#!/usr/bin/env python
"""Run one paper-trading tail-session scan.

Usage:
    python scripts/run_tail_session_live.py --symbols 000001 600519
    python scripts/run_tail_session_live.py --limit 20 --confirmations 1
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import reset_settings
from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.strategy.executor import RealTimeExecutor
from src.strategy.reports import write_tail_session_report
from src.strategy.scanner import IntradayScanner
from src.trading.paper_account import PaperAccount
from src.trading.risk_manager import RiskManager
from src.trading.scheduler import TradingScheduler


def _prices_from_quotes(quotes, fallback_signals) -> dict[str, float]:
    prices: dict[str, float] = {}
    if quotes is not None and not quotes.empty and "symbol" in quotes.columns:
        price_col = "price" if "price" in quotes.columns else "close"
        if price_col in quotes.columns:
            prices.update({
                row["symbol"]: float(row[price_col])
                for _, row in quotes.iterrows()
                if float(row[price_col]) > 0
            })

    for signal in fallback_signals:
        prices.setdefault(signal.symbol, signal.last_price)
    return prices


def main() -> None:
    parser = argparse.ArgumentParser(description="Tail-session paper trading scan")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to scan")
    parser.add_argument("--limit", type=int, default=20, help="Number of default symbols to scan")
    parser.add_argument("--capital", type=float, default=100_000, help="Paper account initial capital")
    parser.add_argument("--confirmations", type=int, default=3, help="Consecutive confirmations required")
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
    if args.symbols:
        symbols = [format_symbol(symbol) for symbol in args.symbols]
    else:
        symbols = aggregator.get_csi300_symbols()[:args.limit]

    scanner = IntradayScanner(aggregator, confirmation_count=args.confirmations)
    candidates = scanner.scan(symbols, trade_date)
    confirmed = scanner.confirm(candidates)

    quotes = aggregator.get_realtime_quotes([signal.symbol for signal in confirmed]) if confirmed else None
    prices = _prices_from_quotes(quotes, confirmed)

    account = PaperAccount(initial_capital=args.capital)
    executor = RealTimeExecutor(account=account, risk_manager=RiskManager())
    trades = executor.execute_buy_signals(confirmed, prices, trade_date)
    account_path = account.save()
    report_path = write_tail_session_report(
        output_dir=args.report_dir,
        trade_date=trade_date,
        scanned_count=len(symbols),
        candidates=candidates,
        confirmed=confirmed,
        trades=trades,
        account_summary=account.summary(),
    )

    print("=" * 50)
    print("Tail Session Paper Scan")
    print("=" * 50)
    print(f"Trade date     : {trade_date}")
    print(f"Scanned symbols: {len(symbols)}")
    print(f"Candidates     : {len(candidates)}")
    print(f"Confirmed      : {len(confirmed)}")
    print(f"Trades         : {len(trades)}")
    for trade in trades:
        print(f"  {trade.side.upper()} {trade.symbol} {trade.quantity} @ {trade.price:.2f}")
    print(f"Account saved  : {account_path}")
    print(f"Report saved   : {report_path}")


if __name__ == "__main__":
    main()
