from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.data_ops.models import DataOpsTaskConfig, DataOpsTaskStatus
from src.web.backend.app import create_app


class FakeDataOpsRepository:
    def __init__(self) -> None:
        self.configs = {
            "quality_snapshot": DataOpsTaskConfig(
                task_key="quality_snapshot",
                enabled=True,
                schedule_kind="interval",
                schedule_config={"interval_seconds": 300},
            )
        }
        self.manual_runs: list[str] = []

    def ensure_tables(self):
        return None

    def seed_default_configs(self):
        return None

    def list_task_configs(self):
        return list(self.configs.values())

    def list_task_statuses(self, now=None):
        statuses = [
            DataOpsTaskStatus(
                task_key="quality_snapshot",
                enabled=self.configs["quality_snapshot"].enabled,
                status="success",
                schedule_kind=self.configs["quality_snapshot"].schedule_kind,
                schedule_config=self.configs["quality_snapshot"].schedule_config,
                last_started_at=datetime(2026, 6, 12, 10, 0),
                last_finished_at=datetime(2026, 6, 12, 10, 0, 3),
                last_result={"rows": 3},
                progress_percent=75,
                progress_stage="writing",
                progress_message="写入质量快照",
            )
        ]
        for key, config in self.configs.items():
            if key != "quality_snapshot":
                statuses.append(DataOpsTaskStatus(
                    task_key=key,
                    enabled=config.enabled,
                    status="idle",
                    schedule_kind=config.schedule_kind,
                    schedule_config=config.schedule_config,
                ))
        return statuses

    def upsert_task_config(self, config, now=None):
        self.configs[config.task_key] = config

    def request_manual_run(self, task_key, now=None):
        if task_key not in self.configs:
            raise KeyError(task_key)
        self.manual_runs.append(task_key)


def _app(repo: FakeDataOpsRepository):
    return create_app(
        data_ops_repository=repo,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )


def test_data_ops_tasks_api_lists_persisted_task_status() -> None:
    repo = FakeDataOpsRepository()
    client = TestClient(_app(repo))

    response = client.get("/api/data/ops-tasks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["task_key"] == "quality_snapshot"
    assert payload["items"][0]["enabled"] is True
    assert payload["items"][0]["status"] == "success"
    assert payload["items"][0]["last_result"] == {"rows": 3}
    assert payload["items"][0]["progress_percent"] == 75
    assert payload["items"][0]["progress_stage"] == "writing"
    assert payload["items"][0]["progress_message"] == "写入质量快照"
    assert payload["items"][0]["max_runtime_seconds"] == 1800
    assert payload["items"][0]["stale_after_seconds"] == 300


def test_data_ops_tasks_api_updates_config() -> None:
    repo = FakeDataOpsRepository()
    client = TestClient(_app(repo))

    response = client.put(
        "/api/data/ops-tasks/quality_snapshot/config",
        json={
            "enabled": False,
            "schedule_kind": "manual",
            "schedule_config": {},
            "max_runtime_seconds": 120,
            "stale_after_seconds": 60,
        },
    )

    assert response.status_code == 200
    assert repo.configs["quality_snapshot"].enabled is False
    assert repo.configs["quality_snapshot"].schedule_kind == "manual"
    assert response.json()["item"]["status"] == "success"


def test_universe_profile_rule_change_increments_rule_version() -> None:
    repo = FakeDataOpsRepository()
    repo.configs["stock_universe_profile_refresh"] = DataOpsTaskConfig(
        task_key="stock_universe_profile_refresh",
        enabled=True,
        schedule_kind="daily_time",
        schedule_config={"time": "16:15", "lookback_days": 20, "min_trading_days": 15, "min_average_amount": 10_000_000, "min_listing_age_days": 0, "include_beijing": False},
    )
    client = TestClient(_app(repo))

    response = client.put("/api/data/ops-tasks/stock_universe_profile_refresh/config", json={
        "enabled": True, "schedule_kind": "daily_time",
        "schedule_config": {"time": "16:15", "lookback_days": 20, "min_trading_days": 15, "min_average_amount": 20_000_000, "min_listing_age_days": 0, "include_beijing": False},
        "max_runtime_seconds": 900, "stale_after_seconds": 300,
    })

    assert response.status_code == 200
    assert repo.configs["stock_universe_profile_refresh"].schedule_config["rule_version"] == 2


def test_data_ops_tasks_api_run_once_sets_manual_trigger_only() -> None:
    repo = FakeDataOpsRepository()
    client = TestClient(_app(repo))

    response = client.post("/api/data/ops-tasks/quality_snapshot/run-once")

    assert response.status_code == 200
    assert response.json() == {"task_key": "quality_snapshot", "manual_trigger": True}
    assert repo.manual_runs == ["quality_snapshot"]


def test_data_ops_tasks_api_unknown_task_returns_404() -> None:
    repo = FakeDataOpsRepository()
    client = TestClient(_app(repo))

    response = client.post("/api/data/ops-tasks/missing/run-once")

    assert response.status_code == 404


def test_mootdx_monitor_api_returns_persisted_monitor_snapshot() -> None:
    class FakeMootdxMonitor:
        def snapshot(self, *, audit_limit: int = 50):
            assert audit_limit == 50
            return {
                "tasks": [{"task_key": "mootdx_stock_catalog_sync", "label": "股票目录同步", "status": "idle"}],
                "audits": [{"task_key": "stock_catalog", "audit": {"status": "healthy", "reasons": []}}],
                "health": {"catalog": {"status": "healthy", "symbols": 4996}},
            }

    app = create_app(
        data_ops_repository=FakeDataOpsRepository(),
        mootdx_monitor_service=FakeMootdxMonitor(),
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )

    response = TestClient(app).get("/api/data/mootdx/monitor")

    assert response.status_code == 200
    assert response.json()["health"]["catalog"]["symbols"] == 4996


def test_mootdx_quality_apis_return_quality_snapshots() -> None:
    class FakeMootdxQuality:
        def catalog_quality(self, *, event_limit: int = 200):
            assert event_limit == 12
            return {"summary": {"symbols": 4996}, "daily_changes": [], "events": []}

        def daily_quality(self, *, lookback_days: int = 30, missing_limit: int = 200):
            assert lookback_days == 15
            assert missing_limit == 40
            return {"summary": {"latest_trade_date": "2026-07-09"}, "daily_coverage": [], "missing_details": []}

    app = create_app(
        data_ops_repository=FakeDataOpsRepository(),
        mootdx_quality_service=FakeMootdxQuality(),
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    catalog_response = client.get("/api/data/mootdx/catalog-quality?event_limit=12")
    daily_response = client.get("/api/data/mootdx/daily-quality?lookback_days=15&missing_limit=40")

    assert catalog_response.status_code == 200
    assert catalog_response.json()["summary"]["symbols"] == 4996
    assert daily_response.status_code == 200
    assert daily_response.json()["summary"]["latest_trade_date"] == "2026-07-09"


def test_mootdx_daily_gap_repair_creates_auditable_targeted_job(tmp_path) -> None:
    calls = []

    def repair_runner(**kwargs):
        calls.append(kwargs)
        return {"inserted": {"mootdx_stock_kline": 2}, "failed": {}}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        data_ops_repository=FakeDataOpsRepository(),
        mootdx_daily_gap_repair_runner=repair_runner,
        run_jobs_inline=True,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/mootdx/daily-quality/repair",
        json={
            "items": [
                {
                    "symbol": "000504.SZ",
                    "start_date": "2026-06-11",
                    "end_date": "2026-06-11",
                    "evidence": "缺口前后交易日均有日线记录",
                }
            ]
        },
    )

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["kind"] == "mootdx_daily_gap_repair"
    assert job["status"] == "success"
    assert calls[0]["symbols"] == ["000504.SZ"]
    assert calls[0]["start_date"].isoformat() == "2026-06-11"
    assert calls[0]["end_date"].isoformat() == "2026-06-11"


def test_mootdx_daily_gap_repair_marks_returned_task_failure_as_failed(tmp_path) -> None:
    def repair_runner(**_kwargs):
        return {"inserted": {}, "failed": {"stock_kline_daily": "RuntimeError: source unavailable"}}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        data_ops_repository=FakeDataOpsRepository(),
        mootdx_daily_gap_repair_runner=repair_runner,
        run_jobs_inline=True,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    response = client.post("/api/data/mootdx/daily-quality/repair", json={"items": [{
        "symbol": "000504.SZ", "start_date": "2026-06-11", "end_date": "2026-06-11", "evidence": "待回补",
    }]})

    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "failed"
    assert "source unavailable" in job["error"]


def test_mootdx_daily_gap_verify_creates_progress_job(tmp_path) -> None:
    calls = []

    def verify_runner(**kwargs):
        calls.append(kwargs)
        return {"available": 1, "no_data": 2, "error": 0}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        data_ops_repository=FakeDataOpsRepository(),
        mootdx_daily_gap_verify_runner=verify_runner,
        run_jobs_inline=True,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    response = client.post("/api/data/mootdx/daily-quality/verify", json={"items": [{
        "symbol": "000524.SZ", "start_date": "2026-06-24", "end_date": "2026-07-07", "evidence": "待核验",
    }]})

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["kind"] == "mootdx_daily_gap_verify"
    assert job["status"] == "success"
    assert job["progress"]["processed"] == 1
    assert job["progress"]["total"] == 1
    assert calls[0]["items"][0].symbol == "000524.SZ"


def test_mootdx_daily_gap_verify_passes_explicit_missing_trade_dates_to_runner(tmp_path) -> None:
    calls = []

    def verify_runner(**kwargs):
        calls.append(kwargs)
        return {"available": 0, "no_data": 2, "error": 0}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        data_ops_repository=FakeDataOpsRepository(),
        mootdx_daily_gap_verify_runner=verify_runner,
        run_jobs_inline=True,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    response = client.post("/api/data/mootdx/daily-quality/verify", json={"items": [{
        "symbol": "000524.SZ", "start_date": "2026-07-10", "end_date": "2026-07-13",
        "trade_dates": ["2026-07-10", "2026-07-13"], "evidence": "跨周末连续缺口",
    }]})

    assert response.status_code == 200
    assert [value.isoformat() for value in calls[0]["items"][0].trade_dates] == ["2026-07-10", "2026-07-13"]
