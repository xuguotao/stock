"""Live tail-session selection API helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from config.settings import reset_settings
from src.data.aggregator import DataAggregator
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
    limit: int = Field(default=200, ge=1, le=500)
    universe: Literal["default", "liquid-cache"] = "liquid-cache"
    bars_cache_dir: str = "data/cache/bars"
    liquidity_start: date | None = None
    liquidity_end: date | None = None
    liquidity_min_bars: int = Field(default=60, ge=1)
    liquidity_min_end_date: date | None = None
    min_market_breadth_above_ma20: float | None = Field(default=None, ge=0, le=1)
    confirmations: int = Field(default=1, ge=1, le=10)
    preview_window_bars: int = Field(default=6, ge=2, le=48)
    top_n: int = Field(default=5, ge=1, le=50)
    min_strength: float | None = Field(default=None, ge=0, le=1)
    as_of_time: time | None = None
    ignore_session: bool = False
    output_dir: str = "reports/tail_session"


def run_tail_live_selection(
    request: TailLiveSelectionRequest,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run a selection-only live tail-session scan and return UI-friendly output."""
    reset_settings()
    scheduler = TradingScheduler()
    if not request.ignore_session and not scheduler.is_tail_session():
        raise ValueError("当前不在 14:30-15:00 尾盘窗口；如需盘外试跑，请打开「忽略时间窗口」。")
    if not scheduler.is_trading_day(request.trade_date):
        raise ValueError(f"{request.trade_date.isoformat()} is not a trading day.")

    _report_progress(progress, 10, "resolving_universe", "解析今日扫描股票池")
    aggregator = DataAggregator()
    liquidity_start = request.liquidity_start or request.trade_date - timedelta(days=548)
    liquidity_end = request.liquidity_end or request.trade_date
    symbols = resolve_scan_symbols(
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
    intraday_coverage = _intraday_coverage(aggregator, symbols, request.trade_date)
    scan_as_of_time = _scan_as_of_time(request, scheduler)

    _report_progress(progress, 30, "market_breadth", "计算市场宽度过滤")
    breadth_result = None
    candidates = []
    confirmed = []
    selected = []
    quotes = (
        aggregator.get_realtime_quotes(symbols)
        if request.min_market_breadth_above_ma20 is not None and symbols
        else None
    )
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
                progress=progress,
            )

    _report_progress(progress, 55, "scanning_intraday", "扫描尾盘分钟信号")
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
        progress=progress,
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
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    _report_progress(progress, 80, "writing_outputs", "写入选股结果文件")
    layered_signals = score_tail_signals(ranked_pool or [])
    layered_by_symbol = {row.symbol: row for row in layered_signals}
    mode = _result_mode_from_signal_mode(signal_mode)
    preview_signals = selected if mode == "preview" else []
    final_selected = _final_trade_candidates(
        confirmed,
        top_n=request.top_n,
        min_strength=request.min_strength,
    ) if mode == "selection" else []

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
        scan_as_of_time=scan_as_of_time,
    )
    return {
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
    }


def _result_mode_from_signal_mode(signal_mode: str) -> str:
    return "preview" if signal_mode == "preview" else "selection"


def _final_trade_candidates(
    confirmed: list[Any],
    *,
    top_n: int,
    min_strength: float | None,
) -> list[Any]:
    layered = score_tail_signals(confirmed)
    trade_candidates = [
        row.signal for row in layered
        if row.layer == "strong" and row.action == "trade_candidate"
    ]
    return select_tail_session_signals(
        trade_candidates,
        top_n=top_n,
        min_strength=min_strength,
    )


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
) -> list[dict[str, Any]]:
    ordered = select_tail_session_signals(confirmed, top_n=None, min_strength=None)
    if not ordered and ranked_pool:
        ordered = select_tail_session_signals(ranked_pool, top_n=None, min_strength=None)
    selected_symbols = {signal.symbol for signal in selected}
    preview_symbols = {signal.symbol for signal in preview or []}
    confirmed_symbols = {signal.symbol for signal in confirmed}
    rows = []
    for index, signal in enumerate(ordered, start=1):
        status = "selected" if signal.symbol in selected_symbols else "filtered"
        filter_reason = None
        layered = (layered_by_symbol or {}).get(signal.symbol)
        if mode == "preview" and signal.symbol in preview_symbols:
            status = "preview"
            filter_reason = "preview_not_final"
        elif status == "filtered":
            if signal.symbol not in confirmed_symbols:
                filter_reason = "below_candidate_threshold"
            elif min_strength is not None and signal.strength < min_strength:
                filter_reason = "below_min_strength"
            elif layered is not None and layered.action != "trade_candidate":
                filter_reason = "v2_not_trade_candidate"
            elif index > top_n:
                filter_reason = "outside_top_n"
            else:
                filter_reason = "not_selected"
        row = _signal_rows_with_credibility(
            [signal],
            mode=mode,
            layered_by_symbol=layered_by_symbol,
        )[0]
        row.update({
            "rank": index,
            "status": status,
            "filter_reason": filter_reason,
        })
        rows.append(row)
    return rows


def _signal_rows_with_credibility(
    signals: list[Any],
    *,
    mode: str,
    layered_by_symbol: dict[str, LayeredSignal] | None = None,
) -> list[dict[str, Any]]:
    rows = tail_session_selection_rows(signals)
    for row, signal in zip(rows, signals, strict=False):
        row["credibility"] = _credibility(signal, mode=mode)
        layered = (layered_by_symbol or {}).get(signal.symbol)
        if layered is not None:
            row.update(_v2_fields(layered))
    return rows


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


def _intraday_coverage(aggregator: Any, symbols: list[str], trade_date: date) -> dict[str, Any]:
    checked_symbols = symbols[:20]
    available = []
    missing = []
    symbol_rows = []
    latest_time: time | None = None
    for index, symbol in enumerate(checked_symbols, start=1):
        bars = aggregator.get_intraday_bars(symbol, trade_date, "5m")
        if bars is not None and not bars.empty:
            available.append(symbol)
            symbol_latest_time = _latest_bar_time(bars)
            if symbol_latest_time is not None and (latest_time is None or symbol_latest_time > latest_time):
                latest_time = symbol_latest_time
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
    scan_as_of_time: time | None,
) -> dict[str, Any]:
    reason = None
    message = None
    scoreable_count = len(ranked_pool or [])
    if not symbols:
        reason = "scan_universe_empty"
        message = "没有解析到可扫描股票，请检查股票池、缓存目录或手动输入股票。"
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
        "resolved_scan_count": len(symbols),
    }


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
