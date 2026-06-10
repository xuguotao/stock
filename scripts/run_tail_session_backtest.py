#!/usr/bin/env python
"""Run tail session strategy backtest.

Usage:
    python scripts/run_tail_session_backtest.py
    python scripts/run_tail_session_backtest.py --start 2023-01-01 --end 2025-06-01
    python scripts/run_tail_session_backtest.py --capital 200000 --top-n 3
"""

from __future__ import annotations

import argparse
from datetime import date

from config.settings import reset_settings
from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tail session strategy backtest"
    )
    parser.add_argument("--start", default="2023-01-01", help="Start date")
    parser.add_argument("--end", default="2025-06-01", help="End date")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--top-n", type=int, default=5, help="Number of stocks to hold")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to test")
    args = parser.parse_args()

    reset_settings()
    agg = DataAggregator()

    if args.symbols:
        symbols = [format_symbol(s) for s in args.symbols]
    else:
        symbols = agg.get_csi300_symbols()[:50]

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"Loading data for {len(symbols)} symbols ({start} to {end})...")
    bars = agg.get_bars_batch(symbols, start, end)
    print(f"Loaded {len(bars)} bars")

    if bars.empty:
        print("No data loaded. Check engine or cache.")
        return

    tail_factor = TailSessionFactor(
        breakout_window=20,
        trend_window=5,
        volume_ratio_threshold=1.2,
    )
    overnight_factor = OvernightMomentumFactor(smoothing_window=1)

    print(f"Running backtest with capital={args.capital}, top_n={args.top_n}...")
    engine = BacktestEngine(
        bars=bars,
        factors=[tail_factor, overnight_factor],
        factor_weights=[0.7, 0.3],
        top_n=args.top_n,
        rebalance_days=1,
        initial_capital=args.capital,
        equal_weight=True,
    )

    result = engine.run()

    print("\n" + "=" * 50)
    print("Tail Session Strategy — Backtest Results")
    print("=" * 50)
    for key, val in result.metrics.items():
        print(f"  {key:25s}: {val}")
    print(f"  Total trades           : {len(result.trades)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
