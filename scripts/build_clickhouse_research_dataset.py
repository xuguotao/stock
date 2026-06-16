#!/usr/bin/env python3
"""Build a standard research parquet dataset from ClickHouse daily_kline."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_research_dataset import build_clickhouse_research_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ClickHouse-backed research dataset")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument("--output", default="data/research/daily_clickhouse.parquet", help="Output parquet path")
    parser.add_argument("--manifest", default=None, help="Output manifest JSON path")
    parser.add_argument("--symbols", nargs="*", default=None, help="Optional explicit symbols")
    parser.add_argument("--limit", type=int, default=0, help="Max non-ST symbols when symbols are omitted")
    args = parser.parse_args()

    manifest = build_clickhouse_research_dataset(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        output_path=args.output,
        manifest_path=args.manifest,
        symbols=args.symbols,
        limit=args.limit,
    )
    print("=" * 50)
    print("ClickHouse Research Dataset Built")
    print("=" * 50)
    print(f"Dataset : {manifest['dataset_path']}")
    print(f"Rows    : {manifest['row_count']}")
    print(f"Symbols : {manifest['symbol_count']} / {len(manifest['requested_symbols'])}")
    print(f"Missing : {len(manifest['missing_symbols'])}")
    print("=" * 50)


if __name__ == "__main__":
    main()
