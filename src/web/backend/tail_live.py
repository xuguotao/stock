"""Live tail-session selection API helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Literal

import pandas as pd
from pydantic import BaseModel, Field

from config.settings import reset_settings
from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.data.strategy_universe import StrategyUniverseOptions, resolve_strategy_universe
from src.ml.tail_features import build_daily_model_feature_context
from src.ml.tail_model import _risk_adjusted_score
from src.strategy.reports import (
    select_tail_session_signals,
    tail_session_selection_rows,
    write_tail_session_report,
    write_tail_session_selection_csv,
    write_tail_session_selection_json,
)
from src.strategy.scanner import IntradayScanner
from src.strategy.tail_session.live import calculate_market_breadth_above_ma20, resolve_scan_symbols
from src.strategy.tail_session.v2_scorer import LayeredSignal, score_tail_signals
from src.trading.scheduler import TradingScheduler


ProgressCallback = Callable[[int, str, str], None]
FINAL_SELECTION_START = time(14, 50)


class TailLiveSelectionRequest(BaseModel):
    """Request body for today's tail-session selection jobs."""

    trade_date: date = Field(default_factory=date.today)
    symbols: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=6000)
    universe: Literal["default", "liquid-cache"] = "default"
    bars_cache_dir: str = "data/cache/bars"
    liquidity_start: date | None = None
    liquidity_end: date | None = None
    liquidity_min_bars: int = Field(default=60, ge=1)
    liquidity_min_end_date: date | None = None
    min_market_breadth_above_ma20: float | None = Field(default=None, ge=0, le=1)
    confirmations: int = Field(default=1, ge=1, le=10)
    preview_window_bars: int = Field(default=6, ge=2, le=48)
    top_n: int = Field(default=2, ge=1, le=50)
    min_strength: float | None = Field(default=None, ge=0, le=1)
    as_of_time: time | None = None
    ignore_session: bool = False
    auto_sync_minute5: bool = True
    data_refresh_mode: Literal["auto", "snapshot", "standard_minute5", "none"] = "auto"
    strategy_mode: Literal["rule", "model", "hybrid"] = "rule"
    output_dir: str = "reports/tail_session"


def run_tail_live_selection(
    request: TailLiveSelectionRequest,
    progress: ProgressCallback | None = None,
    *,
    model_scorer: Any | None = None,
) -> dict[str, Any]:
    """Run a selection-only live tail-session scan and return UI-friendly output."""
    reset_settings()
    scheduler = TradingScheduler()
    if not request.ignore_session and not scheduler.is_tail_session():
        raise ValueError("当前不在 14:30-15:00 尾盘窗口；如需盘外试跑，请打开「忽略时间窗口」。")
    if not scheduler.is_trading_day(request.trade_date):
        raise ValueError(f"{request.trade_date.isoformat()} is not a trading day.")

    timings: dict[str, float] = {}
    _report_progress(progress, 10, "resolving_universe", "解析今日扫描股票池")
    stage_started = perf_counter()
    aggregator = DataAggregator()
    liquidity_start = request.liquidity_start or request.trade_date - timedelta(days=548)
    liquidity_end = request.liquidity_end or request.trade_date
    symbols = _resolve_tail_scan_symbols(
        aggregator=aggregator,
        request=request,
        liquidity_start=liquidity_start,
        liquidity_end=liquidity_end,
    )
    intraday_coverage = _intraday_coverage(aggregator, symbols, request.trade_date)
    scan_as_of_time = _scan_as_of_time(request, scheduler)
    data_freshness = _data_freshness(intraday_coverage, scan_as_of_time=scan_as_of_time)
    timings["resolve_and_coverage"] = _elapsed(stage_started)

    _report_progress(progress, 30, "market_breadth", "计算市场宽度过滤")
    stage_started = perf_counter()
    breadth_result = None
    candidates = []
    confirmed = []
    selected = []
    quotes, quote_status = _safe_realtime_quotes(aggregator, symbols)
    if request.min_market_breadth_above_ma20 is not None:
        breadth_result = calculate_market_breadth_above_ma20(
            symbols=symbols,
            bars_cache_dir=request.bars_cache_dir,
            trade_date=request.trade_date,
            quotes=quotes,
        )
        if breadth_result.breadth < request.min_market_breadth_above_ma20:
            return _write_live_selection_result(
                request=request,
                symbols=symbols,
                intraday_coverage=intraday_coverage,
                candidates=candidates,
                confirmed=confirmed,
                selected=selected,
                breadth_result=breadth_result,
                blocked_by_market_breadth=True,
                scan_as_of_time=scan_as_of_time,
                data_freshness=data_freshness,
                quote_status=quote_status,
                stage_timings=timings,
                progress=progress,
                model_scorer=model_scorer,
            )
    timings["quote_and_breadth"] = _elapsed(stage_started)

    _report_progress(progress, 55, "scanning_intraday", "扫描尾盘分钟信号")
    stage_started = perf_counter()
    scanner = IntradayScanner(
        aggregator,
        confirmation_count=request.confirmations,
        max_bar_time=scan_as_of_time,
    )
    if _latest_time_before_final_selection(intraday_coverage, scan_as_of_time):
        ranked_pool, candidates = scanner.scan_preview_with_rank(
            symbols,
            request.trade_date,
            preview_window_bars=request.preview_window_bars,
        )
        confirmed = candidates
        signal_mode = "preview"
    else:
        ranked_pool, candidates = scanner.scan_with_rank(symbols, request.trade_date)
        confirmed = scanner.confirm(candidates)
        signal_mode = "selection"
    selected = select_tail_session_signals(
        confirmed,
        top_n=request.top_n,
        min_strength=request.min_strength,
    )
    model_feature_context = (
        _live_model_feature_context(aggregator, symbols=symbols, trade_date=request.trade_date)
        if model_scorer is not None and request.strategy_mode != "rule"
        else {}
    )
    timings["scan_intraday"] = _elapsed(stage_started)
    return _write_live_selection_result(
        request=request,
        symbols=symbols,
        intraday_coverage=intraday_coverage,
        candidates=candidates,
        confirmed=confirmed,
        selected=selected,
        ranked_pool=ranked_pool,
        signal_mode=signal_mode,
        breadth_result=breadth_result,
        blocked_by_market_breadth=False,
        scan_as_of_time=scan_as_of_time,
        quotes=quotes,
        data_freshness=data_freshness,
        quote_status=quote_status,
        stage_timings=timings,
        progress=progress,
        model_scorer=model_scorer,
        model_feature_context=model_feature_context,
    )


def _write_live_selection_result(
    *,
    request: TailLiveSelectionRequest,
    symbols: list[str],
    intraday_coverage: dict[str, Any],
    candidates: list[Any],
    confirmed: list[Any],
    selected: list[Any],
    ranked_pool: list[Any] | None = None,
    signal_mode: str = "selection",
    breadth_result: Any | None,
    blocked_by_market_breadth: bool,
    scan_as_of_time: time | None,
    quotes: Any | None = None,
    data_freshness: dict[str, Any] | None = None,
    quote_status: dict[str, Any] | None = None,
    stage_timings: dict[str, float] | None = None,
    progress: ProgressCallback | None,
    model_scorer: Any | None = None,
    model_feature_context: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _report_progress(progress, 80, "writing_outputs", "写入选股结果文件")
    stage_started = perf_counter()
    layered_signals = score_tail_signals(ranked_pool or [])
    layered_by_symbol = {row.symbol: row for row in layered_signals}
    mode = _result_mode_from_signal_mode(signal_mode)
    preview_signals = selected if mode == "preview" else []
    tradability_by_symbol = _tradability_by_symbol(quotes)
    stale_final_data = _is_stale_for_final_selection(data_freshness)
    final_selected = _final_trade_candidates(
        confirmed,
        top_n=request.top_n,
        min_strength=request.min_strength,
        tradability_by_symbol=tradability_by_symbol,
    ) if mode == "selection" and not stale_final_data else []

    output_dir = Path(request.output_dir)
    json_path = output_dir / "latest_selection.json"
    csv_path = output_dir / "latest_selection.csv"
    written_json = write_tail_session_selection_json(json_path, final_selected, trade_date=request.trade_date)
    written_csv = write_tail_session_selection_csv(csv_path, final_selected)
    report_path = write_tail_session_report(
        output_dir=output_dir,
        trade_date=request.trade_date,
        scanned_count=len(symbols),
        candidates=candidates,
        confirmed=confirmed,
        selected=final_selected,
        trades=[],
        account_summary={},
    )
    diagnostics = _diagnostics(
        symbols=symbols,
        intraday_coverage=intraday_coverage,
        ranked_pool=ranked_pool,
        signal_mode=signal_mode,
        candidates=candidates,
        confirmed=confirmed,
        selected=final_selected,
        breadth_result=breadth_result,
        blocked_by_market_breadth=blocked_by_market_breadth,
        requested_scan_limit=request.limit,
        strategy_mode=request.strategy_mode,
        scan_as_of_time=scan_as_of_time,
        data_freshness=data_freshness,
        quote_status=quote_status,
    )
    timings = dict(stage_timings or {})
    timings["write_outputs"] = _elapsed(stage_started)
    result = {
        "mode": mode,
        "trade_date": request.trade_date.isoformat(),
        "scanned_count": len(symbols),
        "candidate_count": len(candidates),
        "confirmed_count": len(confirmed),
        "selected_count": len(final_selected),
        "preview_count": len(preview_signals),
        "selections": _signal_rows_with_credibility(
            final_selected,
            mode=mode,
            layered_by_symbol=layered_by_symbol,
        ),
        "preview_signals": _signal_rows_with_credibility(
            preview_signals,
            mode=mode,
            layered_by_symbol=layered_by_symbol,
        ),
        "ranked_signals": _ranked_signal_rows(
            confirmed=confirmed,
            selected=final_selected,
            preview=preview_signals,
            ranked_pool=ranked_pool,
            mode=mode,
            top_n=request.top_n,
            min_strength=request.min_strength,
            layered_by_symbol=layered_by_symbol,
            tradability_by_symbol=tradability_by_symbol,
        ),
        "signal_layers": _signal_layer_counts(layered_signals),
        "watchlist_signals": _layered_rows(layered_signals, "watchlist", mode=mode),
        "weak_signals": _layered_rows(layered_signals, "weak", mode=mode),
        "files": {
            "json": str(written_json),
            "csv": str(written_csv),
            "report": str(report_path),
        },
        "market_breadth": _market_breadth_row(breadth_result),
        "diagnostics": diagnostics,
        "precheck_rows": _precheck_rows(intraday_coverage) if mode == "precheck" else [],
        "strategy_rules": _strategy_rules(request),
        "stage_timings": timings,
    }
    _apply_model_scores(
        result,
        strategy_mode=request.strategy_mode,
        model_scorer=model_scorer,
        model_feature_context=model_feature_context,
    )
    return result


MODEL_SCORE_SECTIONS = (
    "ranked_signals",
    "selections",
    "preview_signals",
    "watchlist_signals",
    "weak_signals",
)
MODEL_SCORE_RANK_LIMIT = 300


def _apply_model_scores(
    result: dict[str, Any],
    *,
    strategy_mode: str,
    model_scorer: Any | None,
    model_feature_context: dict[str, dict[str, Any]] | None = None,
) -> None:
    diagnostics = result.setdefault("diagnostics", {})
    diagnostics["strategy_mode"] = strategy_mode
    if strategy_mode == "rule":
        diagnostics["effective_strategy_mode"] = "rule"
        diagnostics["model_status"] = "disabled"
        return
    if model_scorer is None:
        diagnostics["effective_strategy_mode"] = "rule"
        diagnostics["model_status"] = "no_promoted_model"
        return

    rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for section in MODEL_SCORE_SECTIONS:
        rows = result.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not _should_score_model_row(section, row):
                continue
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            rows_by_symbol.setdefault(symbol, []).append(row)

    if not rows_by_symbol:
        diagnostics["effective_strategy_mode"] = "rule"
        diagnostics["model_status"] = "no_scoreable_rows"
        return

    feature_rows = [
        _model_feature_row(rows[0], model_feature_context=model_feature_context)
        for rows in rows_by_symbol.values()
    ]
    scores = model_scorer.score(pd.DataFrame(feature_rows))
    scored_by_symbol = {
        str(row.get("symbol")): row
        for row in scores
        if isinstance(row, dict) and row.get("symbol")
    }
    for symbol, rows in rows_by_symbol.items():
        score = scored_by_symbol.get(symbol)
        if not score:
            continue
        model_payload = {
            "model_version": score.get("model_version"),
            "model_score": score.get("model_score"),
            "hit_probability": score.get("hit_probability"),
            "expected_high_return": score.get("expected_high_return"),
            "risk_probability": score.get("risk_probability"),
            "feature_snapshot": score.get("feature_snapshot") or [],
        }
        for row in rows:
            row["model"] = model_payload

    diagnostics["effective_strategy_mode"] = strategy_mode
    diagnostics["model_status"] = "scored"
    diagnostics["model_scored_symbols"] = len(scored_by_symbol)
    diagnostics["model_score_rank_limit"] = MODEL_SCORE_RANK_LIMIT
    _apply_model_selection(result, strategy_mode=strategy_mode)


def _should_score_model_row(section: str, row: dict[str, Any]) -> bool:
    if section in {"selections", "preview_signals"}:
        return True
    if section != "ranked_signals":
        return False
    if row.get("status") in {"selected", "preview"}:
        return True
    if row.get("final_candidate_rank") is not None:
        return True
    rank = row.get("rank")
    if rank is None:
        return True
    try:
        return int(rank) <= MODEL_SCORE_RANK_LIMIT
    except (TypeError, ValueError):
        return False


def _apply_model_selection(result: dict[str, Any], *, strategy_mode: str) -> None:
    ranked = result.get("ranked_signals")
    if strategy_mode not in {"model", "hybrid"} or not isinstance(ranked, list):
        return
    selected_count = int(result.get("selected_count") or len(result.get("selections") or []) or 0)
    if selected_count <= 0:
        result.setdefault("diagnostics", {})["model_selection_applied"] = False
        return

    candidates = [
        row for row in ranked
        if isinstance(row, dict)
        and row.get("final_candidate_rank") is not None
        and isinstance(row.get("model"), dict)
        and (row.get("tradability") or {}).get("buyable", True)
    ]
    if not candidates:
        result.setdefault("diagnostics", {})["model_selection_applied"] = False
        return

    model_ranked = sorted(candidates, key=lambda row: _model_selection_score(row, strategy_mode=strategy_mode), reverse=True)
    selected_symbols = {str(row.get("symbol")) for row in model_ranked[:selected_count]}
    for row in ranked:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol")) in selected_symbols:
            row["status"] = "selected"
            row["filter_reason"] = None
        elif row.get("status") == "selected":
            row["status"] = "filtered"
            row["filter_reason"] = "outside_model_top_n"

    ranked.sort(key=lambda row: _model_ranked_display_key(row, selected_symbols=selected_symbols, strategy_mode=strategy_mode))
    for index, row in enumerate(ranked, start=1):
        if isinstance(row, dict):
            row["rank"] = index
    result["selections"] = [row for row in ranked if isinstance(row, dict) and str(row.get("symbol")) in selected_symbols]
    result["selected_count"] = len(result["selections"])
    diagnostics = result.setdefault("diagnostics", {})
    diagnostics["model_selection_applied"] = True
    diagnostics["model_selection_mode"] = strategy_mode


def _model_feature_row(
    row: dict[str, Any],
    *,
    model_feature_context: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    feature_row = dict(row)
    symbol = str(row.get("symbol") or "")
    if model_feature_context and symbol in model_feature_context:
        feature_row.update(model_feature_context[symbol])
    aliases = {
        "tail_return_from_1430": "tail_return",
        "tail_high_return_from_1430": "tail_high_return",
        "tail_pullback_from_high": "pullback_from_high",
        "tail_volume_ratio": "volume_ratio",
    }
    for target, source in aliases.items():
        if target not in feature_row and source in feature_row:
            feature_row[target] = feature_row[source]
    return feature_row


def _model_ranked_display_key(
    row: Any,
    *,
    selected_symbols: set[str],
    strategy_mode: str,
) -> tuple[Any, ...]:
    if not isinstance(row, dict):
        return (3, 0)
    symbol = str(row.get("symbol"))
    candidate = row.get("final_candidate_rank") is not None and isinstance(row.get("model"), dict)
    return (
        0 if symbol in selected_symbols else 1 if candidate else 2,
        -_model_selection_score(row, strategy_mode=strategy_mode),
        row.get("raw_rank") or row.get("rank") or 999999,
    )


def _model_selection_score(row: dict[str, Any], *, strategy_mode: str) -> float:
    model = row.get("model") or {}
    model_score = _risk_adjusted_model_score(model)
    if strategy_mode == "model":
        return model_score
    credibility = row.get("credibility") or {}
    calibrated = _number_or_zero(credibility.get("calibrated_probability"))
    if calibrated > 1:
        calibrated = calibrated / 100
    return model_score * 0.55 + calibrated * 0.45


def _risk_adjusted_model_score(model: dict[str, Any]) -> float:
    hit_probability = _number_or_zero(model.get("hit_probability"))
    expected_high = _number_or_zero(model.get("expected_high_return"))
    risk_probability = _number_or_zero(model.get("risk_probability"))
    high_rank_proxy = _number_or_zero(model.get("model_score"))
    return _risk_adjusted_score(
        hit_probability=hit_probability,
        high_rank=high_rank_proxy,
        expected_high_return=expected_high,
        risk_probability=risk_probability,
    )


def _number_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _result_mode_from_signal_mode(signal_mode: str) -> str:
    return "preview" if signal_mode == "preview" else "selection"


def _final_trade_candidates(
    confirmed: list[Any],
    *,
    top_n: int,
    min_strength: float | None,
    tradability_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> list[Any]:
    trade_candidates = _trade_candidate_layered(
        confirmed,
        min_strength=min_strength,
        tradability_by_symbol=tradability_by_symbol,
    )
    selected = [row.signal for row in trade_candidates]
    if top_n is None or top_n <= 0:
        return selected
    return selected[:top_n]


def _trade_candidate_layered(
    signals: list[Any],
    *,
    min_strength: float | None,
    tradability_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> list[LayeredSignal]:
    return [
        row for row in score_tail_signals(signals)
        if row.layer == "strong"
        and row.action == "trade_candidate"
        and (min_strength is None or row.signal.strength >= min_strength)
        and _is_buyable(row.signal.symbol, tradability_by_symbol)
    ]


def _safe_realtime_quotes(aggregator: Any, symbols: list[str]) -> tuple[Any | None, dict[str, Any]]:
    if not symbols:
        return None, {"status": "empty_universe", "requested_symbols": 0, "covered_symbols": 0, "coverage_ratio": 0.0}
    getter = getattr(aggregator, "get_realtime_quotes", None)
    if getter is None:
        return None, {"status": "unavailable", "requested_symbols": len(symbols), "covered_symbols": 0, "coverage_ratio": 0.0}
    try:
        quotes = getter(symbols)
    except Exception as exc:
        return None, {
            "status": "failed",
            "requested_symbols": len(symbols),
            "covered_symbols": 0,
            "coverage_ratio": 0.0,
            "error": str(exc),
        }
    if quotes is None or getattr(quotes, "empty", True) or "symbol" not in quotes.columns:
        return quotes, {
            "status": "missing",
            "requested_symbols": len(symbols),
            "covered_symbols": 0,
            "coverage_ratio": 0.0,
        }
    covered = len(set(str(symbol) for symbol in quotes["symbol"].dropna()))
    ratio = covered / len(symbols) if symbols else 0.0
    status = "ok" if ratio >= 0.95 else "partial"
    return quotes, {
        "status": status,
        "requested_symbols": len(symbols),
        "covered_symbols": covered,
        "coverage_ratio": ratio,
    }


def _resolve_tail_scan_symbols(
    *,
    aggregator: Any,
    request: TailLiveSelectionRequest,
    liquidity_start: date,
    liquidity_end: date,
) -> list[str]:
    if not request.symbols and request.universe == "default":
        client = _clickhouse_client_from_aggregator(aggregator)
        if client is not None:
            try:
                symbols = resolve_strategy_universe(
                    client,
                    StrategyUniverseOptions(
                        trade_date=liquidity_end,
                        lookback_start=liquidity_start,
                        min_daily_bars=request.liquidity_min_bars,
                        require_latest_daily=False,
                        require_minute5=False,
                        include_st=False,
                        min_amount=0,
                        markets=("SH", "SZ"),
                    ),
                    symbols_only=True,
                )
                if request.limit > 0:
                    symbols = symbols[:request.limit]
                if symbols:
                    return symbols
            except Exception:
                pass
    return resolve_scan_symbols(
        aggregator=aggregator,
        raw_symbols=request.symbols,
        limit=request.limit,
        universe=request.universe,
        bars_cache_dir=request.bars_cache_dir,
        liquidity_start=liquidity_start,
        liquidity_end=liquidity_end,
        liquidity_min_bars=request.liquidity_min_bars,
        liquidity_min_end_date=request.liquidity_min_end_date,
    )


def _clickhouse_client_from_aggregator(aggregator: Any) -> Any | None:
    for source in getattr(aggregator, "sources", []) or []:
        if getattr(source, "name", "") != "clickhouse":
            continue
        client_getter = getattr(source, "_client_instance", None)
        if client_getter is None:
            continue
        return client_getter()
    return None


def _query_latest_intraday_time(
    aggregator: Any,
    trade_date: date,
    frequency: str = "5m",
) -> time | None:
    """Query ClickHouse for the global max intraday bar time across all symbols.

    Checks three data sources and returns the latest timestamp found:
    - ``stock_quote_snapshots`` (raw real-time snapshots, near-second latency)
    - ``stock_quote_snapshots_5m`` (5-minute aggregated snapshot data)
    - ``minute5_kline`` (batch-synced K-line data)

    The raw snapshots table provides the most timely signal of data pipeline
    health; its ``snapshot_at`` is aligned to the 5-minute bucket grid so the
    comparison with ``scan_as_of_time`` stays consistent.

    Returns the latest bar time as a time object, or None if no data is available.
    """
    client = _clickhouse_client_from_aggregator(aggregator)
    if client is None:
        return None
    start_dt = datetime.combine(trade_date, time(0, 0))
    end_dt = datetime.combine(trade_date, time(23, 59, 59))
    if frequency == "5m":
        minute_table = "minute5_kline"
        minute_time_col = "datetime"
        snapshot_5m_table = "stock_quote_snapshots_5m"
        snapshot_5m_time_col = "bucket_start"
        # Raw snapshots: align to 5-minute bucket grid
        raw_snapshot_query = """
            select toStartOfFiveMinutes(max(snapshot_at)) as latest
            from stock_quote_snapshots
            where snapshot_at >= %(start)s and snapshot_at <= %(end)s
        """
        snapshot_5m_query = f"""
            select max({snapshot_5m_time_col}) as latest
            from {snapshot_5m_table} final
            where {snapshot_5m_time_col} >= %(start)s and {snapshot_5m_time_col} <= %(end)s
        """
        minute_query = f"""
            select max({minute_time_col}) as latest
            from {minute_table} final
            where {minute_time_col} >= %(start)s and {minute_time_col} <= %(end)s
        """
        union_query = f"""
            select max(latest) from (
                {raw_snapshot_query}
                union all
                {snapshot_5m_query}
                union all
                {minute_query}
            )
        """
    else:
        return None
    try:
        rows = client.execute(union_query, {"start": start_dt, "end": end_dt})
        if not rows or not rows[0] or not rows[0][0]:
            return None
        latest_dt = rows[0][0]
        if hasattr(latest_dt, "time"):
            return latest_dt.time()
        return None
    except Exception:
        return None


def _code(symbol: str) -> str:
    return str(symbol).split(".", 1)[0].zfill(6)


def _live_model_feature_context(
    aggregator: Any,
    *,
    symbols: list[str],
    trade_date: date,
) -> dict[str, dict[str, Any]]:
    client = _clickhouse_client_from_aggregator(aggregator)
    if client is None or not symbols:
        return {}
    codes = tuple(_code(symbol) for symbol in symbols)
    rows = client.execute(
        """
        select d.symbol, any(s.industry) as industry, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
        from daily_kline d
        any left join stocks s on d.symbol = s.symbol
        where d.symbol in %(symbols)s
            and d.date >= %(start)s and d.date <= %(end)s
            and d.open > 0 and d.high > 0 and d.low > 0 and d.close > 0 and d.volume > 0
        group by d.symbol, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
        order by d.symbol, d.date
        """,
        {
            "symbols": codes,
            "start": trade_date - timedelta(days=90),
            "end": trade_date,
        },
    )
    if not rows:
        return {}
    frame = pd.DataFrame(
        rows,
        columns=["symbol", "industry", "date", "open", "high", "low", "close", "volume", "amount"],
    )
    frame["symbol"] = frame["symbol"].astype(str).map(format_symbol)
    return build_daily_model_feature_context(frame, trade_date=trade_date)


def _tradability_by_symbol(quotes: Any | None) -> dict[str, dict[str, Any]]:
    if quotes is None or getattr(quotes, "empty", True) or "symbol" not in quotes.columns:
        return {}
    result = {}
    for _, row in quotes.iterrows():
        symbol = str(row.get("symbol", ""))
        if not symbol:
            continue
        price = _float_or_none(row.get("price"))
        limit_up = _float_or_none(row.get("limit_up"))
        limit_up_distance = (limit_up / price - 1.0) if price and limit_up else None
        buyable = True
        reason = None
        execution_flag = "executable"
        score = 100
        if price is not None and limit_up is not None and limit_up > 0 and price >= limit_up * 0.997:
            buyable = False
            reason = "limit_up_not_buyable"
            execution_flag = "blocked_limit_up"
            score = 20
        elif limit_up_distance is not None and limit_up_distance <= 0.02:
            execution_flag = "near_limit_up"
            score = 65
        result[symbol] = {
            "buyable": buyable,
            "reason": reason,
            "price": price,
            "limit_up": limit_up,
            "limit_up_distance": limit_up_distance,
            "execution_flag": execution_flag,
            "score": score,
        }
    return result


def _is_buyable(symbol: str, tradability_by_symbol: dict[str, dict[str, Any]] | None) -> bool:
    if not tradability_by_symbol or symbol not in tradability_by_symbol:
        return True
    return bool(tradability_by_symbol[symbol].get("buyable", True))


def _default_tradability() -> dict[str, Any]:
    return {
        "buyable": True,
        "reason": None,
        "price": None,
        "limit_up": None,
        "limit_up_distance": None,
        "execution_flag": "unknown",
        "score": 50,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _ranked_signal_rows(
    *,
    confirmed: list[Any],
    selected: list[Any],
    preview: list[Any] | None = None,
    ranked_pool: list[Any] | None,
    mode: str,
    top_n: int,
    min_strength: float | None,
    layered_by_symbol: dict[str, LayeredSignal] | None = None,
    tradability_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ordered_source = ranked_pool or confirmed
    effective_layered_by_symbol = layered_by_symbol or {
        row.symbol: row for row in score_tail_signals(ordered_source)
    }
    raw_ordered = select_tail_session_signals(ranked_pool or confirmed, top_n=None, min_strength=None)
    raw_rank_by_symbol = {signal.symbol: index for index, signal in enumerate(raw_ordered, start=1)}
    candidate_rank_by_symbol = {
        row.symbol: index
        for index, row in enumerate(
            _trade_candidate_layered(
                confirmed,
                min_strength=min_strength,
                tradability_by_symbol=tradability_by_symbol,
            ),
            start=1,
        )
    }
    ordered = sorted(
        ordered_source,
        key=lambda signal: _ranked_signal_display_key(
            signal,
            selected=selected,
            candidate_rank_by_symbol=candidate_rank_by_symbol,
            layered_by_symbol=effective_layered_by_symbol,
            tradability_by_symbol=tradability_by_symbol,
        ),
    )
    selected_symbols = {signal.symbol for signal in selected}
    preview_symbols = {signal.symbol for signal in preview or []}
    confirmed_symbols = {signal.symbol for signal in confirmed}
    rows = []
    for index, signal in enumerate(ordered, start=1):
        status = "selected" if signal.symbol in selected_symbols else "filtered"
        filter_reason = None
        layered = effective_layered_by_symbol.get(signal.symbol)
        if mode == "preview" and signal.symbol in preview_symbols:
            status = "preview"
            filter_reason = "preview_not_final"
        elif status == "filtered":
            if signal.symbol not in confirmed_symbols:
                filter_reason = "below_candidate_threshold"
            elif min_strength is not None and signal.strength < min_strength:
                filter_reason = "below_min_strength"
            elif not _is_buyable(signal.symbol, tradability_by_symbol):
                filter_reason = (tradability_by_symbol or {}).get(signal.symbol, {}).get("reason") or "not_buyable"
            elif layered is not None and _has_pullback_risk(layered):
                filter_reason = "tail_pullback_risk"
            elif layered is not None and layered.action != "trade_candidate":
                filter_reason = "v2_not_trade_candidate"
            elif candidate_rank_by_symbol.get(signal.symbol, 0) > top_n > 0:
                filter_reason = "outside_top_n"
            else:
                filter_reason = "not_selected"
        row = _signal_rows_with_credibility(
            [signal],
            mode=mode,
            layered_by_symbol=effective_layered_by_symbol,
        )[0]
        row.update({
            "rank": index,
            "raw_rank": raw_rank_by_symbol.get(signal.symbol),
            "final_candidate_rank": candidate_rank_by_symbol.get(signal.symbol),
            "status": status,
            "filter_reason": filter_reason,
            "tradability": (tradability_by_symbol or {}).get(signal.symbol, _default_tradability()),
            "score_breakdown": _score_breakdown(signal, layered),
        })
        rows.append(row)
    return rows


def _ranked_signal_display_key(
    signal: Any,
    *,
    selected: list[Any],
    candidate_rank_by_symbol: dict[str, int],
    layered_by_symbol: dict[str, LayeredSignal] | None,
    tradability_by_symbol: dict[str, dict[str, Any]] | None,
) -> tuple[Any, ...]:
    selected_symbols = {row.symbol for row in selected}
    layered = (layered_by_symbol or {}).get(signal.symbol)
    candidate_rank = candidate_rank_by_symbol.get(signal.symbol)
    tradability = (tradability_by_symbol or {}).get(signal.symbol, _default_tradability())
    return (
        0 if signal.symbol in selected_symbols else 1,
        0 if candidate_rank is not None else 1,
        candidate_rank or 999999,
        -float(layered.total_score if layered is not None else 0.0),
        0 if _is_buyable(signal.symbol, tradability_by_symbol) else 1,
        -float(tradability.get("score") or 0),
        -float(signal.strength),
        -float(signal.volume_ratio),
        -float(signal.tail_return),
        signal.symbol,
    )


def _score_breakdown(signal: Any, layered: LayeredSignal | None) -> dict[str, Any]:
    volume_component = min(100.0, max(0.0, float(signal.volume_ratio) / 2.5 * 100))
    return_component = min(100.0, max(0.0, float(signal.tail_return) / 0.03 * 100))
    pullback_penalty = min(50.0, abs(min(0.0, float(getattr(signal, "pullback_from_high", 0.0)))) * 500)
    strength_component = min(100.0, max(0.0, float(signal.strength) * 100))
    return {
        "strength": round(strength_component, 2),
        "volume_ratio": round(volume_component, 2),
        "tail_return": round(return_component, 2),
        "pullback_penalty": round(pullback_penalty, 2),
        "v2_total": layered.total_score if layered is not None else None,
        "v2_breakdown": {
            "tail_money": layered.breakdown.tail_money,
            "price_action": layered.breakdown.price_action,
            "liquidity": layered.breakdown.liquidity,
            "risk_control": layered.breakdown.risk_control,
        } if layered is not None else None,
    }


def _signal_rows_with_credibility(
    signals: list[Any],
    *,
    mode: str,
    layered_by_symbol: dict[str, LayeredSignal] | None = None,
) -> list[dict[str, Any]]:
    rows = tail_session_selection_rows(signals)
    for row, signal in zip(rows, signals, strict=False):
        row["credibility"] = _credibility(signal, mode=mode)
        row["next_day_plan"] = _next_day_plan(signal, mode=mode)
        layered = (layered_by_symbol or {}).get(signal.symbol)
        if layered is not None:
            row.update(_v2_fields(layered))
    return rows


def _next_day_plan(signal: Any, *, mode: str) -> dict[str, Any]:
    if mode == "preview":
        return {
            "entry_policy": "wait_tail_confirmation",
            "gap_stop_return": None,
            "intraday_stop_return": None,
            "take_profit_return": None,
            "rules": ["盘中预演不执行，必须等 14:50 后正式尾盘确认。"],
        }
    return {
        "entry_policy": "next_open_or_no_chase",
        "sell_policy": "open_or_morning_strength",
        "gap_stop_return": -0.015,
        "intraday_stop_return": -0.03,
        "take_profit_return": 0.05,
        "rules": [
            "次日优先按开盘和早盘强弱处理，不默认持有到收盘。",
            "次日低开超过 1.5% 不加仓，优先退出或放弃。",
            "持有后相对尾盘信号价回撤超过 3% 触发止损。",
            "次日冲高超过 5% 后不能继续放量维持，分批止盈。",
            "涨停或接近涨停无法买入时，不追单，保留为策略命中记录。",
        ],
    }


def _layered_rows(
    layered_signals: list[LayeredSignal],
    layer: str,
    *,
    mode: str,
) -> list[dict[str, Any]]:
    rows = []
    layered_by_symbol = {row.symbol: row for row in layered_signals}
    for layered in layered_signals:
        if layered.layer != layer:
            continue
        row = _signal_rows_with_credibility(
            [layered.signal],
            mode=mode,
            layered_by_symbol=layered_by_symbol,
        )[0]
        rows.append(row)
    return rows


def _signal_layer_counts(layered_signals: list[LayeredSignal]) -> dict[str, int]:
    counts = {"strong": 0, "watchlist": 0, "weak": 0}
    for layered in layered_signals:
        counts[layered.layer] += 1
    return counts


def _v2_fields(layered: LayeredSignal) -> dict[str, Any]:
    return {
        "v2_score": layered.total_score,
        "v2_layer": layered.layer,
        "v2_action": layered.action,
        "v2_explanation": layered.explanation,
        "v2_risks": layered.risks,
        "v2_breakdown": {
            "tail_money": layered.breakdown.tail_money,
            "price_action": layered.breakdown.price_action,
            "liquidity": layered.breakdown.liquidity,
            "risk_control": layered.breakdown.risk_control,
        },
    }


def _has_pullback_risk(layered: LayeredSignal) -> bool:
    return any("冲高回落" in risk for risk in layered.risks)


def _credibility(signal: Any, *, mode: str) -> dict[str, Any]:
    signal_strength = min(100.0, max(0.0, float(signal.strength) * 100))
    volume_quality = min(100.0, max(0.0, (float(signal.volume_ratio) / 2.5) * 100))
    return_quality = min(100.0, max(0.0, (float(signal.tail_return) / 0.03) * 100))
    phase_discount = 0.78 if mode == "preview" else 1.0
    raw_score = (signal_strength * 0.45 + volume_quality * 0.30 + return_quality * 0.25) * phase_discount
    risks = _credibility_risks(signal, mode=mode)
    score = max(0, min(100, round(raw_score - len(risks) * 4)))
    return {
        "score": score,
        "grade": _credibility_grade(score),
        "rule_score": score,
        "rule_grade": _credibility_grade(score),
        "historical_hit_rate": None,
        "historical_avg_return": None,
        "sample_size": 0,
        "calibrated_probability": None,
        "history_status": "pending",
        "phase": "盘中预演" if mode == "preview" else "正式尾盘",
        "components": {
            "signal_strength": round(signal_strength, 2),
            "volume_quality": round(volume_quality, 2),
            "return_quality": round(return_quality, 2),
            "phase_discount": phase_discount,
        },
        "confirmation_checks": _confirmation_checks(mode),
        "risks": risks,
        "history": {
            "status": "样本不足",
            "sample_count": 0,
            "note": "当前尚未建立同类盘中预演到尾盘确认的历史样本库，不能给出可靠历史胜率。",
        },
    }


def _credibility_grade(score: int) -> str:
    if score >= 75:
        return "高"
    if score >= 55:
        return "中"
    return "低"


def _confirmation_checks(mode: str) -> list[str]:
    if mode == "preview":
        return [
            "14:30 后用正式尾盘窗口复核",
            "量比继续 >= 1.5",
            "尾盘窗口涨幅保持 >= 0",
            "价格不明显跌破盘中预演窗口均价",
        ]
    return [
        "尾盘窗口量比 >= 1.5",
        "尾盘窗口涨幅 >= 0",
        "满足连续确认次数",
    ]


def _credibility_risks(signal: Any, *, mode: str) -> list[str]:
    risks = []
    if mode == "preview":
        risks.append("盘中预演尚未经过 14:30-15:00 正式尾盘确认")
    if float(signal.tail_return) > 0.03:
        risks.append("当前阶段涨幅较高，存在冲高回落风险")
    if float(signal.volume_ratio) < 1.8:
        risks.append("量比刚过候选阈值，放量优势不够厚")
    if float(signal.strength) < 0.65:
        risks.append("综合强度偏中等，需等待尾盘复核")
    return risks


_COVERAGE_SAMPLE_SIZE = 50


def _sample_symbols_for_coverage(symbols: list[str]) -> list[str]:
    """Return a representative sample of symbols for intraday coverage diagnostics.

    Uses even spacing across the universe rather than just the first N,
    so that diagnostic info reflects the whole pool instead of
    being skewed by a handful of potentially slow-to-sync symbols.
    """
    if len(symbols) <= _COVERAGE_SAMPLE_SIZE:
        return list(symbols)
    step = max(1, len(symbols) // _COVERAGE_SAMPLE_SIZE)
    return symbols[::step][:_COVERAGE_SAMPLE_SIZE]


def _intraday_coverage(aggregator: Any, symbols: list[str], trade_date: date) -> dict[str, Any]:
    """Check intraday data availability and freshness.

    Uses a direct ClickHouse query for the global max bar time (accurate and efficient),
    with a fallback to sample-based computation when ClickHouse is unavailable.
    Per-symbol diagnostic info uses a representative sample.
    """
    checked_symbols = _sample_symbols_for_coverage(symbols)
    available = []
    missing = []
    symbol_rows = []
    sample_latest_time: time | None = None
    for index, symbol in enumerate(checked_symbols, start=1):
        bars = aggregator.get_intraday_bars(symbol, trade_date, "5m")
        if bars is not None and not bars.empty:
            available.append(symbol)
            symbol_latest_time = _latest_bar_time(bars)
            if symbol_latest_time is not None and (sample_latest_time is None or symbol_latest_time > sample_latest_time):
                sample_latest_time = symbol_latest_time
            symbol_rows.append({
                "rank": index,
                "symbol": symbol,
                "has_intraday_data": True,
                "latest_time": symbol_latest_time.isoformat() if symbol_latest_time is not None else None,
            })
        else:
            missing.append(symbol)
            symbol_rows.append({
                "rank": index,
                "symbol": symbol,
                "has_intraday_data": False,
                "latest_time": None,
            })

    # Prefer ClickHouse global max time; fall back to sample-based max
    latest_time = _query_latest_intraday_time(aggregator, trade_date, "5m")
    if latest_time is None:
        latest_time = sample_latest_time

    return {
        "checked_count": len(checked_symbols),
        "available_count": len(available),
        "missing_count": len(missing),
        "available_symbols": available,
        "missing_symbols": missing,
        "latest_time": latest_time.isoformat() if latest_time is not None else None,
        "symbols": symbol_rows,
    }


def _precheck_rows(intraday_coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in intraday_coverage.get("symbols", []):
        has_data = bool(item.get("has_intraday_data"))
        latest_time = item.get("latest_time")
        if has_data:
            data_status = "has_intraday_data"
            stage = "waiting_tail_window"
            filter_reason = "tail_window_not_available"
            explanation = "分钟数据尚未覆盖 14:30-15:00，暂不能计算尾盘涨幅、尾盘量比和连续确认。"
        else:
            data_status = "missing_intraday_data"
            stage = "waiting_data"
            filter_reason = "missing_intraday_data"
            explanation = "当前没有取到分钟数据，暂不能进入尾盘评分。"
        rows.append({
            "symbol": item["symbol"],
            "rank": item["rank"],
            "data_status": data_status,
            "latest_intraday_time": latest_time,
            "stage": stage,
            "filter_reason": filter_reason,
            "explanation": explanation,
        })
    return rows


def _strategy_rules(request: TailLiveSelectionRequest) -> dict[str, Any]:
    return {
        "universe": request.universe,
        "tail_window": "14:30-15:00",
        "bar_frequency": "5m",
        "as_of_time": request.as_of_time.isoformat() if request.as_of_time else None,
        "preview_window_bars": request.preview_window_bars,
        "volume_ratio_threshold": 1.5,
        "min_tail_return": 0.0,
        "confirmations": request.confirmations,
        "top_n": request.top_n,
        "min_strength": request.min_strength,
        "min_market_breadth_above_ma20": request.min_market_breadth_above_ma20,
        "ranking": "按强度、量比、尾盘涨幅、股票代码排序",
    }


def _scan_as_of_time(request: TailLiveSelectionRequest, scheduler: TradingScheduler) -> time | None:
    if request.as_of_time is not None:
        return _completed_5m_bar_time(request.as_of_time)
    today = date.today()
    if request.trade_date == today and scheduler.is_tail_session():
        return _completed_5m_bar_time(datetime.now().time())
    return None


def _completed_5m_bar_time(value: time) -> time:
    minute = value.minute - (value.minute % 5)
    return time(value.hour, minute, 0)


def _latest_bar_time(bars: Any) -> time | None:
    if "time" in bars.columns:
        values = [_coerce_time(value) for value in bars["time"].dropna()]
    elif "datetime" in bars.columns:
        values = [_coerce_time(value) for value in bars["datetime"].dropna()]
    else:
        return None
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _coerce_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().time()
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%H:%M:%S", "%H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
    return None


def _diagnostics(
    *,
    symbols: list[str],
    intraday_coverage: dict[str, Any],
    ranked_pool: list[Any] | None,
    signal_mode: str,
    candidates: list[Any],
    confirmed: list[Any],
    selected: list[Any],
    breadth_result: Any | None,
    blocked_by_market_breadth: bool,
    requested_scan_limit: int,
    strategy_mode: str,
    scan_as_of_time: time | None,
    data_freshness: dict[str, Any] | None = None,
    quote_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason = None
    message = None
    scoreable_count = len(ranked_pool or [])
    if not symbols:
        reason = "scan_universe_empty"
        message = "没有解析到可扫描股票，请检查股票池、缓存目录或手动输入股票。"
    elif (data_freshness or {}).get("status") == "stale" and _is_stale_for_final_selection(data_freshness):
        reason = "data_stale"
        message = (
            f"当前分钟数据最新到 {(data_freshness or {}).get('latest_time') or '-'}，"
            f"低于本次运行目标 {(data_freshness or {}).get('target_time') or '-'}；"
            "本次结果降级为数据过期，不生成最终可交易选股。"
        )
    elif blocked_by_market_breadth:
        reason = "blocked_by_market_breadth"
        message = "市场宽度未达到阈值，本次按风控规则不扫描尾盘信号。"
    elif signal_mode == "preview" and scoreable_count > 0:
        reason = "intraday_preview"
        message = (
            f"当前尚未进入 14:50 后的最终确认窗口，以下结果仅为盘中预演；"
            f"{FINAL_SELECTION_START.strftime('%H:%M')} 后需要重新用正式尾盘窗口确认。"
        )
    elif (
        not candidates
        and scoreable_count == 0
        and intraday_coverage.get("latest_time") is not None
        and str(intraday_coverage.get("latest_time")) < "14:30:00"
    ):
        reason = "tail_window_not_available"
        message = (
            f"当前分钟数据最新到 {intraday_coverage['latest_time']}，尚未覆盖 14:30-15:00 "
            "尾盘窗口；请在 14:30 后重新运行。"
        )
    elif not candidates and scoreable_count == 0:
        reason = "no_scoreable_intraday_data"
        message = "扫描股票没有可评分的尾盘分钟数据；常见原因是实时分钟数据源失败、数据未覆盖 14:30-15:00，或返回字段不完整。"
    elif not candidates:
        reason = "no_intraday_candidates"
        message = "没有股票达到候选阈值；策略排序池已展示接近但未达标的股票，重点看量比和尾盘涨幅。"
    elif not confirmed:
        reason = "no_confirmed_signals"
        message = "已有候选信号，但未达到连续确认次数。"
    elif not selected:
        reason = "filtered_by_selection_rules"
        message = "已有确认信号，但被 Top N 或最小强度过滤。"

    return {
        "empty_reason": reason,
        "empty_message": message,
        "scan_universe_preview": symbols[:20],
        "has_intraday_data_count": intraday_coverage["available_count"],
        "checked_intraday_count": intraday_coverage["checked_count"],
        "missing_intraday_symbols": intraday_coverage["missing_symbols"][:20],
        "latest_intraday_time": intraday_coverage.get("latest_time"),
        "scan_as_of_time": scan_as_of_time.isoformat() if scan_as_of_time else None,
        "scoreable_count": scoreable_count,
        "unscoreable_count": max(0, len(symbols) - scoreable_count),
        "candidate_count": len(candidates),
        "confirmed_count": len(confirmed),
        "selected_count": len(selected),
        "blocked_by_market_breadth": blocked_by_market_breadth,
        "market_breadth": _market_breadth_row(breadth_result),
        "requested_scan_limit": requested_scan_limit,
        "strategy_mode": strategy_mode,
        "resolved_scan_count": len(symbols),
        "data_freshness": data_freshness or {},
        "quote_status": quote_status or {},
    }


def _data_freshness(
    intraday_coverage: dict[str, Any],
    *,
    scan_as_of_time: time | None,
) -> dict[str, Any]:
    latest = _coerce_time(intraday_coverage.get("latest_time"))
    target = scan_as_of_time
    if latest is None:
        return {
            "status": "missing",
            "latest_time": None,
            "target_time": target.isoformat() if target else None,
            "lag_minutes": None,
            "tradable": False,
        }
    if target is None:
        return {
            "status": "fresh",
            "latest_time": latest.isoformat(),
            "target_time": None,
            "lag_minutes": 0,
            "tradable": latest >= FINAL_SELECTION_START,
        }
    lag_minutes = _minutes_between(latest, target)
    return {
        "status": "fresh" if latest >= target else "stale",
        "latest_time": latest.isoformat(),
        "target_time": target.isoformat(),
        "lag_minutes": lag_minutes,
        "tradable": latest >= target and latest >= FINAL_SELECTION_START,
    }


def _is_stale_for_final_selection(data_freshness: dict[str, Any] | None) -> bool:
    if not data_freshness or data_freshness.get("status") != "stale":
        return False
    target = _coerce_time(data_freshness.get("target_time"))
    return target is not None and target >= FINAL_SELECTION_START


def _minutes_between(start: time, end: time) -> int:
    return (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)


def _elapsed(started_at: float) -> float:
    return round(max(0.0, perf_counter() - started_at), 4)


def _latest_time_before_final_selection(
    intraday_coverage: dict[str, Any],
    scan_as_of_time: time | None,
) -> bool:
    latest_time = scan_as_of_time.isoformat() if scan_as_of_time is not None else intraday_coverage.get("latest_time")
    if latest_time is None:
        return False
    return str(latest_time) < FINAL_SELECTION_START.isoformat()


def _market_breadth_row(result: Any | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "breadth": result.breadth,
        "above_count": result.above_count,
        "symbol_count": result.symbol_count,
    }


def _report_progress(
    progress: ProgressCallback | None,
    percent: int,
    stage: str,
    message: str,
) -> None:
    if progress is not None:
        progress(percent, stage, message)
