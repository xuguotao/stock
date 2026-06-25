from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
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


def test_tail_ml_train_api_runs_inline_training_job(tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_sample_builder(**kwargs):
        calls["builder"] = kwargs
        return SimpleNamespace(
            samples=pd.DataFrame(
                [
                    {
                        "trade_date": "2026-06-01",
                        "symbol": "000001.SZ",
                        "tail_return_from_1430": 0.01,
                        "tail_volume_ratio": 2.0,
                        "last3_close_slope": 0.01,
                        "tail_pullback_from_high": -0.001,
                        "next_high_return": 0.02,
                        "next_open_return": 0.01,
                        "next_low_return": -0.01,
                        "hit_next_high_1pct": True,
                        "drawdown_breach_2pct": False,
                    }
                ]
            ),
            summary={"sample_rows": 1, "symbols": 1, "trade_dates": 1, "null_label_rows": 0},
        )

    def fake_trainer(samples, **kwargs):
        calls["trainer"] = {"samples": samples, **kwargs}
        return {
            "version": kwargs["version"],
            "status": "ready",
            "artifact_dir": str(tmp_path / "models" / kwargs["version"]),
            "sample_count": int(len(samples)),
            "fold_count": 1,
            "metrics": {
                "selected_days": 1,
                "hit_next_high_1pct_rate": 1.0,
                "avg_next_high_return": 0.03,
                "avg_next_low_drawdown": -0.01,
            },
            "feature_columns": ["tail_return_from_1430"],
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        run_jobs_inline=True,
        tail_model_root=tmp_path / "models",
        tail_ml_sample_builder=fake_sample_builder,
        tail_model_trainer=fake_trainer,
    )
    client = TestClient(app)

    response = client.post(
        "/api/ml/tail/train",
        json={
            "start": "2026-06-01",
            "end": "2026-06-20",
            "version": "tail-test-train",
            "top_n": 2,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["kind"] == "tail_ml_train"
    assert job["status"] == "success"
    assert calls["builder"]["start"].isoformat() == "2026-06-01"
    assert calls["builder"]["end"].isoformat() == "2026-06-20"
    assert calls["trainer"]["version"] == "tail-test-train"
    assert calls["trainer"]["output_root"] == tmp_path / "models"
    assert job["result"]["dataset_summary"]["sample_rows"] == 1
    assert job["result"]["manifest"]["version"] == "tail-test-train"
    assert job["result"]["manifest"]["baseline_metrics"]["top_n"] == 2
    assert job["result"]["manifest"]["promotion_decision"]["status"] == "rejected"


def test_tail_ml_promote_api_marks_only_requested_model_promoted(tmp_path) -> None:
    model_root = tmp_path / "models"
    first = model_root / "tail-a"
    second = model_root / "tail-b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "manifest.json").write_text(
        json.dumps({"version": "tail-a", "status": "promoted", "created_at": "2026-06-25T09:00:00+00:00"}),
        encoding="utf-8",
    )
    (second / "manifest.json").write_text(
        json.dumps({"version": "tail-b", "status": "ready", "created_at": "2026-06-25T10:00:00+00:00"}),
        encoding="utf-8",
    )
    app = create_app(db_path=tmp_path / "jobs.sqlite3", tail_model_root=model_root)
    client = TestClient(app)

    response = client.post("/api/ml/tail/models/tail-b/promote")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "tail-b"
    assert payload["status"] == "promoted"
    assert json.loads((first / "manifest.json").read_text(encoding="utf-8"))["status"] == "ready"
    assert json.loads((second / "manifest.json").read_text(encoding="utf-8"))["status"] == "promoted"
