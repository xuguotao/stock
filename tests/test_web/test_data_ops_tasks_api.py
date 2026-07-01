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
        return [
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
