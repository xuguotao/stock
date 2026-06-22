"""Historical replay backtest for tail-session live selection."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from pydantic import BaseModel, Field, field_validator

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.web.backend.tail_live import TailLiveSelectionRequest, run_tail_live_selection


ProgressCallback = Callable[[int, str, str], None]
Selector = Callable[[TailLiveSelectionRequest, ProgressCallback | None], dict[str, Any]]
OutcomeProvider = Callable[..., dict[str, Any] | None]

DEFAULT_CUTOFF_TIMES = ["14:30", "14:35", "14:40", "14:45", "14:50", "14:55"]


class TailReplayBacktestRequest(BaseModel):
    """Request body for replaying live tail-session selection over historical cutoffs."""

    start: date
    end: date
    cutoff_times: list[str] = Field(default_factory=lambda: list(DEFAULT_CUTOFF_TIMES))
    symbols: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=6000)
    universe: str = "default"
    top_n: int = Field(default=5, ge=1, le=50)
    min_strength: float | None = Field(default=None, ge=0, le=1)
    confirmations: int = Field(default=1, ge=1, le=10)
    preview_window_bars: int = Field(default=6, ge=2, le=48)
    min_market_breadth_above_ma20: float | None = Field(default=None, ge=0, le=1)
    liquidity_min_bars: int = Field(default=60, ge=1)
    min_optimizer_samples: int = Field(default=3, ge=1)
    output_dir: str = "reports/tail_session/replay"

    @field_validator("cutoff_times")
    @classmethod
    def validate_cutoff_times(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("cutoff_times must not be empty")
        for item in value:
            _parse_time(item)
        return value


def run_tail_replay_backtest(
    request: TailReplayBacktestRequest,
    progress: ProgressCallback | None = None,
    *,
    selector: Selector = run_tail_live_selection,
    outcome_provider: OutcomeProvider | None = None,
) -> dict[str, Any]:
    """Replay the live selector at historical 5-minute cutoffs and summarize next-day returns."""
    dates = _calendar_dates(request.start, request.end)
    cutoffs = [_parse_time(item) for item in request.cutoff_times]
    total_runs = max(1, len(dates) * len(cutoffs))
    provider = outcome_provider or ClickHouseReplayOutcomeProvider()

    details: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    completed = 0
    for trade_date in dates:
        for cutoff in cutoffs:
            completed += 1
            _report_progress(
                progress,
                5 + int(completed / total_runs * 85),
                "replaying",
                f"回放 {trade_date.isoformat()} {cutoff.strftime('%H:%M')}",
            )
            replay_request = _selection_request(request, trade_date=trade_date, cutoff=cutoff)
            try:
                selection = selector(replay_request, progress=None)
            except ValueError as exc:
                run_rows.append(_skipped_run(trade_date, cutoff, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - keep batch replay running and expose failed slice.
                run_rows.append(_failed_run(trade_date, cutoff, str(exc)))
                continue

            selected_rows = list(selection.get("selections") or selection.get("preview_signals") or [])
            run_rows.append(_run_row(trade_date, cutoff, selection, len(selected_rows)))
            for index, row in enumerate(selected_rows, start=1):
                signal_row = dict(row)
                signal_row.setdefault("rank", index)
                detail = _detail_row(
                    trade_date=trade_date,
                    cutoff=cutoff,
                    selection=selection,
                    signal=signal_row,
                    outcome_provider=provider,
                )
                details.append(detail)

    summary = _summary(run_rows, details)
    by_cutoff = _by_cutoff(run_rows, details)
    factor_diagnostics = _factor_diagnostics(details)
    optimization_grid = _optimization_grid(details, max_top_n=request.top_n, min_samples=request.min_optimizer_samples)
    strategy_recommendation = _strategy_recommendation(by_cutoff, factor_diagnostics, optimization_grid)
    return {
        "request": request.model_dump(mode="json"),
        "summary": summary,
        "by_cutoff": by_cutoff,
        "factor_diagnostics": factor_diagnostics,
        "optimization_grid": optimization_grid,
        "strategy_recommendation": strategy_recommendation,
        "runs": run_rows,
        "details": details,
        "notes": [
            "回放每个 cutoff 时只把 as_of_time 传给今日尾盘选股，分钟扫描不会读取 cutoff 之后的 5m K。",
            "收益使用次一交易日分钟线优先计算；分钟线缺失时可由日线兜底。",
            "14:30-14:45 属于盘中预演，14:50 之后才按正式尾盘选择口径统计。",
        ],
    }


class ClickHouseReplayOutcomeProvider:
    """Compute next-session outcome from ClickHouse minute5 first, daily fallback second."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = ClickHouseStockDataSource()._client_instance()
        return self._client

    def __call__(self, *, signal_date: date, symbol: str, signal_price: float) -> dict[str, Any] | None:
        return self._minute_outcome(signal_date=signal_date, symbol=symbol, signal_price=signal_price) or self._daily_outcome(
            signal_date=signal_date,
            symbol=symbol,
            signal_price=signal_price,
        )

    def _minute_outcome(self, *, signal_date: date, symbol: str, signal_price: float) -> dict[str, Any] | None:
        date_rows = self.client.execute(
            """
            select min(toDate(datetime))
            from minute5_kline
            where symbol = %(symbol)s and toDate(datetime) > %(signal_date)s
            """,
            {"symbol": _code(symbol), "signal_date": signal_date},
        )
        if not date_rows or date_rows[0][0] is None:
            return None
        outcome_date = _as_date(date_rows[0][0])
        rows = self.client.execute(
            """
            select datetime, open, high, low, close
            from minute5_kline
            where symbol = %(symbol)s and toDate(datetime) = %(outcome_date)s
            order by datetime
            """,
            {"symbol": _code(symbol), "outcome_date": outcome_date},
        )
        if not rows:
            return None
        next_open = float(rows[0][1])
        next_high = max(float(row[2]) for row in rows)
        next_low = min(float(row[3]) for row in rows)
        next_close = float(rows[-1][4])
        outcome = _outcome_dict(
            signal_date=signal_date,
            outcome_date=outcome_date,
            symbol=symbol,
            signal_price=signal_price,
            next_open=next_open,
            next_high=next_high,
            next_low=next_low,
            next_close=next_close,
            source="minute5",
        )
        outcome.update(_simulate_next_day_exit(rows, signal_price=signal_price))
        return outcome

    def _daily_outcome(self, *, signal_date: date, symbol: str, signal_price: float) -> dict[str, Any] | None:
        rows = self.client.execute(
            """
            select date, open, high, low, close
            from daily_kline
            where symbol = %(symbol)s and date > %(signal_date)s
            order by date
            limit 1
            """,
            {"symbol": _code(symbol), "signal_date": signal_date},
        )
        if not rows:
            return None
        outcome_date, next_open, next_high, next_low, next_close = rows[0]
        return _outcome_dict(
            signal_date=signal_date,
            outcome_date=_as_date(outcome_date),
            symbol=symbol,
            signal_price=signal_price,
            next_open=float(next_open),
            next_high=float(next_high),
            next_low=float(next_low),
            next_close=float(next_close),
            source="daily",
        )


def _selection_request(request: TailReplayBacktestRequest, *, trade_date: date, cutoff: time) -> TailLiveSelectionRequest:
    return TailLiveSelectionRequest(
        trade_date=trade_date,
        symbols=request.symbols,
        limit=request.limit,
        universe=request.universe,  # type: ignore[arg-type]
        liquidity_min_bars=request.liquidity_min_bars,
        min_market_breadth_above_ma20=request.min_market_breadth_above_ma20,
        confirmations=request.confirmations,
        preview_window_bars=request.preview_window_bars,
        top_n=request.top_n,
        min_strength=request.min_strength,
        as_of_time=cutoff,
        ignore_session=True,
        auto_sync_minute5=False,
        output_dir=request.output_dir,
    )


def _detail_row(
    *,
    trade_date: date,
    cutoff: time,
    selection: dict[str, Any],
    signal: dict[str, Any],
    outcome_provider: OutcomeProvider,
) -> dict[str, Any]:
    signal_price = _positive_float(signal.get("last_price"))
    outcome = None
    if signal_price is not None and signal.get("symbol"):
        outcome = outcome_provider(
            signal_date=trade_date,
            symbol=str(signal["symbol"]),
            signal_price=signal_price,
        )
    return {
        "trade_date": trade_date.isoformat(),
        "cutoff_time": cutoff.strftime("%H:%M"),
        "mode": selection.get("mode"),
        "symbol": signal.get("symbol"),
        "rank": signal.get("rank"),
        "strength": signal.get("strength"),
        "last_price": signal.get("last_price"),
        "volume_ratio": signal.get("volume_ratio"),
        "tail_return": signal.get("tail_return"),
        "v2_score": signal.get("v2_score"),
        "v2_layer": signal.get("v2_layer"),
        "score_breakdown": signal.get("score_breakdown") or {},
        "outcome": outcome,
    }


def _run_row(trade_date: date, cutoff: time, selection: dict[str, Any], selected_count: int) -> dict[str, Any]:
    return {
        "trade_date": trade_date.isoformat(),
        "cutoff_time": cutoff.strftime("%H:%M"),
        "status": "success",
        "mode": selection.get("mode"),
        "scanned_count": selection.get("scanned_count", 0),
        "candidate_count": selection.get("candidate_count", 0),
        "selected_count": selected_count,
        "data_freshness": selection.get("data_freshness") or selection.get("diagnostics", {}).get("data_freshness"),
        "empty_reason": (selection.get("diagnostics") or {}).get("empty_reason"),
    }


def _skipped_run(trade_date: date, cutoff: time, reason: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date.isoformat(),
        "cutoff_time": cutoff.strftime("%H:%M"),
        "status": "skipped",
        "selected_count": 0,
        "skip_reason": reason,
    }


def _failed_run(trade_date: date, cutoff: time, error: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date.isoformat(),
        "cutoff_time": cutoff.strftime("%H:%M"),
        "status": "failed",
        "selected_count": 0,
        "error": error,
    }


def _summary(runs: list[dict[str, Any]], details: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [_outcome(detail) for detail in details]
    outcomes = [item for item in outcomes if item is not None]
    return {
        "total_runs": len(runs),
        "success_runs": sum(1 for row in runs if row.get("status") == "success"),
        "failed_runs": sum(1 for row in runs if row.get("status") == "failed"),
        "skipped_runs": sum(1 for row in runs if row.get("status") == "skipped"),
        "total_selected": len(details),
        "outcome_count": len(outcomes),
        **_return_stats(outcomes),
    }


def _by_cutoff(runs: list[dict[str, Any]], details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_details: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in runs:
        grouped_runs[str(row["cutoff_time"])].append(row)
    for row in details:
        grouped_details[str(row["cutoff_time"])].append(row)
    result = []
    for cutoff in sorted(grouped_runs):
        cutoff_outcomes = [_outcome(detail) for detail in grouped_details.get(cutoff, [])]
        cutoff_outcomes = [item for item in cutoff_outcomes if item is not None]
        run_count = len(grouped_runs[cutoff])
        selected_count = len(grouped_details.get(cutoff, []))
        result.append({
            "cutoff_time": cutoff,
            "run_count": run_count,
            "success_runs": sum(1 for row in grouped_runs[cutoff] if row.get("status") == "success"),
            "selected_count": selected_count,
            "avg_selected_per_run": round(selected_count / run_count, 4) if run_count else 0.0,
            **_return_stats(cutoff_outcomes),
        })
    return result


def _factor_diagnostics(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    factors = ["strength", "volume_ratio", "tail_return"]
    breakdown_factors = ["strength", "volume_ratio", "tail_return"]
    rows = []
    for factor in factors:
        rows.append(_factor_row(factor, details, value_getter=lambda detail, key=factor: _positive_float(detail.get(key))))
    for factor in breakdown_factors:
        rows.append(_factor_row(
            f"score_{factor}",
            details,
            value_getter=lambda detail, key=factor: _positive_float((detail.get("score_breakdown") or {}).get(key)),
        ))
    return [row for row in rows if row["sample_count"] > 0]


def _strategy_recommendation(
    by_cutoff: list[dict[str, Any]],
    factor_diagnostics: list[dict[str, Any]],
    optimization_grid: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cutoff_candidates = [
        row for row in by_cutoff
        if row.get("selected_count", 0) and row.get("avg_close_return") is not None
    ]
    best = max(
        cutoff_candidates,
        key=lambda row: (
            float(row.get("avg_close_return") or 0),
            float(row.get("win_rate_close") or 0),
            int(row.get("selected_count") or 0),
        ),
        default=None,
    )
    recommended_filters = [
        {
            "factor": row["factor"],
            "direction": "prefer_high",
            "spread": row.get("spread"),
            "sample_count": row.get("sample_count"),
            "reason": f"高分组三分位收盘收益比低分组高 {float(row.get('spread') or 0) * 100:.2f}%。",
        }
        for row in factor_diagnostics
        if float(row.get("spread") or 0) > 0
    ]
    recommended_filters.sort(key=lambda row: float(row.get("spread") or 0), reverse=True)
    best_plan = optimization_grid[0] if optimization_grid else None
    return {
        "best_cutoff_time": best.get("cutoff_time") if best else None,
        "best_cutoff_reason": (
            f"{best.get('cutoff_time')} 平均收盘收益 {float(best.get('avg_close_return') or 0) * 100:.2f}%，"
            f"收盘胜率 {float(best.get('win_rate_close') or 0) * 100:.2f}%。"
            if best else "暂无可复核收益样本，不能给出时间点建议。"
        ),
        "best_plan": best_plan,
        "best_plan_reason": (
            f"{best_plan.get('cutoff_time')} / Top {best_plan.get('top_n')} 的策略卖出收益 "
            f"{float(best_plan.get('avg_policy_return') or 0) * 100:.2f}%，"
            f"策略胜率 {float(best_plan.get('win_rate_policy') or 0) * 100:.2f}%。"
            if best_plan else "暂无足够样本生成参数组合建议。"
        ),
        "recommended_filters": recommended_filters[:5],
        "risk_note": "该建议来自历史样本统计，不保证未来收益；样本越少，越应降低置信度。",
    }


def _optimization_grid(
    details: list[dict[str, Any]],
    *,
    max_top_n: int,
    min_samples: int,
) -> list[dict[str, Any]]:
    cutoffs = sorted({str(detail.get("cutoff_time")) for detail in details if detail.get("cutoff_time")})
    rows = []
    for cutoff in cutoffs:
        cutoff_details = [detail for detail in details if detail.get("cutoff_time") == cutoff]
        for top_n in range(1, max(1, max_top_n) + 1):
            selected = [
                detail for detail in cutoff_details
                if _rank_value(detail.get("rank")) <= top_n
            ]
            outcomes = [_outcome(detail) for detail in selected]
            outcomes = [outcome for outcome in outcomes if outcome is not None]
            if len(outcomes) < min_samples:
                continue
            stats = _return_stats(outcomes)
            row = {
                "cutoff_time": cutoff,
                "top_n": top_n,
                "sample_count": len(outcomes),
                **stats,
            }
            row["score"] = _optimization_score(row)
            rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("score") or 0),
            float(row.get("avg_policy_return") or row.get("avg_close_return") or 0),
            float(row.get("win_rate_policy") or row.get("win_rate_close") or 0),
            int(row.get("sample_count") or 0),
        ),
        reverse=True,
    )


def _optimization_score(row: dict[str, Any]) -> float:
    policy_return = float(row.get("avg_policy_return") or row.get("avg_close_return") or 0)
    win_rate = float(row.get("win_rate_policy") or row.get("win_rate_close") or 0)
    max_loss = abs(float(row.get("max_loss") or 0))
    sample_bonus = min(0.01, int(row.get("sample_count") or 0) * 0.0005)
    return round(policy_return + win_rate * 0.01 - max_loss * 0.15 + sample_bonus, 6)


def _factor_row(
    factor: str,
    details: list[dict[str, Any]],
    *,
    value_getter: Callable[[dict[str, Any]], float | None],
) -> dict[str, Any]:
    samples = []
    for detail in details:
        outcome = _outcome(detail)
        value = value_getter(detail)
        if outcome is None or value is None:
            continue
        samples.append((value, outcome))
    if not samples:
        return {"factor": factor, "sample_count": 0}
    samples.sort(key=lambda item: item[0], reverse=True)
    top = [item[1] for item in samples[: max(1, len(samples) // 3)]]
    bottom = [item[1] for item in samples[-max(1, len(samples) // 3):]]
    return {
        "factor": factor,
        "sample_count": len(samples),
        "top_avg_close_return": _avg([item["close_return"] for item in top]),
        "bottom_avg_close_return": _avg([item["close_return"] for item in bottom]),
        "spread": round(_avg([item["close_return"] for item in top]) - _avg([item["close_return"] for item in bottom]), 6),
        "interpretation": "高值更优" if _avg([item["close_return"] for item in top]) >= _avg([item["close_return"] for item in bottom]) else "高值未体现优势",
    }


def _return_stats(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    if not outcomes:
        return {
            "win_rate_open": None,
            "win_rate_close": None,
            "win_rate_max": None,
            "win_rate_policy": None,
            "avg_open_return": None,
            "avg_close_return": None,
            "avg_max_return": None,
            "avg_min_return": None,
            "avg_policy_return": None,
            "max_loss": None,
        }
    policy_returns = [
        float(item["policy_return"])
        for item in outcomes
        if item.get("policy_return") is not None
    ]
    return {
        "win_rate_open": _rate([item["open_return"] > 0 for item in outcomes]),
        "win_rate_close": _rate([item["close_return"] > 0 for item in outcomes]),
        "win_rate_max": _rate([item["max_return"] > 0 for item in outcomes]),
        "win_rate_policy": _rate([item > 0 for item in policy_returns]) if policy_returns else None,
        "avg_open_return": _avg([item["open_return"] for item in outcomes]),
        "avg_close_return": _avg([item["close_return"] for item in outcomes]),
        "avg_max_return": _avg([item["max_return"] for item in outcomes]),
        "avg_min_return": _avg([item["min_return"] for item in outcomes]),
        "avg_policy_return": _avg(policy_returns) if policy_returns else None,
        "max_loss": min(item["min_return"] for item in outcomes),
    }


def _outcome(detail: dict[str, Any]) -> dict[str, Any] | None:
    outcome = detail.get("outcome")
    return outcome if isinstance(outcome, dict) else None


def _rank_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999999


def _outcome_dict(
    *,
    signal_date: date,
    outcome_date: date,
    symbol: str,
    signal_price: float,
    next_open: float,
    next_high: float,
    next_low: float,
    next_close: float,
    source: str,
) -> dict[str, Any]:
    return {
        "signal_date": signal_date.isoformat(),
        "outcome_date": outcome_date.isoformat(),
        "symbol": symbol,
        "signal_price": signal_price,
        "next_open": next_open,
        "next_high": next_high,
        "next_low": next_low,
        "next_close": next_close,
        "open_return": round(next_open / signal_price - 1, 6),
        "max_return": round(next_high / signal_price - 1, 6),
        "min_return": round(next_low / signal_price - 1, 6),
        "close_return": round(next_close / signal_price - 1, 6),
        "source": source,
    }


def _simulate_next_day_exit(
    rows: list[tuple[Any, ...]],
    *,
    signal_price: float,
    take_profit_return: float = 0.01,
    stop_loss_return: float = -0.02,
    gap_stop_return: float = -0.015,
) -> dict[str, Any]:
    if not rows:
        return {"policy_return": None, "policy_exit": "missing"}
    next_open = float(rows[0][1])
    open_return = next_open / signal_price - 1
    if open_return <= gap_stop_return:
        return {"policy_return": round(open_return, 6), "policy_exit": "gap_stop"}
    if open_return >= take_profit_return:
        return {"policy_return": round(open_return, 6), "policy_exit": "gap_take_profit"}

    take_price = signal_price * (1 + take_profit_return)
    stop_price = signal_price * (1 + stop_loss_return)
    for _, _open, high, low, _close in rows:
        high_value = float(high)
        low_value = float(low)
        if low_value <= stop_price and high_value >= take_price:
            return {"policy_return": round(stop_loss_return, 6), "policy_exit": "ambiguous_stop_first"}
        if low_value <= stop_price:
            return {"policy_return": round(stop_loss_return, 6), "policy_exit": "stop_loss"}
        if high_value >= take_price:
            return {"policy_return": round(take_profit_return, 6), "policy_exit": "take_profit"}
    close_return = float(rows[-1][4]) / signal_price - 1
    return {"policy_return": round(close_return, 6), "policy_exit": "close"}


def _calendar_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end must be greater than or equal to start")
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _parse_time(value: str) -> time:
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"Invalid cutoff time: {value}") from exc
    if parsed < time(14, 30) or parsed > time(14, 55):
        raise ValueError(f"cutoff time must be between 14:30 and 14:55: {value}")
    return parsed


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _rate(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values), 6) if values else 0.0


def _code(symbol: str) -> str:
    return str(symbol).split(".")[0].zfill(6)


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _report_progress(progress: ProgressCallback | None, percent: int, stage: str, message: str) -> None:
    if progress is not None:
        progress(percent, stage, message)
