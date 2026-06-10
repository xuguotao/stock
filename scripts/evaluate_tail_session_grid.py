#!/usr/bin/env python
"""Evaluate tail-session strategy parameter grids on an offline dataset.

Usage:
    python scripts/evaluate_tail_session_grid.py \
      --bars-dataset data/research/daily_bars_liquid10.parquet \
      --start 2024-01-01 --end 2025-06-01 \
      --breakout-windows 10 20 \
      --trend-windows 3 5 \
      --volume-thresholds 1.0 1.2 \
      --top-n 3 5 \
      --output reports/tail_session/grid_liquid10.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.research_dataset import load_research_dataset
from src.research.tail_session_analysis import evaluate_tail_session_grid, expand_grid


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate tail-session parameter grid")
    parser.add_argument("--bars-dataset", required=True, help="Research dataset parquet path")
    parser.add_argument("--start", required=True, help="Start date")
    parser.add_argument("--end", required=True, help="End date")
    parser.add_argument("--symbols", nargs="+", help="Optional symbols to filter")
    parser.add_argument("--breakout-windows", type=int, nargs="+", default=[10, 20])
    parser.add_argument("--trend-windows", type=int, nargs="+", default=[3, 5])
    parser.add_argument("--volume-thresholds", type=float, nargs="+", default=[1.0, 1.2])
    parser.add_argument("--top-n", type=int, nargs="+", default=[3, 5])
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--output", default="reports/tail_session/grid_results.csv")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars = load_research_dataset(args.bars_dataset, symbols=args.symbols, start=start, end=end)
    if bars.empty:
        print("No bars loaded from dataset.")
        return

    configs = expand_grid({
        "breakout_window": args.breakout_windows,
        "trend_window": args.trend_windows,
        "volume_ratio_threshold": args.volume_thresholds,
        "top_n": args.top_n,
    })
    print(f"Loaded {len(bars)} bars; evaluating {len(configs)} configs...")

    results = evaluate_tail_session_grid(
        bars=bars,
        configs=configs,
        initial_capital=args.capital,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results.sort_values(["sharpe_ratio", "total_return"], ascending=False).to_csv(output, index=False)

    print("=" * 50)
    print("Tail Session Grid Results")
    print("=" * 50)
    print(f"Output: {output}")
    if not results.empty:
        best = results.sort_values(["sharpe_ratio", "total_return"], ascending=False).iloc[0]
        print(f"Best config_id : {int(best['config_id'])}")
        print(f"Sharpe         : {best['sharpe_ratio']}")
        print(f"Total return   : {best['total_return']}")
        print(f"Win rate       : {best['win_rate']}")
        print(f"Trades         : {int(best['trade_count'])}")
    print("=" * 50)


if __name__ == "__main__":
    main()
