from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.stock_readiness import build_readiness_summary, query_readiness


class FakeReadinessClient:
    def __init__(self) -> None:
        self.summary_rows = [
            ("000001", "平安银行", "SZ", "MAIN", "daily", date(2026, 7, 1), date(2026, 7, 2), 2, date(2020, 1, 2), date(2026, 7, 7), 100, 0, 100, "ready", 1, 0, ""),
            ("000002", "万科A", "SZ", "MAIN", "daily", date(2026, 7, 1), date(2026, 7, 2), 2, date(2020, 1, 2), date(2026, 7, 7), 99, 1, 100, "repairable", 1, 1, ""),
            ("000003", "缺数据", "SZ", "MAIN", "daily", date(2026, 7, 1), date(2026, 7, 2), 2, None, None, 0, 100, 100, "no_data", 1, 0, ""),
        ]
        self.gap_rows = [
            ("000002", "daily", date(2026, 7, 2), "missing_daily", 1, ""),
            ("000003", "daily", date(2026, 7, 1), "missing_daily", 0, ""),
            ("000003", "daily", date(2026, 7, 2), "missing_daily", 0, ""),
        ]

    def execute(self, query: str, params=None):
        q = query.lower()
        if "trade_calendar" in q:
            return [(date(2026, 7, 1),), (date(2026, 7, 2),)]
        if "stock_data_readiness_gaps" in q:
            return self.gap_rows
        if "stock_data_readiness" in q:
            return self.summary_rows
        return []


def test_build_readiness_summary_groups_statuses() -> None:
    result = build_readiness_summary(
        FakeReadinessClient(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 2),
        dimensions=["daily"],
    )

    assert result["total_symbols"] == 3
    assert result["dimensions"]["daily"]["ready"] == 1
    assert result["dimensions"]["daily"]["repairable"] == 1
    assert result["dimensions"]["daily"]["no_data"] == 1


def test_build_readiness_summary_counts_beyond_page_size_cap() -> None:
    class ManyReadinessClient(FakeReadinessClient):
        def __init__(self) -> None:
            super().__init__()
            self.summary_rows = [
                (f"{index:06d}", f"股票{index}", "SZ", "MAIN", "daily", date(2026, 7, 1), date(2026, 7, 2), 2, date(2020, 1, 2), date(2026, 7, 7), 2, 0, 2, "ready", 1, 0, "")
                for index in range(1, 505)
            ]
            self.gap_rows = []

    result = build_readiness_summary(
        ManyReadinessClient(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 2),
        dimensions=["daily"],
    )

    assert result["total_symbols"] == 504
    assert result["dimensions"]["daily"]["ready"] == 504


def test_query_readiness_returns_paginated_items() -> None:
    result = query_readiness(
        FakeReadinessClient(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 2),
        dimensions=["daily"],
        page=1,
        page_size=2,
    )

    assert result["total"] == 3
    assert result["page"] == 1
    assert result["page_size"] == 2
    assert result["items"][0]["symbol"] == "000001"
    assert result["items"][0]["dimensions"]["daily"]["status"] == "ready"


def test_query_readiness_status_requires_all_selected_dimensions_to_match() -> None:
    class MultiDimensionClient(FakeReadinessClient):
        def __init__(self) -> None:
            super().__init__()
            self.summary_rows = [
                ("000001", "平安银行", "SZ", "MAIN", "daily", date(2026, 7, 1), date(2026, 7, 2), 2, date(2020, 1, 2), date(2026, 7, 7), 2, 0, 2, "ready", 1, 0, ""),
                ("000001", "平安银行", "SZ", "MAIN", "minute5", date(2026, 7, 1), date(2026, 7, 2), 2, date(2020, 1, 2), date(2026, 7, 7), 2, 0, 2, "ready", 1, 0, ""),
                ("000002", "万科A", "SZ", "MAIN", "daily", date(2026, 7, 1), date(2026, 7, 2), 2, date(2020, 1, 2), date(2026, 7, 7), 2, 0, 2, "ready", 1, 0, ""),
                ("000002", "万科A", "SZ", "MAIN", "minute5", date(2026, 7, 1), date(2026, 7, 2), 2, None, None, 0, 2, 2, "no_data", 1, 0, ""),
            ]
            self.gap_rows = [
                ("000002", "minute5", date(2026, 7, 1), "missing_minute5", 0, ""),
                ("000002", "minute5", date(2026, 7, 2), "missing_minute5", 0, ""),
            ]

    result = query_readiness(
        MultiDimensionClient(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 2),
        dimensions=["daily", "minute5"],
        status="ready",
    )

    assert result["total"] == 1
    assert [item["symbol"] for item in result["items"]] == ["000001"]


def test_query_readiness_marks_ready_snapshot_as_insufficient_for_larger_window() -> None:
    class ShortSnapshotClient(FakeReadinessClient):
        def __init__(self) -> None:
            super().__init__()
            self.summary_rows = [
                ("000001", "平安银行", "SZ", "MAIN", "daily", date(2026, 7, 7), date(2026, 7, 7), 1, date(2026, 7, 7), date(2026, 7, 7), 1, 0, 1, "ready", 1, 0, ""),
            ]
            self.gap_rows = []

        def execute(self, query: str, params=None):
            if "trade_calendar" in query.lower():
                return [(date(2026, 7, 1),), (date(2026, 7, 2),), (date(2026, 7, 7),)]
            return super().execute(query, params)

    result = query_readiness(
        ShortSnapshotClient(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 7),
        dimensions=["daily"],
    )
    daily = result["items"][0]["dimensions"]["daily"]

    assert daily["status"] == "snapshot_insufficient"
    assert daily["coverage_ratio"] == 1 / 3
    assert daily["expected_days"] == 3
    assert daily["checked_days"] == 1

    summary = build_readiness_summary(
        ShortSnapshotClient(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 7),
        dimensions=["daily"],
    )
    assert summary["dimensions"]["daily"]["snapshot_insufficient"] == 1


def test_stock_readiness_routes_return_summary_and_list(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.json", stock_readiness_client=FakeReadinessClient())
    client = TestClient(app)

    summary = client.get("/api/stock-readiness/summary?start=2026-07-01&end=2026-07-02")
    listing = client.get("/api/stock-readiness?start=2026-07-01&end=2026-07-02")

    assert summary.status_code == 200
    assert summary.json()["total_symbols"] == 3
    assert listing.status_code == 200
    assert listing.json()["total"] == 3


def test_stock_readiness_snapshot_route_runs_job(tmp_path) -> None:
    snapshot_calls = []

    def fake_snapshot_runner(params):
        snapshot_calls.append(params)
        return {"status": "success", "rows": 2, "gaps": 0}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        stock_readiness_client=FakeReadinessClient(),
        run_jobs_inline=True,
        stock_readiness_snapshot_runner=fake_snapshot_runner,
    )
    client = TestClient(app)

    response = client.post(
        "/api/stock-readiness/snapshot",
        json={"start": "2026-07-01", "end": "2026-07-02", "dimensions": ["daily", "minute5"]},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "success"
    assert job["result"] == {"status": "success", "rows": 2, "gaps": 0}
    assert snapshot_calls[0]["start"] == date(2026, 7, 1)
    assert snapshot_calls[0]["end"] == date(2026, 7, 2)
    assert snapshot_calls[0]["dimensions"] == ["daily", "minute5"]
    assert snapshot_calls[0]["client"].__class__ is FakeReadinessClient


def test_stock_readiness_repair_route_creates_job(tmp_path) -> None:
    repair_calls = []

    def fake_repair_runner(params):
        repair_calls.append(params)
        return {"status": "success", "attempted_gaps": 1}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        stock_readiness_client=FakeReadinessClient(),
        run_jobs_inline=True,
        stock_readiness_repair_runner=fake_repair_runner,
    )
    client = TestClient(app)

    response = client.post(
        "/api/stock-readiness/repair",
        json={"symbols": ["000002"], "dimensions": ["daily"], "start": "2026-07-01", "end": "2026-07-02"},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "success"
    assert job["result"] == {"status": "success", "attempted_gaps": 1}
    assert repair_calls[0]["symbols"] == ["000002"]
    assert repair_calls[0]["client"].__class__ is FakeReadinessClient
