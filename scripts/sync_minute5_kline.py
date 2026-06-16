#!/usr/bin/env python3
"""Sync local 5-minute K-line data into data/stock.db."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.minute5_sync import sync_minute5_kline


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync 5-minute A-share K-line data into stock.db")
    parser.add_argument("--db", default="data/stock.db", help="SQLite stock database path")
    parser.add_argument("--trade-date", required=True, help="Trade date, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="Max symbols to update, 0 means all")
    parser.add_argument("--symbols", nargs="*", default=None, help="Optional explicit symbols")
    parser.add_argument("--include-st", action="store_true", help="Include ST stocks")
    parser.add_argument("--verbose", action="store_true", help="Print every symbol progress update")
    args = parser.parse_args()

    last_bucket = {"value": -1}

    def report(percent: int, stage: str, message: str) -> None:
        if args.verbose or stage in {"preparing", "completed"}:
            print(f"[{percent:3d}%] {stage}: {message}", flush=True)
            return
        marker = _progress_marker(message)
        if marker is not None and marker // 100 != last_bucket["value"]:
            last_bucket["value"] = marker // 100
            print(f"[{percent:3d}%] {stage}: {message}", flush=True)

    result = sync_minute5_kline(
        db_path=args.db,
        trade_date=datetime.strptime(args.trade_date, "%Y-%m-%d").date(),
        limit=args.limit,
        symbols=args.symbols,
        include_st=args.include_st,
        progress=report,
    )
    print(
        "Done: "
        f"{result['success']} success, {result.get('no_data', 0)} no_data, "
        f"{result.get('skipped', 0)} skipped, {result['failed']} failed, "
        f"{result['inserted_rows']} rows, "
        f"{result['coverage_after']['symbol_count']} covered symbols"
    )


def _progress_marker(message: str) -> int | None:
    if "/" not in message:
        return None
    left = message.rsplit(" ", 1)[-1].split("/", 1)[0]
    return int(left) if left.isdigit() else None


if __name__ == "__main__":
    main()
