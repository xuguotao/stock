#!/usr/bin/env python3
"""Sync quote, concept, announcement, and source health data into stock.db."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market_enrichment_sync import resolve_symbols_from_database, sync_market_enrichment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/stock.db", help="SQLite stock database path")
    parser.add_argument("--symbols", nargs="*", default=None, help="Explicit symbols to sync")
    parser.add_argument("--limit", type=int, default=20, help="Resolve this many symbols when --symbols is omitted")
    parser.add_argument("--include-st", action="store_true", help="Include ST stocks when resolving from DB")
    parser.add_argument("--announcement-page-size", type=int, default=5)
    args = parser.parse_args()

    symbols = args.symbols or resolve_symbols_from_database(
        args.db,
        limit=args.limit,
        include_st=args.include_st,
    )
    result = sync_market_enrichment(
        db_path=args.db,
        symbols=symbols,
        announcement_page_size=args.announcement_page_size,
    )
    print(
        "Done: "
        f"{result['symbols']} symbols, {result['quote_rows']} quotes, "
        f"{result['concept_rows']} concept rows, "
        f"{result['announcement_rows']} announcements, "
        f"{result['health_rows']} health rows"
    )


if __name__ == "__main__":
    main()
