#!/usr/bin/env python
"""Sync stock.db from a remote host with integrity check and atomic replace."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.web.backend.data_sync import DEFAULT_REMOTE_STOCK_DB, sync_stock_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync remote SQLite stock database into this project")
    parser.add_argument("--remote", default=DEFAULT_REMOTE_STOCK_DB)
    parser.add_argument("--dest", default="data/stock.db")
    parser.add_argument("--backup", action="store_true", help="Keep a .bak copy of the previous destination")
    args = parser.parse_args()

    result = sync_stock_database(args.remote, args.dest, args.backup)
    print(f"Synced {result['remote']} -> {result['dest']}")


if __name__ == "__main__":
    main()
