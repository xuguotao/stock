#!/usr/bin/env python
"""Run tail session strategy backtest.

Usage:
    python scripts/run_tail_session_backtest.py
    python scripts/run_tail_session_backtest.py --start 2023-01-01 --end 2025-06-01
    python scripts/run_tail_session_backtest.py --capital 200000 --top-n 3
    python scripts/run_tail_session_backtest.py --bars-dataset data/research/daily_bars_liquid10.parquet --min-score 0.7
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import reset_settings
from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.tail_session.backtest import (
    load_bars_from_offline_cache,
    load_bars_from_research_dataset,
    load_bars_with_progress,
    make_aggregator,
    resolve_symbols,
    write_metrics_json,
    write_selection_rows_csv,
    write_selection_rows_json,
)
from src.strategy.tail_session.history import build_historical_selection_rows as build_historical_selection_rows_impl


def build_historical_selection_rows(
    bars: pd.DataFrame,
    factors: list,
    factor_weights: list[float],
    start: date,
    end: date,
    top_n: int,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    """Build daily tail-session selections from daily backtest scores.

    This is intended for historical review. It avoids historical intraday APIs
    and mirrors the backtest engine's composite-score path.
    """
    return build_historical_selection_rows_impl(
        bars=bars,
        factors=factors,
        factor_weights=factor_weights,
        start=start,
        end=end,
        top_n=top_n,
        min_score=min_score,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tail session strategy backtest"
    )
    parser.add_argument("--start", default="2023-01-01", help="Start date")
    parser.add_argument("--end", default="2025-06-01", help="End date")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--top-n", type=int, default=5, help="Number of stocks to hold")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum raw factor score required before ranking")
    parser.add_argument("--min-close-above-ma20", action="store_true", help="Require close above MA20 before tail-session scoring")
    parser.add_argument("--max-daily-return", type=float, default=None, help="Reject signals with same-day close return above this decimal threshold")
    parser.add_argument("--min-turnover-value", type=float, default=None, help="Reject signals below this traded value; falls back to close*volume when amount is missing")
    parser.add_argument("--min-market-breadth-above-ma20", type=float, default=None, help="Only score signals when this fraction of the universe is above MA20")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to test")
    parser.add_argument("--limit", type=int, default=50, help="Default stock-pool size when --symbols is omitted")
    parser.add_argument("--output-json", help="Write metrics to JSON file")
    parser.add_argument("--selection-report-json", help="Write historical daily selections to JSON")
    parser.add_argument("--selection-report-csv", help="Write historical daily selections to CSV")
    parser.add_argument("--selection-report-only", action="store_true", help="Only write historical selections; skip portfolio backtest")
    parser.add_argument("--selection-start", help="Selection report start date; defaults to --start")
    parser.add_argument("--selection-end", help="Selection report end date; defaults to --end")
    parser.add_argument("--fallback-sources", action="store_true", help="Enable fallback data sources beyond Sina")
    parser.add_argument("--offline-cache", action="store_true", help="Read local parquet bars directly and do not fetch network data")
    parser.add_argument("--bars-cache-dir", default="data/cache/bars", help="Directory for --offline-cache parquet files")
    parser.add_argument("--bars-dataset", help="Consolidated research dataset parquet file")
    args = parser.parse_args()

    reset_settings()
    agg = make_aggregator(fallback_sources=args.fallback_sources)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if args.bars_dataset:
        bars, symbols = load_bars_from_research_dataset(args.bars_dataset, args.symbols, start, end)
        print(f"Loading data from dataset {args.bars_dataset}...")
        print(f"Loaded {len(bars)} bars")
    else:
        symbols = resolve_symbols(agg, args.symbols, args.limit)
        print(f"Loading data for {len(symbols)} symbols ({start} to {end})...")
        if args.offline_cache:
            bars = load_bars_from_offline_cache(args.bars_cache_dir, symbols, start, end)
        else:
            bars = load_bars_with_progress(agg, symbols, start, end)
        print(f"Loaded {len(bars)} bars")

    if bars.empty:
        print("No data loaded. Check engine or cache.")
        return

    tail_factor = TailSessionFactor(
        breakout_window=20,
        trend_window=5,
        volume_ratio_threshold=1.2,
        min_close_above_ma20=args.min_close_above_ma20,
        max_daily_return=args.max_daily_return,
        min_turnover_value=args.min_turnover_value,
        min_market_breadth_above_ma20=args.min_market_breadth_above_ma20,
    )
    overnight_factor = OvernightMomentumFactor(smoothing_window=1)
    factors = [tail_factor, overnight_factor]
    factor_weights = [0.7, 0.3]

    if args.selection_report_json or args.selection_report_csv:
        selection_start = date.fromisoformat(args.selection_start) if args.selection_start else start
        selection_end = date.fromisoformat(args.selection_end) if args.selection_end else end
        selection_rows = build_historical_selection_rows(
            bars=bars,
            factors=factors,
            factor_weights=factor_weights,
            start=selection_start,
            end=selection_end,
            top_n=args.top_n,
            min_score=args.min_score,
        )
        print(f"Historical selections: {len(selection_rows)} rows across {len({row['date'] for row in selection_rows})} days")
        if args.selection_report_json:
            path = write_selection_rows_json(args.selection_report_json, selection_rows)
            print(f"  Selection JSON        : {path}")
        if args.selection_report_csv:
            path = write_selection_rows_csv(args.selection_report_csv, selection_rows)
            print(f"  Selection CSV         : {path}")
        if args.selection_report_only:
            return

    print(f"Running backtest with capital={args.capital}, top_n={args.top_n}, min_score={args.min_score}...")
    engine = BacktestEngine(
        bars=bars,
        factors=factors,
        factor_weights=factor_weights,
        top_n=args.top_n,
        rebalance_days=1,
        initial_capital=args.capital,
        equal_weight=True,
        min_score=args.min_score,
    )

    result = engine.run()

    print("\n" + "=" * 50)
    print("Tail Session Strategy — Backtest Results")
    print("=" * 50)
    for key, val in result.metrics.items():
        print(f"  {key:25s}: {val}")
    print(f"  Total trades           : {len(result.trades)}")
    if args.output_json:
        output_path = write_metrics_json(args.output_json, result, len(symbols))
        print(f"  Metrics JSON           : {output_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
