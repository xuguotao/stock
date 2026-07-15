#!/usr/bin/env python
"""Run isolated mootdx offline sync into ClickHouse."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.mootdx_clickhouse_sync import DEFAULT_TASKS, sync_mootdx_offline_data  # noqa: E402
from src.data.mootdx_source import MootdxSource  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync mootdx data into isolated ClickHouse mootdx_* tables.")
    parser.add_argument("--symbols", type=_csv_list, default=None, help="Comma-separated symbols, e.g. 000001.SZ,600519.SH.")
    parser.add_argument("--trade-date", type=date.fromisoformat, default=date.today(), help="Trade date in YYYY-MM-DD.")
    parser.add_argument("--tasks", type=_csv_list, default=list(DEFAULT_TASKS), help="Comma-separated offline task names.")
    parser.add_argument("--frequencies", type=_csv_list, default=["5m"], help="Comma-separated kline frequencies.")
    parser.add_argument("--daily-mode", choices=["incremental", "backfill"], default="incremental", help="Daily kline sync mode.")
    parser.add_argument("--daily-offset", type=int, default=800, help="mootdx daily bars offset for backfill mode.")
    parser.add_argument("--start-date", type=date.fromisoformat, default=None, help="Start date for daily backfill in YYYY-MM-DD.")
    parser.add_argument("--end-date", type=date.fromisoformat, default=None, help="End date for daily backfill in YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=0, help="Limit resolved symbols; 0 means no limit.")
    parser.add_argument("--include-beijing", action="store_true", help="Include Beijing market stock catalog when resolving symbols.")
    parser.add_argument("--bestip", action="store_true", help="Let mootdx choose best server.")
    parser.add_argument("--server", type=_server, default=None, help="Pin mootdx server as host:port.")
    parser.add_argument("--timeout", type=int, default=15, help="mootdx socket timeout seconds.")
    parser.add_argument("--rate-limit", type=float, default=0.02, help="Minimum spacing between mootdx requests in seconds.")
    parser.add_argument("--recheck-no-data", action="store_true", help="Include symbols previously marked as no_data for this data kind.")
    parser.add_argument("--daily-reconcile", action="store_true", help="Only request symbols missing the selected daily kline trade date.")
    parser.add_argument("--no-ensure-tables", dest="ensure_tables", action="store_false", help="Skip ClickHouse DDL creation.")
    parser.set_defaults(ensure_tables=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source = MootdxSource(
        bestip=args.bestip,
        server=args.server,
        timeout=args.timeout,
        rate_limit=args.rate_limit,
        include_beijing=args.include_beijing,
    )
    result = sync_mootdx_offline_data(
        source=source,
        symbols=args.symbols,
        trade_date=args.trade_date,
        frequencies=args.frequencies,
        tasks=args.tasks,
        include_beijing=args.include_beijing,
        limit=args.limit,
        ensure_tables=args.ensure_tables,
        recheck_no_data=args.recheck_no_data,
        daily_mode=args.daily_mode,
        daily_offset=args.daily_offset,
        start_date=args.start_date,
        end_date=args.end_date,
        daily_reconcile=args.daily_reconcile,
        progress=_print_progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("failed") else 0


def _csv_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _server(value: str) -> tuple[str, int]:
    host, sep, port = value.partition(":")
    if not sep or not host or not port.isdigit():
        raise argparse.ArgumentTypeError("server must be host:port")
    return host, int(port)


def _print_progress(percent: int, stage: str, message: str, **extra: object) -> None:
    processed = extra.get("processed")
    total = extra.get("total")
    suffix = f" ({processed} / {total})" if processed is not None and total is not None else ""
    print(f"[{percent:3d}%] {stage}: {message}{suffix}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
