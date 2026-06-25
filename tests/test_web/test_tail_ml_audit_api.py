from __future__ import annotations

import json

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


def test_tail_ml_audit_api_returns_degraded_payload_when_runner_fails(tmp_path) -> None:
    def failing_audit_runner():
        raise RuntimeError("clickhouse timeout")

    app = create_app(db_path=tmp_path / "jobs.sqlite3", tail_ml_audit_runner=failing_audit_runner)
    client = TestClient(app)

    response = client.get("/api/ml/tail/audit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["issues"] == ["tail_ml_audit_failed"]
    assert "clickhouse timeout" in payload["error"]


def test_tail_ml_models_api_lists_model_manifests(tmp_path) -> None:
    model_root = tmp_path / "models" / "tail_session"
    first = model_root / "tail-001"
    second = model_root / "tail-002"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "manifest.json").write_text(
        json.dumps({
            "version": "tail-001",
            "status": "rejected",
            "created_at": "2026-06-25T09:00:00+00:00",
            "metrics": {"selected_days": 20},
            "feature_columns": ["tail_return_from_1430"],
        }),
        encoding="utf-8",
    )
    (second / "manifest.json").write_text(
        json.dumps({
            "version": "tail-002",
            "status": "ready",
            "created_at": "2026-06-25T10:00:00+00:00",
            "metrics": {"selected_days": 35},
            "feature_columns": ["tail_volume_ratio"],
        }),
        encoding="utf-8",
    )

    app = create_app(db_path=tmp_path / "jobs.sqlite3", tail_model_root=model_root)
    client = TestClient(app)

    response = client.get("/api/ml/tail/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_root"] == str(model_root)
    assert [item["version"] for item in payload["items"]] == ["tail-002", "tail-001"]
    assert payload["items"][0]["metrics"]["selected_days"] == 35
