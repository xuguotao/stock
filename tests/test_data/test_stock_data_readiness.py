from __future__ import annotations

from datetime import date
from typing import Any

from src.data.stock_data_readiness import (
    compute_dimension_snapshots,
    compute_initial_pool,
    ensure_readiness_table,
    evaluate_window_coverage,
    persist_readiness_snapshot,
    run_readiness_repair,
    run_readiness_snapshot,
)


class FakeClient:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> list[tuple[Any, ...]]:
        self.calls.append((query, params))
        return self.rows


def test_initial_pool_filters_market_name_and_listing_age() -> None:
    client = FakeClient([
        ("000001", "平安银行", "SZ", "1991-04-03"),
        ("688001", "科创公司", "SH", "2020-01-01"),
        ("300001", "创业公司", "SZ", "2020-01-01"),
        ("830001", "北交所股票", "BJ", "2020-01-01"),
        ("000002", "*ST某公司", "SZ", "2000-01-01"),
        ("600001", "退市某某", "SH", "2010-01-01"),
        ("000003", "新股", "SZ", "2026-06-01"),
    ])

    pool = compute_initial_pool(client, as_of=date(2026, 7, 7))

    assert [row["symbol"] for row in pool] == ["000001", "688001", "300001"]
    assert {row["symbol"]: row["board"] for row in pool} == {
        "000001": "MAIN",
        "688001": "STAR",
        "300001": "CHINEXT",
    }


def test_evaluate_window_coverage_statuses() -> None:
    trade_dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]

    ready = evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates=set(trade_dates),
        repair_attempts=0,
        repair_supported=True,
    )
    assert ready["status"] == "ready"
    assert ready["coverage_ratio"] == 1
    assert ready["missing_days"] == 0

    repairable = evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates={trade_dates[0], trade_dates[2]},
        repair_attempts=0,
        repair_supported=True,
    )
    assert repairable["status"] == "repairable"
    assert repairable["missing_samples"] == ["2026-07-02"]

    unrepairable = evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates={trade_dates[0], trade_dates[2]},
        repair_attempts=3,
        repair_supported=True,
    )
    assert unrepairable["status"] == "unrepairable"

    partial = evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates={trade_dates[0], trade_dates[2]},
        repair_attempts=0,
        repair_supported=False,
    )
    assert partial["status"] == "partial"

    no_data = evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates=set(),
        repair_attempts=0,
        repair_supported=True,
    )
    assert no_data["status"] == "no_data"


def test_ensure_readiness_table_creates_summary_and_gap_tables() -> None:
    client = FakeClient()

    ensure_readiness_table(client)

    executed = "\n".join(query.lower() for query, _params in client.calls)
    assert "create table if not exists stock_data_readiness" in executed
    assert "create table if not exists stock_data_readiness_gaps" in executed


def test_persist_readiness_snapshot_uses_batch_insert() -> None:
    client = FakeClient()
    rows = [{
        "symbol": "000001",
        "name": "平安银行",
        "market": "SZ",
        "board": "MAIN",
        "dimension": "daily",
        "first_date": date(2026, 7, 1),
        "latest_date": date(2026, 7, 3),
        "covered_days": 2,
        "missing_days": 1,
        "checked_days": 3,
        "window_start": date(2026, 7, 1),
        "window_end": date(2026, 7, 3),
        "query_trade_days": 3,
        "status": "repairable",
        "repair_supported": True,
        "repair_attempts": 0,
        "last_repair_error": "",
        "computed_at": "2026-07-07 15:40:00",
    }]
    gap_rows = [{
        "symbol": "000001",
        "dimension": "daily",
        "trade_date": date(2026, 7, 2),
        "reason": "missing_daily",
        "repair_attempts": 0,
        "last_repair_error": "",
        "computed_at": "2026-07-07 15:40:00",
    }]

    persist_readiness_snapshot(client, rows, gap_rows)

    insert_calls = [(query, params) for query, params in client.calls if "insert into" in query.lower()]
    assert len(insert_calls) == 2
    assert "stock_data_readiness" in insert_calls[0][0]
    assert insert_calls[0][1] == [(
        "000001", "平安银行", "SZ", "MAIN", "daily",
        date(2026, 7, 1), date(2026, 7, 3), 3,
        date(2026, 7, 1), date(2026, 7, 3), 2, 1, 3,
        "repairable", 1, 0, "", "2026-07-07 15:40:00",
    )]
    assert "stock_data_readiness_gaps" in insert_calls[1][0]
    assert insert_calls[1][1] == [(
        "000001", "daily", date(2026, 7, 2), "missing_daily", 0, "", "2026-07-07 15:40:00",
    )]


def test_persist_readiness_snapshot_replaces_stale_gaps_for_written_dimensions() -> None:
    client = FakeClient()
    rows = [{
        "symbol": "000001",
        "name": "平安银行",
        "market": "SZ",
        "board": "MAIN",
        "dimension": "daily",
        "first_date": date(2026, 7, 1),
        "latest_date": date(2026, 7, 3),
        "covered_days": 3,
        "missing_days": 0,
        "checked_days": 3,
        "window_start": date(2026, 7, 1),
        "window_end": date(2026, 7, 3),
        "query_trade_days": 3,
        "status": "ready",
        "repair_supported": True,
        "repair_attempts": 1,
        "last_repair_error": "",
        "computed_at": "2026-07-07 15:40:00",
    }]

    persist_readiness_snapshot(client, rows, [])

    delete_calls = [(query, params) for query, params in client.calls if "delete where" in query.lower()]
    assert len(delete_calls) == 1
    assert "stock_data_readiness_gaps" in delete_calls[0][0]
    assert delete_calls[0][1] == {"dimensions": ("daily",), "symbols": ("000001",)}


def test_run_readiness_snapshot_can_be_bounded_to_symbols_and_limit() -> None:
    class SnapshotClient(FakeClient):
        def execute(self, query: str, params: Any = None) -> list[tuple[Any, ...]]:
            self.calls.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from stocks" in normalized:
                return [
                    ("000001", "平安银行", "SZ", "1991-04-03"),
                    ("000002", "万科A", "SZ", "1991-01-29"),
                    ("600519", "贵州茅台", "SH", "2001-08-27"),
                ]
            if "from trade_calendar" in normalized:
                return [(date(2026, 7, 1),), (date(2026, 7, 2),)]
            if "from daily_kline" in normalized and "select distinct" in normalized:
                return [(date(2026, 7, 1),), (date(2026, 7, 2),)]
            if "from daily_kline" in normalized and "select max" in normalized:
                return [(date(2026, 7, 2),)]
            if "stock_data_readiness_gaps" in normalized and "select max" in normalized:
                return [(0,)]
            return []

    client = SnapshotClient()

    result = run_readiness_snapshot({
        "client": client,
        "as_of": "2026-07-02",
        "lookback_days": 2,
        "dimensions": ["daily"],
        "symbols": ["000001", "600519"],
        "limit": 1,
    })

    assert result["status"] == "success"
    assert result["total"] == 1
    inserts = [(query, params) for query, params in client.calls if "insert into stock_data_readiness" in query.lower()]
    assert inserts[0][1][0][0] == "000001"


def test_run_readiness_snapshot_accepts_explicit_start_and_end_window() -> None:
    class SnapshotClient(FakeClient):
        def execute(self, query: str, params: Any = None) -> list[tuple[Any, ...]]:
            self.calls.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from stocks" in normalized:
                return [("000001", "平安银行", "SZ", "1991-04-03")]
            if "from trade_calendar" in normalized:
                assert params == {"start": date(2026, 1, 9), "end": date(2026, 7, 8)}
                return [(date(2026, 1, 9),), (date(2026, 7, 8),)]
            if "from daily_kline" in normalized and "group by symbol" in normalized:
                return [("000001", [date(2026, 1, 9), date(2026, 7, 8)], date(2026, 1, 9), date(2026, 7, 8))]
            return []

    client = SnapshotClient()

    result = run_readiness_snapshot({
        "client": client,
        "start": "2026-01-09",
        "end": "2026-07-08",
        "dimensions": ["daily"],
    })

    assert result["status"] == "success"
    assert result["start"] == "2026-01-09"
    assert result["end"] == "2026-07-08"
    insert_params = next(params for query, params in client.calls if "insert into stock_data_readiness" in query.lower())
    assert insert_params[0][5:8] == (date(2026, 1, 9), date(2026, 7, 8), 2)


def test_compute_dimension_snapshots_fetches_dimension_data_in_one_batch() -> None:
    class BatchClient(FakeClient):
        def execute(self, query: str, params: Any = None) -> list[tuple[Any, ...]]:
            self.calls.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from daily_kline" in normalized and "group by symbol" in normalized:
                return [
                    ("000001", [date(2026, 7, 1), date(2026, 7, 2)], date(2026, 7, 1), date(2026, 7, 2)),
                    ("000002", [date(2026, 7, 1)], date(2026, 7, 1), date(2026, 7, 1)),
                ]
            if "from stock_data_readiness_gaps" in normalized and "group by symbol" in normalized:
                return [("000002", 1)]
            return []

    client = BatchClient()
    stocks = [
        {"symbol": "000001", "name": "平安银行", "market": "SZ", "board": "MAIN"},
        {"symbol": "000002", "name": "万科A", "market": "SZ", "board": "MAIN"},
    ]

    rows, gaps = compute_dimension_snapshots(
        client,
        stocks=stocks,
        dimension="daily",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        computed_at="2026-07-08 10:00:00",
    )

    assert len(rows) == 2
    assert rows[0]["covered_days"] == 2
    assert rows[1]["covered_days"] == 1
    assert rows[1]["repair_attempts"] == 1
    assert gaps == [{
        "symbol": "000002",
        "dimension": "daily",
        "trade_date": date(2026, 7, 2),
        "reason": "missing_daily",
        "repair_attempts": 1,
        "last_repair_error": "",
        "computed_at": "2026-07-08 10:00:00",
    }]
    daily_queries = [query for query, _params in client.calls if "from daily_kline" in query.lower()]
    assert len(daily_queries) == 1


def test_run_readiness_repair_backfills_daily_and_minute5_then_refreshes_snapshot() -> None:
    class GapClient(FakeClient):
        def execute(self, query: str, params: Any = None) -> list[tuple[Any, ...]]:
            self.calls.append((query, params))
            if "stock_data_readiness_gaps" in query.lower() and "select" in query.lower():
                return [
                    ("000001", "daily", date(2026, 7, 1), 0),
                    ("000002", "daily", date(2026, 7, 1), 1),
                    ("000001", "minute5", date(2026, 7, 1), 0),
                    ("000001", "minute5", date(2026, 7, 2), 0),
                ]
            return []

    client = GapClient()
    daily_calls: list[dict[str, Any]] = []
    minute5_calls: list[dict[str, Any]] = []
    snapshot_calls: list[dict[str, Any]] = []

    def fake_daily_runner(**kwargs: Any) -> dict[str, Any]:
        daily_calls.append(kwargs)
        return {"inserted_rows": 2}

    def fake_minute5_runner(**kwargs: Any) -> dict[str, Any]:
        minute5_calls.append(kwargs)
        return {"inserted_rows": 4}

    def fake_snapshot_runner(params: dict[str, Any]) -> dict[str, Any]:
        snapshot_calls.append(params)
        return {"rows": 4, "gaps": 0}

    result = run_readiness_repair({
        "client": client,
        "symbols": ["000001"],
        "dimensions": ["daily", "minute5"],
        "start": "2026-07-01",
        "end": "2026-07-02",
        "daily_repair_runner": fake_daily_runner,
        "minute5_history_runner": fake_minute5_runner,
        "snapshot_runner": fake_snapshot_runner,
    })

    assert result["status"] == "success"
    assert result["attempted_gaps"] == 4
    assert [call["trade_date"] for call in daily_calls] == [date(2026, 7, 1)]
    assert daily_calls[0]["client"] is client
    assert minute5_calls == [{
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 2),
        "symbols": ["000001"],
        "limit": 0,
        "include_st": False,
        "client": client,
        "progress": None,
    }]
    assert snapshot_calls[0]["as_of"] == date(2026, 7, 2)
    assert snapshot_calls[0]["dimensions"] == ["daily", "minute5"]
    assert snapshot_calls[0]["symbols"] == ["000001", "000002"]
    repair_gap_query = next(
        query.lower()
        for query, _params in client.calls
        if "from stock_data_readiness_gaps" in query.lower() and "group by" in query.lower()
    )
    normalized_repair_gap_query = " ".join(repair_gap_query.split())
    assert "from (" in normalized_repair_gap_query
    assert "where repair_attempts < %(max_attempts)s" in normalized_repair_gap_query
    assert "having max(repair_attempts)" not in normalized_repair_gap_query


def test_run_readiness_repair_marks_snapshot_dimension_unsupported() -> None:
    result = run_readiness_repair({
        "client": FakeClient(),
        "symbols": ["000001"],
        "dimensions": ["snapshot"],
        "start": "2026-07-01",
        "end": "2026-07-02",
        "snapshot_runner": lambda params: {"rows": 0},
    })

    assert result["status"] == "skipped"
    assert result["unsupported_dimensions"] == ["snapshot"]
