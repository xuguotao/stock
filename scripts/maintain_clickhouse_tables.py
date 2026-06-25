#!/usr/bin/env python3
"""Run ClickHouse table maintenance tasks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_table_maintenance import (
    daily_duplicate_stats,
    deduplicate_daily_kline,
    deduplicate_minute5_kline,
    minute5_duplicate_stats,
)
from config.settings import get_settings


def main() -> None:
    clickhouse = get_settings().clickhouse
    parser = argparse.ArgumentParser(description="Maintain ClickHouse stock tables")
    parser.add_argument("--host", default=clickhouse.host, help="ClickHouse host")
    parser.add_argument("--user", default=clickhouse.user, help="ClickHouse user")
    parser.add_argument("--password", default=clickhouse.password, help="ClickHouse password")
    parser.add_argument("--database", default=clickhouse.database, help="ClickHouse database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("minute5-duplicates", help="Inspect minute5 duplicate keys")
    subparsers.add_parser("daily-duplicates", help="Inspect daily duplicate keys")
    dedup = subparsers.add_parser("dedup-minute5", help="Rebuild minute5_kline without duplicate keys")
    dedup.add_argument("--execute", action="store_true", help="Actually swap the rebuilt table into place")
    dedup.add_argument("--suffix", default=None, help="Optional maintenance table suffix")
    dedup_daily = subparsers.add_parser("dedup-daily", help="Rebuild daily_kline without duplicate keys")
    dedup_daily.add_argument("--execute", action="store_true", help="Actually swap the rebuilt table into place")
    dedup_daily.add_argument("--suffix", default=None, help="Optional maintenance table suffix")

    args = parser.parse_args()
    common = {
        "host": args.host,
        "user": args.user,
        "password": args.password,
        "database": args.database,
    }
    if args.command == "minute5-duplicates":
        result = minute5_duplicate_stats(**common)
    elif args.command == "daily-duplicates":
        result = daily_duplicate_stats(**common)
    elif args.command == "dedup-daily":
        result = deduplicate_daily_kline(
            **common,
            dry_run=not args.execute,
            suffix=args.suffix,
        )
    else:
        result = deduplicate_minute5_kline(
            **common,
            dry_run=not args.execute,
            suffix=args.suffix,
        )
    print(result)


if __name__ == "__main__":
    main()
