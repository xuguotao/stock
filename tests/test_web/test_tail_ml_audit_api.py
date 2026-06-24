from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_tail_ml_audit_api_returns_runner_payload(tmp_path) -> None:
    def fake_audit_runner():
        return {
            "status": "limited",
            "as_of": "2026-06-24",
            "summary": {
                "daily_rows": 7_252_052,
                "daily_symbols": 5207,
                "minute5_rows": 25_747_349,
                "minute5_symbols": 4991,
                "minute5_usable_days": 108,
                "joinable_label_days": 89,
                "tradable_pool": 4936,
            },
            "issues": ["minute5_history_limited_108_days"],
        }

    app = create_app(db_path=tmp_path / "jobs.sqlite3", tail_ml_audit_runner=fake_audit_runner)
    client = TestClient(app)

    response = client.get("/api/ml/tail/audit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "limited"
    assert payload["summary"]["minute5_usable_days"] == 108
    assert payload["issues"] == ["minute5_history_limited_108_days"]
