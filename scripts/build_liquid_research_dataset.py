#!/usr/bin/env python
"""Build a research dataset from the most liquid cached symbols."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.research_dataset import build_research_dataset, select_liquid_symbols_from_cache


def main() -> None:
    parser = argparse.ArgumentParser(description="Build liquid-symbol research dataset from local bar cache")
    parser.add_argument("--start", required=True, help="Start date")
    parser.add_argument("--end", required=True, help="End date")
    parser.add_argument("--limit", type=int, default=30, help="Number of liquid symbols to include")
    parser.add_argument("--min-bars", type=int, default=120, help="Minimum bars required per symbol")
    parser.add_argument("--min-end-date", help="Minimum latest bar date, YYYY-MM-DD")
    parser.add_argument("--bars-cache-dir", default="data/cache/bars", help="Input per-symbol parquet cache directory")
    parser.add_argument("--output", default="data/research/daily_bars_liquid.parquet", help="Output dataset parquet path")
    parser.add_argument("--manifest", default=None, help="Output manifest JSON path")
    parser.add_argument("--ranking-output", help="Optional JSON path for liquidity ranking")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    min_end_date = date.fromisoformat(args.min_end_date) if args.min_end_date else None

    ranking = select_liquid_symbols_from_cache(
        bars_dir=args.bars_cache_dir,
        start=start,
        end=end,
        limit=args.limit,
        min_bars=args.min_bars,
        min_end_date=min_end_date,
    )
    symbols = [row["symbol"] for row in ranking]
    manifest = build_research_dataset(
        symbols=symbols,
        start=start,
        end=end,
        bars_dir=args.bars_cache_dir,
        output_path=args.output,
        manifest_path=args.manifest,
    )

    if args.ranking_output:
        ranking_path = Path(args.ranking_output)
        ranking_path.parent.mkdir(parents=True, exist_ok=True)
        ranking_path.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 50)
    print("Liquid Research Dataset Built")
    print("=" * 50)
    print(f"Dataset       : {manifest['dataset_path']}")
    print(f"Rows          : {manifest['row_count']}")
    print(f"Symbols       : {manifest['symbol_count']}")
    print(f"Missing       : {len(manifest['missing_symbols'])}")
    print("Top symbols   : " + ", ".join(symbols[:10]))
    if args.ranking_output:
        print(f"Ranking JSON  : {args.ranking_output}")
    print("=" * 50)


if __name__ == "__main__":
    main()
