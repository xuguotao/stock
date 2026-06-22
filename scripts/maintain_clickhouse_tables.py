#!/usr/bin/env python3
"""Run ClickHouse table maintenance tasks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_table_maintenance import deduplicate_minute5_kline, minute5_duplicate_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintain ClickHouse stock tables")
    parser.add_argument("--host", default="10.211.49.42", help="ClickHouse host")
    parser.add_argument("--user", default="default", help="ClickHouse user")
    parser.add_argument("--password", default="stock123", help="ClickHouse password")
    parser.add_argument("--database", default="stock", help="ClickHouse database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("minute5-duplicates", help="Inspect minute5 duplicate keys")
    dedup = subparsers.add_parser("dedup-minute5", help="Rebuild minute5_kline without duplicate keys")
    dedup.add_argument("--execute", action="store_true", help="Actually swap the rebuilt table into place")
    dedup.add_argument("--suffix", default=None, help="Optional maintenance table suffix")

    args = parser.parse_args()
    common = {
        "host": args.host,
        "user": args.user,
        "password": args.password,
        "database": args.database,
    }
    if args.command == "minute5-duplicates":
        result = minute5_duplicate_stats(**common)
    else:
        result = deduplicate_minute5_kline(
            **common,
            dry_run=not args.execute,
            suffix=args.suffix,
        )
    print(result)


if __name__ == "__main__":
    main()
