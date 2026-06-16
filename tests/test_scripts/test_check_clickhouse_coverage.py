from __future__ import annotations

from scripts.check_clickhouse_coverage import compare_coverage


class FakeClickHouseClient:
    def execute(self, query):
        if "from daily_kline" in query:
            return [(100, "2026-01-01", "2026-06-15", 10)]
        if "from minute5_kline" in query:
            return [(50, "2026-06-01 09:35:00", "2026-06-15 15:00:00", 8)]
        return [(0, None, None, 0)]


def test_compare_coverage_returns_table_rows(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "stock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table daily_kline (symbol text, date text)")
        conn.execute("create table minute5_kline (symbol text, datetime text)")
        conn.execute("insert into daily_kline values ('000001', '2026-06-12')")
        conn.execute("insert into minute5_kline values ('000001', '2026-06-12 15:00:00')")

    rows = compare_coverage(sqlite_db=db_path, clickhouse_client=FakeClickHouseClient())

    assert rows == [
        {
            "table": "daily_kline",
            "sqlite_rows": 1,
            "sqlite_start": "2026-06-12",
            "sqlite_end": "2026-06-12",
            "sqlite_symbols": 1,
            "clickhouse_rows": 100,
            "clickhouse_start": "2026-01-01",
            "clickhouse_end": "2026-06-15",
            "clickhouse_symbols": 10,
        },
        {
            "table": "minute5_kline",
            "sqlite_rows": 1,
            "sqlite_start": "2026-06-12 15:00:00",
            "sqlite_end": "2026-06-12 15:00:00",
            "sqlite_symbols": 1,
            "clickhouse_rows": 50,
            "clickhouse_start": "2026-06-01 09:35:00",
            "clickhouse_end": "2026-06-15 15:00:00",
            "clickhouse_symbols": 8,
        },
    ]
