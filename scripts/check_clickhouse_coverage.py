#!/usr/bin/env python3
"""Compare SQLite and ClickHouse coverage for core market tables."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CORE_TABLES = {
    "daily_kline": {"date_col": "date", "symbol_col": "symbol"},
    "minute5_kline": {"date_col": "datetime", "symbol_col": "symbol"},
}


def compare_coverage(
    *,
    sqlite_db: str | Path = "data/stock.db",
    clickhouse_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Compare row/date/symbol coverage between SQLite and ClickHouse."""
    if clickhouse_client is None:
        from src.data.clickhouse_source import ClickHouseStockDataSource

        clickhouse_client = ClickHouseStockDataSource()._client_instance()

    rows = []
    sqlite_path = Path(sqlite_db)
    with sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True) as conn:
        for table, spec in CORE_TABLES.items():
            sqlite_status = _sqlite_status(conn, table, spec["date_col"], spec["symbol_col"])
            ch_status = _clickhouse_status(
                clickhouse_client,
                table,
                spec["date_col"],
                spec["symbol_col"],
            )
            rows.append({
                "table": table,
                "sqlite_rows": sqlite_status["rows"],
                "sqlite_start": sqlite_status["start"],
                "sqlite_end": sqlite_status["end"],
                "sqlite_symbols": sqlite_status["symbols"],
                "clickhouse_rows": ch_status["rows"],
                "clickhouse_start": ch_status["start"],
                "clickhouse_end": ch_status["end"],
                "clickhouse_symbols": ch_status["symbols"],
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-db", default="data/stock.db")
    args = parser.parse_args()

    print(json.dumps(compare_coverage(sqlite_db=args.sqlite_db), ensure_ascii=False, indent=2, default=str))


def _sqlite_status(
    conn: sqlite3.Connection,
    table: str,
    date_col: str,
    symbol_col: str,
) -> dict[str, Any]:
    row = conn.execute(
        f"select count(*), min({date_col}), max({date_col}), count(distinct {symbol_col}) from {table}"
    ).fetchone()
    return {"rows": row[0], "start": row[1], "end": row[2], "symbols": row[3]}


def _clickhouse_status(
    client: Any,
    table: str,
    date_col: str,
    symbol_col: str,
) -> dict[str, Any]:
    row = client.execute(
        f"select count(), min({date_col}), max({date_col}), count(distinct {symbol_col}) from {table}"
    )[0]
    return {
        "rows": row[0],
        "start": str(row[1]) if row[1] is not None else None,
        "end": str(row[2]) if row[2] is not None else None,
        "symbols": row[3],
    }


if __name__ == "__main__":
    main()
