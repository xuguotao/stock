#!/usr/bin/env python
"""Compute TimesFM forecast features on an offline research dataset.

Usage:
    python scripts/compute_timesfm_features.py \
      --bars-dataset data/research/daily_bars_recent_liquid30.parquet \
      --start 2025-01-01 \
      --end 2026-06-10 \
      --context-window 512 \
      --min-history 120 \
      --horizon 1 \
      --output reports/timesfm/features.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.research_dataset import load_research_dataset
from src.strategy.factors.timesfm import (
    LazyTimesFMForecaster,
    ReturnForecaster,
    TimesFMReturnForecastFactor,
)


def compute_timesfm_features(
    bars: pd.DataFrame,
    *,
    forecaster: ReturnForecaster | None = None,
    context_window: int = 512,
    min_history: int = 32,
    horizon: int = 1,
    price_col: str = "close",
) -> pd.DataFrame:
    factor = TimesFMReturnForecastFactor(
        forecaster=forecaster,
        context_window=context_window,
        min_history=min_history,
        horizon=horizon,
        price_col=price_col,
    )
    return factor.compute_features(bars)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute TimesFM return forecast features from a parquet dataset"
    )
    parser.add_argument("--bars-dataset", required=True, help="Research dataset parquet path")
    parser.add_argument("--start", required=True, help="Start date")
    parser.add_argument("--end", required=True, help="End date")
    parser.add_argument("--symbols", nargs="+", help="Optional symbols to filter")
    parser.add_argument("--context-window", type=int, default=512)
    parser.add_argument("--min-history", type=int, default=32)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--price-col", default="close")
    parser.add_argument("--per-core-batch-size", type=int, default=32)
    parser.add_argument("--output", default="reports/timesfm/features.csv")
    args = parser.parse_args()

    bars = load_research_dataset(
        args.bars_dataset,
        symbols=args.symbols,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
    if bars.empty:
        print("No bars loaded from dataset.")
        return

    forecaster = LazyTimesFMForecaster(
        max_context=args.context_window,
        max_horizon=args.horizon,
        per_core_batch_size=args.per_core_batch_size,
    )
    features = compute_timesfm_features(
        bars,
        forecaster=forecaster,
        context_window=args.context_window,
        min_history=args.min_history,
        horizon=args.horizon,
        price_col=args.price_col,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    features.dropna(how="all").to_csv(output)

    print("=" * 50)
    print("TimesFM Features")
    print("=" * 50)
    print(f"Bars loaded      : {len(bars)}")
    print(f"Feature rows     : {len(features.dropna(how='all'))}")
    print(f"Output           : {output}")
    print("=" * 50)


if __name__ == "__main__":
    main()
