from __future__ import annotations

from datetime import date, datetime

from src.web.backend.data_status import inspect_clickhouse_database, persist_clickhouse_quality_snapshot


class FakeClickHouseClient:
    def __init__(self):
        self.commands: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from system.tables" in normalized:
            return [
                ("stocks",),
                ("daily_kline",),
                ("minute5_kline",),
                ("stock_quote_snapshots",),
                ("stock_quote_snapshots_1m",),
                ("stock_quote_snapshots_5m",),
                ("fund_tail_nav",),
                ("fund_tail_proxy",),
                ("fund_tail_benchmark",),
            ]
        if "from stock_quote_snapshots" in normalized and "group by snapshot_at" in normalized:
            if "snapshot_at >= now() - interval 5 minute" in normalized:
                return [
                    (datetime(2026, 6, 17, 10, 51, 29), 2),
                    (datetime(2026, 6, 17, 10, 51, 19), 2),
                    (datetime(2026, 6, 17, 10, 51, 9), 2),
                ]
            if "snapshot_at >= now() - interval 30 minute" in normalized:
                return [
                    (datetime(2026, 6, 17, 10, 51, 29), 2),
                    (datetime(2026, 6, 17, 10, 51, 19), 2),
                    (datetime(2026, 6, 17, 10, 51, 9), 2),
                ]
            return [
                (datetime(2026, 6, 17, 10, 51, 29), 2),
                (datetime(2026, 6, 17, 10, 51, 19), 2),
                (datetime(2026, 6, 17, 10, 51, 9), 2),
            ]
        if "from stock_quote_snapshots_1m" in normalized and "where bucket_start" in normalized:
            return [(2,)]
        if "from stock_quote_snapshots_5m" in normalized and "where bucket_start" in normalized:
            return [(2,)]
        if "from stock_quote_snapshots" in normalized and "where snapshot_at" in normalized:
            return [(2,)]
        if "from stock_quote_snapshots_1m" in normalized:
            return [(24, datetime(2026, 6, 17, 10, 41), datetime(2026, 6, 17, 10, 51), 2)]
        if "from stock_quote_snapshots_5m" in normalized:
            return [(8, datetime(2026, 6, 17, 10, 40), datetime(2026, 6, 17, 10, 50), 2)]
        if "count() as affected_symbols" in normalized and "daily_days <" in normalized:
            return [(1,)]
        if "daily_days <" in normalized and "select s.symbol" in normalized:
            return [("000002", "万科A", 12)]
        if "count() as bad_rows" in normalized and "daily_kline" in normalized and "volume <= 0" in normalized:
            return [(2,)]
        if "from daily_kline k" in normalized and "volume <= 0" in normalized:
            return [
                ("000001", date(2026, 6, 15), 10.0, 10.2, 9.9, 10.1, 0.0),
                ("600000", date(2026, 6, 15), 0.0, 10.2, 9.9, 10.1, 100.0),
            ]
        if "select uniqexact(k.symbol)" in normalized and "from daily_kline" in normalized:
            return [(3,)]
        if "select uniqexact(k.symbol)" in normalized and "from minute5_kline" in normalized:
            return [(1,)]
        if "select count() from stocks s inner join daily_kline d" in normalized and "d.volume >= 1" in normalized:
            return [(2,)]
        if "having count() > 1" in normalized and "from minute5_kline" in normalized:
            return [(2, 3)]
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
        if "from stock_quote_snapshots" in normalized:
            return [(12, datetime(2026, 6, 17, 10, 41, 21), datetime(2026, 6, 17, 10, 51, 29), 2)]
        if "from fund_tail_nav" in normalized:
            return [(100, date(2025, 1, 1), date(2026, 6, 17), 16)]
        if "from fund_tail_proxy" in normalized:
            return [(80, date(2025, 1, 1), date(2026, 6, 22), 16)]
        if "from fund_tail_benchmark" in normalized:
            return [(50, date(2025, 1, 1), date(2026, 6, 22))]
        return [(0, None, None, 0)]


class MissingSymbolClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "select count() from stocks s inner join daily_kline d" in normalized and "d.volume >= 1" in normalized:
            return [(2,)]
        if "left join minute5_kline" in normalized and "select s.symbol, s.name" in normalized:
            return [("000002", "万科A"), ("600000", "浦发银行")]
        return super().execute(query, params)


class SuspendedSymbolClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "select uniqexact(k.symbol)" in normalized and "from minute5_kline" in normalized:
            return [(1,)]
        if "select count() from stocks s inner join daily_kline d" in normalized and "d.volume >= 1" in normalized:
            return [(1,)]
        if "left join minute5_kline" in normalized and "inner join daily_kline d" in normalized:
            return []
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
    payload = inspect_clickhouse_database(client=FakeClickHouseClient(), as_of=date(2026, 6, 17))

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
    assert payload["tables"]["stock_quote_snapshots"]["date_range"] == {
        "start": "2026-06-17 10:41:21",
        "end": "2026-06-17 10:51:29",
    }
    assert payload["health"] == {
        "status": "ok",
        "daily_latest_date": "2026-06-15",
        "daily_symbol_count": 3,
        "minute1_latest_datetime": None,
        "minute1_symbol_count": 0,
        "minute5_latest_datetime": "2026-06-15 15:00:00",
        "minute5_symbol_count": 1,
        "quote_snapshot_latest_datetime": "2026-06-17 10:51:29",
        "quote_snapshot_symbol_count": 2,
    }
    datasets = {row["key"]: row for row in payload["datasets_health"]}
    assert datasets["daily_kline"]["name"] == "股票日线"
    assert datasets["daily_kline"]["update_mechanism"] == "日常维护补齐；当分钟线先到位时可由 5m 聚合修复最新交易日。"
    assert datasets["daily_kline"]["consumer"] == "尾盘选股、个股趋势、策略复盘、回测、因子计算"
    assert datasets["daily_kline"]["coverage_ratio"] == 1.0
    assert datasets["minute5_kline"]["status"] == "warning"
    assert datasets["stock_quote_snapshots_5m"]["consumer"] == "尾盘选股 5m 兜底、个股趋势、盘中验证"
    assert datasets["fund_tail_nav"]["status"] == "ok"
    assert datasets["fund_tail_nav"]["rows"] == 100
    assert datasets["fund_tail_nav"]["symbols"] == 16
    assert datasets["fund_tail_nav"]["latest"] == "2026-06-17"
    assert datasets["fund_tail_proxy"]["status"] == "ok"
    assert datasets["fund_tail_benchmark"]["status"] == "ok"
    assert datasets["data_source_health"]["category"] == "运维数据"
    assert payload["quality"] == {
        "status": "warning",
        "expected_non_st_symbols": 2,
        "daily": {
            "latest_date": "2026-06-15",
            "covered_symbols": 3,
            "missing_symbols": 0,
            "coverage_ratio": 1.0,
            "status": "ok",
            "expected_symbols": 1,
        },
            "minute5": {
                "latest_datetime": "2026-06-15 15:00:00",
                "covered_symbols": 1,
                "missing_symbols": 1,
                "coverage_ratio": 0.5,
                "expected_symbols": 2,
                "current_latest_datetime": "2026-06-15 15:00:00",
                "current_covered_symbols": 1,
                "current_coverage_ratio": 0.5,
                "duplicate_groups": 2,
                "extra_rows": 3,
                "status": "warning",
        },
            "quote_snapshots": {
            "status": "ok",
            "expected_symbols": 2,
            "expected_interval_seconds": 10,
            "raw_retention_days": 120,
            "aggregate_retention_days": 1095,
            "raw": {
                "table": "stock_quote_snapshots",
                "latest_datetime": "2026-06-17 10:51:29",
                "row_count": 12,
                "symbol_count": 2,
                "latest_symbol_count": 2,
                "missing_symbols": 0,
                "coverage_ratio": 1.0,
                "retention_days": 120,
                "expected_interval_seconds": 10,
                "observed_rounds": 3,
                "expected_rounds": 3,
                "missing_rounds": 0,
                "missing_rate": 0.0,
                "actual_avg_interval_seconds": 10.0,
                "recent_windows": {
                    "5m": {
                        "observed_rounds": 3,
                        "expected_rounds": 3,
                        "missing_rounds": 0,
                        "missing_rate": 0.0,
                        "actual_avg_interval_seconds": 10.0,
                    },
                    "30m": {
                        "observed_rounds": 3,
                        "expected_rounds": 3,
                        "missing_rounds": 0,
                        "missing_rate": 0.0,
                        "actual_avg_interval_seconds": 10.0,
                    },
                },
                "status": "ok",
            },
            "rollups": {
                "1m": {
                    "table": "stock_quote_snapshots_1m",
                    "latest_bucket": "2026-06-17 10:51:00",
                    "row_count": 24,
                    "symbol_count": 2,
                    "latest_symbol_count": 2,
                    "missing_symbols": 0,
                    "coverage_ratio": 1.0,
                    "retention_days": 1095,
                    "bucket_seconds": 60,
                    "status": "ok",
                },
                "5m": {
                    "table": "stock_quote_snapshots_5m",
                    "latest_bucket": "2026-06-17 10:50:00",
                    "row_count": 8,
                    "symbol_count": 2,
                    "latest_symbol_count": 2,
                    "missing_symbols": 0,
                    "coverage_ratio": 1.0,
                    "retention_days": 1095,
                    "bucket_seconds": 300,
                    "status": "ok",
                },
            },
            "issues": [],
        },
        "scheduled_checks": {
            "status": "warning",
            "completeness_30d": {
                "status": "warning",
                "window_days": 30,
                "min_required_days": 15,
                "affected_symbols": 1,
                "samples": [{"symbol": "000002.SZ", "name": "万科A", "data_days": 12}],
            },
            "today_anomalies": {
                "status": "warning",
                "latest_date": "2026-06-15",
                "bad_rows": 2,
                "samples": [
                    {
                        "symbol": "000001.SZ",
                        "date": "2026-06-15",
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "volume": 0.0,
                    },
                    {
                        "symbol": "600000.SH",
                        "date": "2026-06-15",
                        "open": 0.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "volume": 100.0,
                    },
                ],
            },
            "freshness": {
                "status": "ok",
                    "latest_date": "2026-06-15",
                    "as_of_date": "2026-06-17",
                    "lag_days": 2,
                    "expected_latest_date": "2026-06-17",
                    "trading_lag_days": 0,
                    "max_lag_days": 3,
                },
            "issues": [
                "daily_kline_30d_incomplete_1_symbols",
                "daily_kline_today_anomalies_2_rows",
            ],
        },
        "issues": [
            "minute5_kline_missing_1_symbols",
            "minute5_kline_duplicate_3_extra_rows",
            "daily_kline_30d_incomplete_1_symbols",
            "daily_kline_today_anomalies_2_rows",
        ],
    }


def test_persist_clickhouse_quality_snapshot_writes_health_rows() -> None:
    client = FakeClickHouseClient()
    payload = inspect_clickhouse_database(client=client, as_of=date(2026, 6, 17))

    result = persist_clickhouse_quality_snapshot(client=client, quality=payload["quality"], checked_at=datetime(2026, 6, 17, 16, 0))

    executed = [" ".join(query.lower().split()) for query, _ in client.commands]
    inserts = [params for query, params in client.commands if "insert into data_source_health" in " ".join(query.lower().split())]
    assert result["rows"] >= 4
    assert any("create table if not exists data_source_health" in query for query in executed)
    assert inserts
    row_names = {row[1] for row in inserts[0]}
    assert {"daily", "minute5", "quote_snapshots", "scheduled_completeness_30d", "scheduled_freshness"} <= row_names


class StaleDailyClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if normalized.startswith("select count(), min(date), max(date), uniqexact(symbol) from daily_kline"):
            return [(10, date(2026, 6, 10), date(2026, 6, 10), 3)]
        if "from trade_calendar" in normalized:
            raise RuntimeError("trade calendar unavailable")
        return super().execute(query, params)


def test_inspect_clickhouse_database_warns_when_daily_data_is_stale() -> None:
    payload = inspect_clickhouse_database(client=StaleDailyClickHouseClient(), as_of=date(2026, 6, 17))

    freshness = payload["quality"]["scheduled_checks"]["freshness"]
    assert freshness["status"] == "warning"
    assert freshness["latest_date"] == "2026-06-10"
    assert freshness["lag_days"] == 7
    assert "daily_kline_stale_7_days" in payload["quality"]["issues"]


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


def test_inspect_clickhouse_database_excludes_no_trade_symbols_from_minute5_missing() -> None:
    payload = inspect_clickhouse_database(client=SuspendedSymbolClickHouseClient())

    assert payload["quality"]["minute5"]["covered_symbols"] == 1
    assert payload["quality"]["minute5"]["expected_symbols"] == 1
    assert payload["quality"]["minute5"]["missing_symbols"] == 0
    assert "missing_samples" not in payload["quality"]["minute5"]


class PartialLatestMinute5ClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "select k.datetime, uniqexact(k.symbol)" in normalized and "from minute5_kline k" in normalized:
            return [(datetime(2026, 6, 22, 13, 35), 2)]
        if "select uniqexact(k.symbol)" in normalized and "from minute5_kline" in normalized:
            return [(1,)]
        if "select count() from stocks s inner join daily_kline d" in normalized and "d.volume >= 1" in normalized:
            return [(2,)]
        return super().execute(query, params)


def test_inspect_clickhouse_database_uses_latest_complete_minute5_bucket() -> None:
    payload = inspect_clickhouse_database(client=PartialLatestMinute5ClickHouseClient())

    minute5 = payload["quality"]["minute5"]
    assert minute5["current_latest_datetime"] == "2026-06-15 15:00:00"
    assert minute5["current_covered_symbols"] == 1
    assert minute5["latest_datetime"] == "2026-06-22 13:35:00"
    assert minute5["covered_symbols"] == 2
    assert minute5["missing_symbols"] == 0


class TradingCalendarFreshDailyClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "select k.datetime, uniqexact(k.symbol)" in normalized and "from minute5_kline k" in normalized:
            return []
        if "from trade_calendar" in normalized and "max(date)" in normalized:
            return [(date(2026, 6, 18),)]
        if "from trade_calendar" in normalized and "count()" in normalized:
            return [(0,)]
        if "from daily_kline" in normalized and "select count(), min(date), max(date)" in normalized:
            return [(10, date(2026, 6, 11), date(2026, 6, 18), 3)]
        return super().execute(query, params)


def test_inspect_clickhouse_database_checks_daily_freshness_by_trade_calendar() -> None:
    payload = inspect_clickhouse_database(
        client=TradingCalendarFreshDailyClickHouseClient(),
        as_of=date(2026, 6, 22),
    )

    freshness = payload["quality"]["scheduled_checks"]["freshness"]
    assert freshness["status"] == "ok"
    assert freshness["latest_date"] == "2026-06-18"
    assert freshness["expected_latest_date"] == "2026-06-18"
    assert freshness["trading_lag_days"] == 0
    assert not any(issue.startswith("daily_kline_stale") for issue in payload["quality"]["issues"])
