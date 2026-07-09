from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.jobs import JobStore


def test_jobs_api_creates_and_lists_jobs(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.json")
    client = TestClient(app)

    response = client.post("/api/jobs", json={"kind": "noop", "params": {"x": 1}})
    created = response.json()
    listed = client.get("/api/jobs").json()

    assert response.status_code == 200
    assert created["kind"] == "noop"
    assert created["status"] == "pending"
    assert created["health"] == "pending"
    assert created["heartbeat_at"] is None
    assert created["progress"] == {"percent": 0, "stage": "pending", "message": "等待执行"}
    assert listed["items"][0]["id"] == created["id"]
    assert listed["items"][0]["health"] == "pending"
    assert listed["items"][0]["progress"]["percent"] == 0


def test_jobs_api_returns_one_job(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.json")
    client = TestClient(app)
    created = client.post("/api/jobs", json={"kind": "noop", "params": {}}).json()

    response = client.get(f"/api/jobs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_job_store_records_running_heartbeat_and_marks_stale_jobs(tmp_path) -> None:
    db_path = tmp_path / "jobs.json"
    store = JobStore(db_path)
    job = store.create_job("minute5_sync", {})

    running = store.update_job(
        job.id,
        status="running",
        progress={"percent": 40, "stage": "fetching", "message": "更新分钟线"},
    )

    assert running.status == "running"
    assert running.health == "running"
    assert running.heartbeat_at is not None

    old_heartbeat = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    payload = json.loads(db_path.read_text(encoding="utf-8"))
    payload[0]["heartbeat_at"] = old_heartbeat
    db_path.write_text(json.dumps(payload), encoding="utf-8")

    stale = store.get_job(job.id)

    assert stale is not None
    assert stale.status == "running"
    assert stale.health == "stale"
    assert stale.heartbeat_at == old_heartbeat


def test_jobs_api_lists_result_summaries_without_heavy_signal_rows(tmp_path) -> None:
    db_path = tmp_path / "jobs.json"
    app = create_app(db_path=db_path)
    client = TestClient(app)
    created = client.post("/api/jobs", json={"kind": "tail_session_live_selection", "params": {}}).json()
    store = JobStore(db_path)
    store.update_job(
        created["id"],
        status="success",
        result={
            "mode": "selection",
            "trade_date": "2026-06-25",
            "scanned_count": 4977,
            "selected_count": 1,
            "ranked_signals": [{"symbol": "000001.SZ"}, {"symbol": "600519.SH"}],
            "selections": [{"symbol": "000001.SZ"}],
            "diagnostics": {"empty_reason": None, "latest_intraday_time": "15:00:00"},
        },
    )

    listed = client.get("/api/jobs").json()["items"][0]
    detail = client.get(f"/api/jobs/{created['id']}").json()

    assert listed["result"]["ranked_count"] == 2
    assert listed["result"]["selected_count"] == 1
    assert "ranked_signals" not in listed["result"]
    assert len(detail["result"]["ranked_signals"]) == 2


def test_job_store_marks_existing_running_jobs_interrupted_on_startup(tmp_path) -> None:
    db_path = tmp_path / "jobs.json"
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
