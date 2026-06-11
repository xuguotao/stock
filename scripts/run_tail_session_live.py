#!/usr/bin/env python
"""Run one paper-trading tail-session scan.

Usage:
    python scripts/run_tail_session_live.py --symbols 000001 600519
    python scripts/run_tail_session_live.py --limit 20 --confirmations 1
    python scripts/run_tail_session_live.py --universe liquid-cache --limit 30 --selection-only --output-json reports/tail_session/latest_selection.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import reset_settings
from src.data.aggregator import DataAggregator
from src.strategy.executor import RealTimeExecutor
from src.strategy.reports import (
    select_tail_session_signals,
    write_tail_session_report,
    write_tail_session_selection_csv,
    write_tail_session_selection_json,
)
from src.strategy.scanner import IntradayScanner
from src.strategy.tail_session.live import (
    MarketBreadthResult,
    calculate_market_breadth_above_ma20,
    prices_from_quotes,
    resolve_scan_symbols,
)
from src.trading.paper_account import PaperAccount
from src.trading.risk_manager import RiskManager
from src.trading.scheduler import TradingScheduler


def _prices_from_quotes(quotes, fallback_signals) -> dict[str, float]:
    """Backward-compatible wrapper for tests and older imports."""
    return prices_from_quotes(quotes, fallback_signals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tail-session paper trading scan")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to scan")
    parser.add_argument("--limit", type=int, default=20, help="Number of default symbols to scan")
    parser.add_argument(
        "--universe",
        choices=["default", "liquid-cache"],
        default="liquid-cache",
        help="Default scan universe when --symbols is omitted",
    )
    parser.add_argument("--bars-cache-dir", default="data/cache/bars", help="Local daily bars cache for liquid-cache universe")
    parser.add_argument("--liquidity-start", default=None, help="Liquidity ranking start date; defaults to 18 months before trade date")
    parser.add_argument("--liquidity-end", default=None, help="Liquidity ranking end date; defaults to trade date")
    parser.add_argument("--liquidity-min-bars", type=int, default=120, help="Minimum daily bars required for liquid-cache universe")
    parser.add_argument("--liquidity-min-end-date", default=None, help="Minimum latest daily bar date for liquid-cache universe")
    parser.add_argument("--min-market-breadth-above-ma20", type=float, default=None, help="Skip live scan unless this fraction of scan universe is above MA20")
    parser.add_argument("--capital", type=float, default=100_000, help="Paper account initial capital")
    parser.add_argument("--confirmations", type=int, default=3, help="Consecutive confirmations required")
    parser.add_argument("--top-n", type=int, default=5, help="Maximum final selected symbols")
    parser.add_argument("--min-strength", type=float, default=None, help="Minimum signal strength for final selection")
    parser.add_argument("--selection-only", action="store_true", help="Only output selected symbols; do not paper trade")
    parser.add_argument("--output-json", help="Write final selections to JSON")
    parser.add_argument("--output-csv", help="Write final selections to CSV")
    parser.add_argument("--trade-date", default=None, help="Trade date, YYYY-MM-DD. Defaults to today")
    parser.add_argument("--ignore-session", action="store_true", help="Run even outside 14:30-15:00")
    parser.add_argument("--report-dir", default="reports/tail_session", help="Directory for Markdown daily reports")
    args = parser.parse_args()

    reset_settings()
    trade_date = date.fromisoformat(args.trade_date) if args.trade_date else date.today()

    scheduler = TradingScheduler()
    if not args.ignore_session and not scheduler.is_tail_session():
        print("Not in tail session. Use --ignore-session for a manual dry run.")
        return
    if not scheduler.is_trading_day(trade_date):
        print(f"{trade_date} is not a trading day.")
        return

    aggregator = DataAggregator()
    liquidity_start = (
        date.fromisoformat(args.liquidity_start)
        if args.liquidity_start
        else trade_date - timedelta(days=548)
    )
    liquidity_end = date.fromisoformat(args.liquidity_end) if args.liquidity_end else trade_date
    liquidity_min_end_date = date.fromisoformat(args.liquidity_min_end_date) if args.liquidity_min_end_date else None
    symbols = resolve_scan_symbols(
        aggregator=aggregator,
        raw_symbols=args.symbols,
        limit=args.limit,
        universe=args.universe,
        bars_cache_dir=args.bars_cache_dir,
        liquidity_start=liquidity_start,
        liquidity_end=liquidity_end,
        liquidity_min_bars=args.liquidity_min_bars,
        liquidity_min_end_date=liquidity_min_end_date,
    )

    breadth = None
    universe_quotes = (
        aggregator.get_realtime_quotes(symbols)
        if args.min_market_breadth_above_ma20 is not None and symbols
        else None
    )
    if args.min_market_breadth_above_ma20 is not None:
        breadth = calculate_market_breadth_above_ma20(
            symbols=symbols,
            bars_cache_dir=args.bars_cache_dir,
            trade_date=trade_date,
            quotes=universe_quotes,
        )
        if breadth.breadth < args.min_market_breadth_above_ma20:
            candidates = []
            confirmed = []
            selected = []
        else:
            scanner = IntradayScanner(aggregator, confirmation_count=args.confirmations)
            candidates = scanner.scan(symbols, trade_date)
            confirmed = scanner.confirm(candidates)
            selected = select_tail_session_signals(
                confirmed,
                top_n=args.top_n,
                min_strength=args.min_strength,
            )
    else:
        scanner = IntradayScanner(aggregator, confirmation_count=args.confirmations)
        candidates = scanner.scan(symbols, trade_date)
        confirmed = scanner.confirm(candidates)
        selected = select_tail_session_signals(
            confirmed,
            top_n=args.top_n,
            min_strength=args.min_strength,
        )

    quotes = aggregator.get_realtime_quotes([signal.symbol for signal in selected]) if selected else None
    prices = _prices_from_quotes(quotes, selected)

    account_path = None
    trades = []
    if args.selection_only:
        account_summary = {}
    else:
        account = PaperAccount(initial_capital=args.capital)
        executor = RealTimeExecutor(account=account, risk_manager=RiskManager())
        trades = executor.execute_buy_signals(selected, prices, trade_date)
        account_path = account.save()
        account_summary = account.summary()

    json_path = write_tail_session_selection_json(args.output_json, selected) if args.output_json else None
    csv_path = write_tail_session_selection_csv(args.output_csv, selected) if args.output_csv else None
    report_path = write_tail_session_report(
        output_dir=args.report_dir,
        trade_date=trade_date,
        scanned_count=len(symbols),
        candidates=candidates,
        confirmed=confirmed,
        selected=selected,
        trades=trades,
        account_summary=account_summary,
    )

    print("=" * 50)
    print("Tail Session Paper Scan")
    print("=" * 50)
    print(f"Trade date     : {trade_date}")
    print(f"Scanned symbols: {len(symbols)}")
    if breadth is not None:
        print(f"Market breadth : {breadth.breadth:.2%} ({breadth.above_count}/{breadth.symbol_count} above MA20)")
    print(f"Candidates     : {len(candidates)}")
    print(f"Confirmed      : {len(confirmed)}")
    print(f"Selected       : {len(selected)}")
    for signal in selected:
        print(f"  SELECT {signal.symbol} strength={signal.strength:.3f} price={signal.last_price:.2f}")
    print(f"Trades         : {len(trades)}")
    for trade in trades:
        print(f"  {trade.side.upper()} {trade.symbol} {trade.quantity} @ {trade.price:.2f}")
    if account_path is not None:
        print(f"Account saved  : {account_path}")
    if json_path is not None:
        print(f"Selection JSON : {json_path}")
    if csv_path is not None:
        print(f"Selection CSV  : {csv_path}")
    print(f"Report saved   : {report_path}")


if __name__ == "__main__":
    main()
