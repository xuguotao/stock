#!/usr/bin/env python
"""Build an offline parquet research dataset from local bar cache.

Usage:
    python scripts/build_research_dataset.py --symbols 000001 600519 300750
    python scripts/build_research_dataset.py --limit 50 --start 2024-01-01 --end 2025-06-01
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
from src.data.research_dataset import build_research_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline research dataset")
    parser.add_argument("--start", default="2024-01-01", help="Start date")
    parser.add_argument("--end", default="2025-06-01", help="End date")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to include")
    parser.add_argument("--limit", type=int, default=50, help="Default stock-pool size when --symbols is omitted")
    parser.add_argument("--bars-cache-dir", default="data/cache/bars", help="Input per-symbol parquet cache directory")
    parser.add_argument("--output", default="data/research/daily_bars.parquet", help="Output dataset parquet path")
    parser.add_argument("--manifest", default=None, help="Output manifest JSON path")
    args = parser.parse_args()

    reset_settings()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if args.symbols:
        symbols = [format_symbol(symbol) for symbol in args.symbols]
    else:
        symbols = DataAggregator().get_csi300_symbols()[:args.limit]

    manifest = build_research_dataset(
        symbols=symbols,
        start=start,
        end=end,
        bars_dir=args.bars_cache_dir,
        output_path=args.output,
        manifest_path=args.manifest,
    )

    print("=" * 50)
    print("Research Dataset Built")
    print("=" * 50)
    print(f"Dataset       : {manifest['dataset_path']}")
    print(f"Rows          : {manifest['row_count']}")
    print(f"Symbols       : {manifest['symbol_count']}")
    print(f"Missing       : {len(manifest['missing_symbols'])}")
    if manifest["missing_symbols"]:
        print(f"Missing list  : {', '.join(manifest['missing_symbols'])}")
    print("=" * 50)


if __name__ == "__main__":
    main()
