"""Live tail-session selection API helpers."""

from __future__ import annotations

from datetime import date, timedelta
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
from src.trading.scheduler import TradingScheduler


ProgressCallback = Callable[[int, str, str], None]


class TailLiveSelectionRequest(BaseModel):
    """Request body for today's tail-session selection jobs."""

    trade_date: date = Field(default_factory=date.today)
    symbols: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=500)
    universe: Literal["default", "liquid-cache"] = "liquid-cache"
    bars_cache_dir: str = "data/cache/bars"
    liquidity_start: date | None = None
    liquidity_end: date | None = None
    liquidity_min_bars: int = Field(default=120, ge=1)
    liquidity_min_end_date: date | None = None
    min_market_breadth_above_ma20: float | None = Field(default=None, ge=0, le=1)
    confirmations: int = Field(default=1, ge=1, le=10)
    top_n: int = Field(default=5, ge=1, le=50)
    min_strength: float | None = Field(default=None, ge=0, le=1)
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
                progress=progress,
            )

    _report_progress(progress, 55, "scanning_intraday", "扫描尾盘分钟信号")
    scanner = IntradayScanner(aggregator, confirmation_count=request.confirmations)
    candidates = scanner.scan(symbols, request.trade_date)
    confirmed = scanner.confirm(candidates)
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
        breadth_result=breadth_result,
        blocked_by_market_breadth=False,
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
    breadth_result: Any | None,
    blocked_by_market_breadth: bool,
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    _report_progress(progress, 80, "writing_outputs", "写入选股结果文件")
    output_dir = Path(request.output_dir)
    json_path = output_dir / "latest_selection.json"
    csv_path = output_dir / "latest_selection.csv"
    written_json = write_tail_session_selection_json(json_path, selected)
    written_csv = write_tail_session_selection_csv(csv_path, selected)
    report_path = write_tail_session_report(
        output_dir=output_dir,
        trade_date=request.trade_date,
        scanned_count=len(symbols),
        candidates=candidates,
        confirmed=confirmed,
        selected=selected,
        trades=[],
        account_summary={},
    )
    return {
        "trade_date": request.trade_date.isoformat(),
        "scanned_count": len(symbols),
        "candidate_count": len(candidates),
        "confirmed_count": len(confirmed),
        "selected_count": len(selected),
        "selections": tail_session_selection_rows(selected),
        "ranked_signals": _ranked_signal_rows(
            confirmed=confirmed,
            selected=selected,
            top_n=request.top_n,
            min_strength=request.min_strength,
        ),
        "files": {
            "json": str(written_json),
            "csv": str(written_csv),
            "report": str(report_path),
        },
        "market_breadth": _market_breadth_row(breadth_result),
        "diagnostics": _diagnostics(
            symbols=symbols,
            intraday_coverage=intraday_coverage,
            candidates=candidates,
            confirmed=confirmed,
            selected=selected,
            breadth_result=breadth_result,
            blocked_by_market_breadth=blocked_by_market_breadth,
        ),
    }


def _ranked_signal_rows(
    *,
    confirmed: list[Any],
    selected: list[Any],
    top_n: int,
    min_strength: float | None,
) -> list[dict[str, Any]]:
    ordered = select_tail_session_signals(confirmed, top_n=None, min_strength=None)
    selected_symbols = {signal.symbol for signal in selected}
    rows = []
    for index, signal in enumerate(ordered, start=1):
        status = "selected" if signal.symbol in selected_symbols else "filtered"
        filter_reason = None
        if status == "filtered":
            if min_strength is not None and signal.strength < min_strength:
                filter_reason = "below_min_strength"
            elif index > top_n:
                filter_reason = "outside_top_n"
            else:
                filter_reason = "not_selected"
        row = tail_session_selection_rows([signal])[0]
        row.update({
            "rank": index,
            "status": status,
            "filter_reason": filter_reason,
        })
        rows.append(row)
    return rows


def _intraday_coverage(aggregator: Any, symbols: list[str], trade_date: date) -> dict[str, Any]:
    checked_symbols = symbols[:20]
    available = []
    missing = []
    for symbol in checked_symbols:
        bars = aggregator.get_intraday_bars(symbol, trade_date, "5m")
        if bars is not None and not bars.empty:
            available.append(symbol)
        else:
            missing.append(symbol)
    return {
        "checked_count": len(checked_symbols),
        "available_count": len(available),
        "missing_count": len(missing),
        "available_symbols": available,
        "missing_symbols": missing,
    }


def _diagnostics(
    *,
    symbols: list[str],
    intraday_coverage: dict[str, Any],
    candidates: list[Any],
    confirmed: list[Any],
    selected: list[Any],
    breadth_result: Any | None,
    blocked_by_market_breadth: bool,
) -> dict[str, Any]:
    reason = None
    message = None
    if not symbols:
        reason = "scan_universe_empty"
        message = "没有解析到可扫描股票，请检查股票池、缓存目录或手动输入股票。"
    elif blocked_by_market_breadth:
        reason = "blocked_by_market_breadth"
        message = "市场宽度未达到阈值，本次按风控规则不扫描尾盘信号。"
    elif not candidates:
        reason = "no_intraday_candidates"
        message = "没有股票形成尾盘候选信号；常见原因是分钟数据为空、当前不在有效尾盘时段、或量价条件未达标。"
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
        "candidate_count": len(candidates),
        "confirmed_count": len(confirmed),
        "selected_count": len(selected),
        "blocked_by_market_breadth": blocked_by_market_breadth,
        "market_breadth": _market_breadth_row(breadth_result),
    }


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
