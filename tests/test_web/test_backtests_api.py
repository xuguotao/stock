from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_backtest_api_runs_with_inline_sample_dataset(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "capital": 100000,
            "top_n": 2,
            "sample": True,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert "metrics" in job["result"]
    assert "equity_curve" in job["result"]
    assert len(job["result"]["equity_curve"]) > 0


def test_backtest_api_rejects_missing_dataset_when_not_sample(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "sample": False,
        },
    )

    assert response.status_code == 422
