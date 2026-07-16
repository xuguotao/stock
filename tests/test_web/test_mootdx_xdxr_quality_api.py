from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


class _FakeMootdxQuality:
    def __init__(self) -> None:
        self.quality_calls: list[dict[str, object]] = []
        self.detail_calls: list[dict[str, object]] = []

    def xdxr_quality(self, *, limit: int, start_date: date | None, end_date: date | None, status: str | None):
        self.quality_calls.append({
            "limit": limit,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
        })
        return {"runs": [], "data_summary": {}}

    def xdxr_run_detail(self, run_id: str, *, status: str | None, limit: int):
        self.detail_calls.append({"run_id": run_id, "status": status, "limit": limit})
        if run_id == "missing":
            return None
        return {"run_id": run_id, "items": []}


def _client(service: _FakeMootdxQuality) -> TestClient:
    app = create_app(
        mootdx_quality_service=service,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    return TestClient(app)


def test_xdxr_quality_api_forwards_history_filters() -> None:
    service = _FakeMootdxQuality()

    response = _client(service).get(
        "/api/data/mootdx/xdxr-quality?limit=12&start_date=2026-07-01&end_date=2026-07-14&status=failed"
    )

    assert response.status_code == 200
    assert service.quality_calls == [{
        "limit": 12,
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 14),
        "status": "failed",
    }]


def test_xdxr_quality_api_rejects_invalid_history_filters() -> None:
    service = _FakeMootdxQuality()
    client = _client(service)

    invalid_status = client.get("/api/data/mootdx/xdxr-quality?status=unknown")
    invalid_range = client.get("/api/data/mootdx/xdxr-quality?start_date=2026-07-15&end_date=2026-07-14")
    invalid_date = client.get("/api/data/mootdx/xdxr-quality?start_date=2026-07-xx")

    assert invalid_status.status_code == 400
    assert invalid_range.status_code == 400
    assert invalid_date.status_code == 400
    assert service.quality_calls == []


def test_xdxr_quality_detail_api_forwards_audit_filter_and_returns_404() -> None:
    service = _FakeMootdxQuality()
    client = _client(service)

    detail = client.get("/api/data/mootdx/xdxr-quality/runs/run-1?status=empty&limit=3")
    missing = client.get("/api/data/mootdx/xdxr-quality/runs/missing")

    assert detail.status_code == 200
    assert detail.json() == {"item": {"run_id": "run-1", "items": []}}
    assert service.detail_calls == [
        {"run_id": "run-1", "status": "empty", "limit": 3},
        {"run_id": "missing", "status": None, "limit": 500},
    ]
    assert missing.status_code == 404


def test_xdxr_quality_detail_api_rejects_invalid_audit_status() -> None:
    service = _FakeMootdxQuality()

    response = _client(service).get("/api/data/mootdx/xdxr-quality/runs/run-1?status=failed")

    assert response.status_code == 400
    assert service.detail_calls == []
