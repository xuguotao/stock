from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.jobs import JobStore


def test_jobs_api_creates_and_lists_jobs(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3")
    client = TestClient(app)

    response = client.post("/api/jobs", json={"kind": "noop", "params": {"x": 1}})
    created = response.json()
    listed = client.get("/api/jobs").json()

    assert response.status_code == 200
    assert created["kind"] == "noop"
    assert created["status"] == "pending"
    assert created["progress"] == {"percent": 0, "stage": "pending", "message": "等待执行"}
    assert listed["items"][0]["id"] == created["id"]
    assert listed["items"][0]["progress"]["percent"] == 0


def test_jobs_api_returns_one_job(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3")
    client = TestClient(app)
    created = client.post("/api/jobs", json={"kind": "noop", "params": {}}).json()

    response = client.get(f"/api/jobs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_job_store_marks_existing_running_jobs_interrupted_on_startup(tmp_path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    running = store.create_job("daily_maintenance", {})
    store.update_job(
        running.id,
        status="running",
        progress={"percent": 53, "stage": "fetching", "message": "更新 603721.SH ClickHouse 5m 分钟线 7/10"},
    )
    success = store.create_job("daily_maintenance", {})
    store.update_job(success.id, status="success", result={"ok": True})

    marked = store.mark_running_jobs_interrupted("服务重启，任务进程已中断")

    interrupted = store.get_job(running.id)
    untouched = store.get_job(success.id)
    assert marked == 1
    assert interrupted is not None
    assert interrupted.status == "failed"
    assert interrupted.error == "服务重启，任务进程已中断"
    assert interrupted.progress == {"percent": 100, "stage": "interrupted", "message": "服务重启，任务进程已中断"}
    assert untouched is not None
    assert untouched.status == "success"
