#!/usr/bin/env python3
"""Compute next-session outcomes for tail-session signals."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.tail_signal_repository import ClickHouseTailSignalRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify tail-session signal outcomes from ClickHouse daily bars")
    parser.add_argument("--signal-date", required=True, help="Signal date, YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", default=None, help="Optional symbols. Defaults to selected signals from ClickHouse.")
    args = parser.parse_args()

    repo = ClickHouseTailSignalRepository()
    signal_date = date.fromisoformat(args.signal_date)
    symbols = args.symbols or _selected_symbols(repo, signal_date)
    result = repo.compute_and_save_outcomes(signal_date=signal_date, symbols=symbols)
    print(result)


def _selected_symbols(repo: ClickHouseTailSignalRepository, signal_date: date) -> list[str]:
    rows = repo.client.execute(
        """
        select distinct symbol
        from tail_selection_signals
        where trade_date = %(trade_date)s and status = 'selected'
        order by symbol
        """,
        {"trade_date": signal_date},
    )
    return [str(row[0]).zfill(6) for row in rows]


if __name__ == "__main__":
    main()
