from __future__ import annotations

from datetime import date, datetime

from src.web.backend.data_status import inspect_clickhouse_database


class FakeClickHouseClient:
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "from system.tables" in normalized:
            return [
                ("stocks",),
                ("daily_kline",),
                ("minute5_kline",),
            ]
        if "left join daily_kline" in normalized or "left join minute5_kline" in normalized:
            return []
        if "countif(upper(name)" in normalized:
            return [(3, 2, 1)]
        if "from stocks" in normalized and "uniqexact(symbol)" in normalized:
            return [(3, 3)]
        if "from stocks" in normalized:
            return [(3,)]
        if "from daily_kline" in normalized:
            return [(10, date(2026, 6, 11), date(2026, 6, 15), 3)]
        if "from minute5_kline" in normalized:
            return [(48, datetime(2026, 6, 15, 9, 35), datetime(2026, 6, 15, 15, 0), 1)]
        return [(0, None, None, 0)]


class MissingSymbolClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "left join minute5_kline" in normalized:
            return [("000002", "万科A"), ("600000", "浦发银行")]
        return super().execute(query, params)


class PartiallyBrokenClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "from system.tables" in normalized:
            return [
                ("stocks",),
                ("daily_kline",),
                ("minute5_kline",),
                ("index_daily",),
            ]
        if "from index_daily" in normalized:
            raise RuntimeError("missing column")
        return super().execute(query, params)


def test_inspect_clickhouse_database_returns_coverage() -> None:
    payload = inspect_clickhouse_database(client=FakeClickHouseClient())

    assert payload["database"] == {
        "type": "clickhouse",
        "host": "10.211.49.42",
        "database": "stock",
        "exists": True,
        "size_bytes": 0,
    }
    assert payload["stock_summary"] == {
        "stock_count": 3,
        "non_st_stock_count": 2,
        "st_stock_count": 1,
    }
    assert payload["tables"]["daily_kline"]["date_range"] == {
        "start": "2026-06-11",
        "end": "2026-06-15",
    }
    assert payload["tables"]["minute5_kline"]["date_range"]["end"] == "2026-06-15 15:00:00"
    assert payload["health"] == {
        "status": "ok",
        "daily_latest_date": "2026-06-15",
        "daily_symbol_count": 3,
        "minute5_latest_datetime": "2026-06-15 15:00:00",
        "minute5_symbol_count": 1,
    }
    assert payload["quality"] == {
        "status": "warning",
        "expected_non_st_symbols": 2,
        "daily": {
            "latest_date": "2026-06-15",
            "covered_symbols": 3,
            "missing_symbols": 0,
            "coverage_ratio": 1.0,
            "status": "ok",
        },
        "minute5": {
            "latest_datetime": "2026-06-15 15:00:00",
            "covered_symbols": 1,
            "missing_symbols": 1,
            "coverage_ratio": 0.5,
            "status": "warning",
        },
        "issues": ["minute5_kline_missing_1_symbols"],
    }


def test_inspect_clickhouse_database_keeps_health_when_optional_table_fails() -> None:
    payload = inspect_clickhouse_database(client=PartiallyBrokenClickHouseClient())

    assert payload["health"]["status"] == "ok"
    assert payload["tables"]["daily_kline"]["row_count"] == 10
    assert payload["tables"]["index_daily"] == {"row_count": 0, "error": "missing column"}


def test_inspect_clickhouse_database_returns_missing_symbol_samples() -> None:
    payload = inspect_clickhouse_database(client=MissingSymbolClickHouseClient())

    assert payload["quality"]["minute5"]["missing_samples"] == [
        {"symbol": "000002.SZ", "name": "万科A"},
        {"symbol": "600000.SH", "name": "浦发银行"},
    ]
