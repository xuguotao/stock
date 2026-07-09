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
    parser.add_argument("--limit", type=int, default=0, help="Limit resolved symbols; 0 means no limit.")
    parser.add_argument("--include-beijing", action="store_true", help="Include Beijing market stock catalog when resolving symbols.")
    parser.add_argument("--bestip", action="store_true", help="Let mootdx choose best server.")
    parser.add_argument("--server", type=_server, default=None, help="Pin mootdx server as host:port.")
    parser.add_argument("--timeout", type=int, default=15, help="mootdx socket timeout seconds.")
    parser.add_argument("--no-ensure-tables", dest="ensure_tables", action="store_false", help="Skip ClickHouse DDL creation.")
    parser.set_defaults(ensure_tables=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source = MootdxSource(
        bestip=args.bestip,
        server=args.server,
        timeout=args.timeout,
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
        progress=lambda percent, stage, message: print(f"[{percent:3d}%] {stage}: {message}", file=sys.stderr),
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


if __name__ == "__main__":
    raise SystemExit(main())
