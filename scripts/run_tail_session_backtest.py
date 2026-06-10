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
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import reset_settings
from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.data.research_dataset import dataset_symbols, load_research_dataset
from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor


def make_aggregator(fallback_sources: bool = False) -> DataAggregator:
    """Create the data aggregator used by this script."""
    if fallback_sources:
        return DataAggregator()

    from src.data.sina_source import SinaSource
    return DataAggregator([SinaSource(rate_limit=0.2)])


def resolve_symbols(
    agg: DataAggregator,
    raw_symbols: list[str] | None,
    limit: int,
) -> list[str]:
    """Resolve CLI symbols or default stock pool."""
    if raw_symbols:
        return [format_symbol(s) for s in raw_symbols]
    return agg.get_csi300_symbols()[:limit]


def load_bars_with_progress(
    agg: DataAggregator,
    symbols: list[str],
    start: date,
    end: date,
    verbose: bool = True,
) -> pd.DataFrame:
    """Load daily bars symbol-by-symbol so long runs show progress."""
    all_dfs = []
    for i, symbol in enumerate(symbols, start=1):
        if verbose:
            print(f"  [{i:>3}/{len(symbols)}] loading {symbol}...", flush=True)
        df = agg.get_bars(symbol, start, end)
        if df is not None and not df.empty:
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    return combined.set_index(["date", "symbol"])


def load_bars_from_offline_cache(
    bars_dir: str | Path,
    symbols: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Load bars from local parquet cache files, ignoring TTL."""
    directory = Path(bars_dir)
    all_dfs = []
    start_key = int(start.strftime("%Y%m%d"))
    end_key = int(end.strftime("%Y%m%d"))

    for symbol in symbols:
        stem = symbol.replace(".", "_")
        candidates = []
        for path in directory.glob(f"{stem}_*.parquet"):
            parts = path.stem.split("_")
            if len(parts) < 4:
                continue
            file_start = int(parts[-2])
            file_end = int(parts[-1])
            if file_start <= start_key and file_end >= end_key:
                candidates.append(path)

        if not candidates:
            continue

        path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
        df = df[mask].copy()
        if not df.empty:
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    return combined.set_index(["date", "symbol"]).sort_index()


def load_bars_from_research_dataset(
    dataset_path: str | Path,
    raw_symbols: list[str] | None,
    start: date,
    end: date,
) -> tuple[pd.DataFrame, list[str]]:
    """Load bars from a consolidated research dataset."""
    symbols = [format_symbol(s) for s in raw_symbols] if raw_symbols else dataset_symbols(dataset_path)
    bars = load_research_dataset(dataset_path, symbols=symbols, start=start, end=end)
    return bars, symbols


def write_metrics_json(path: str | Path, result, symbol_count: int) -> Path:
    """Write backtest metrics to JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol_count": symbol_count,
        "trade_count": len(result.trades),
        "metrics": result.metrics,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tail session strategy backtest"
    )
    parser.add_argument("--start", default="2023-01-01", help="Start date")
    parser.add_argument("--end", default="2025-06-01", help="End date")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--top-n", type=int, default=5, help="Number of stocks to hold")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum raw factor score required before ranking")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to test")
    parser.add_argument("--limit", type=int, default=50, help="Default stock-pool size when --symbols is omitted")
    parser.add_argument("--output-json", help="Write metrics to JSON file")
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
    )
    overnight_factor = OvernightMomentumFactor(smoothing_window=1)

    print(f"Running backtest with capital={args.capital}, top_n={args.top_n}, min_score={args.min_score}...")
    engine = BacktestEngine(
        bars=bars,
        factors=[tail_factor, overnight_factor],
        factor_weights=[0.7, 0.3],
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
