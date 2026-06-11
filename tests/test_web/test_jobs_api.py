from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_jobs_api_creates_and_lists_jobs(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3")
    client = TestClient(app)

    response = client.post("/api/jobs", json={"kind": "noop", "params": {"x": 1}})
    created = response.json()
    listed = client.get("/api/jobs").json()

    assert response.status_code == 200
    assert created["kind"] == "noop"
    assert created["status"] == "pending"
    assert listed["items"][0]["id"] == created["id"]


def test_jobs_api_returns_one_job(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3")
    client = TestClient(app)
    created = client.post("/api/jobs", json={"kind": "noop", "params": {}}).json()

    response = client.get(f"/api/jobs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
