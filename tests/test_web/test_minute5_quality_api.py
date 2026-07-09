from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


class FakeMinute5QualityService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def summary(self) -> dict[str, object]:
        self.calls.append(("summary", {}))
        return {
            "table": "minute5_kline",
            "rows": 120,
            "symbols": 3,
            "range": {"start": "2026-07-01 09:35:00", "end": "2026-07-08 11:25:00"},
            "latest": {"raw_bucket": "2026-07-08 11:25:00", "raw_symbols": 2, "complete_bucket": "2026-07-08 11:20:00"},
            "issues": {"duplicate_groups": 0, "extra_rows": 0, "invalid_ohlc": 1, "non_5m_boundary": 0, "non_market_session": 0},
            "status": "warning",
        }

    def days(self, start: date | None = None, end: date | None = None, limit: int = 90) -> dict[str, object]:
        self.calls.append(("days", {"start": start, "end": end, "limit": limit}))
        return {"items": [{"trade_date": "2026-07-08", "rows": 96, "symbols": 2, "buckets": 48, "status": "ok"}]}

    def buckets(self, trade_date: date) -> dict[str, object]:
        self.calls.append(("buckets", {"trade_date": trade_date}))
        return {"trade_date": str(trade_date), "items": [{"datetime": "2026-07-08 11:20:00", "symbols": 2, "status": "ok"}]}

    def sample(self, trade_date: date | None = None, mode: str = "random", limit: int = 20) -> dict[str, object]:
        self.calls.append(("sample", {"trade_date": trade_date, "mode": mode, "limit": limit}))
        return {"mode": mode, "items": [{"symbol": "000001", "name": "平安银行", "bars": 48, "invalid_rows": 0}]}

    def symbol_bars(self, symbol: str, trade_date: date) -> dict[str, object]:
        self.calls.append(("symbol_bars", {"symbol": symbol, "trade_date": trade_date}))
        return {"symbol": "000001", "trade_date": str(trade_date), "items": [{"datetime": "2026-07-08 09:35:00", "close": 10.0}]}

    def missing_symbols(self, trade_date: date, bucket: str | None = None, limit: int = 200) -> dict[str, object]:
        self.calls.append(("missing_symbols", {"trade_date": trade_date, "bucket": bucket, "limit": limit}))
        return {"trade_date": str(trade_date), "items": [{"symbol": "000002", "missing_bars": 2}, {"symbol": "000003", "missing_bars": 48}]}

    def invalid_rows(self, trade_date: date, limit: int = 200) -> dict[str, object]:
        self.calls.append(("invalid_rows", {"trade_date": trade_date, "limit": limit}))
        return {"trade_date": str(trade_date), "items": [{"symbol": "000001", "reason": "high_invalid"}]}

    def delete_symbol_day_rows(self, trade_date: date, symbols: list[str]) -> dict[str, object]:
        self.calls.append(("delete_symbol_day_rows", {"trade_date": trade_date, "symbols": symbols}))
        return {"deleted_symbols": symbols, "trade_date": str(trade_date)}

    def backfill_plan(self, start: date, end: date, limit: int = 90) -> dict[str, object]:
        self.calls.append(("backfill_plan", {"start": start, "end": end, "limit": limit}))
        return {"range": {"start": str(start), "end": str(end)}, "items": [{"trade_date": "2026-07-08", "status": "needs_backfill"}]}


def test_minute5_quality_api_exposes_summary_days_buckets_sample_and_symbol_bars(tmp_path) -> None:
    service = FakeMinute5QualityService()
    app = create_app(db_path=tmp_path / "jobs.json", minute5_quality_service=service)
    client = TestClient(app)

    assert client.get("/api/data/minute5-quality/summary").json()["latest"]["complete_bucket"] == "2026-07-08 11:20:00"
    assert client.get("/api/data/minute5-quality/days?start=2026-07-01&end=2026-07-08&limit=5").json()["items"][0]["buckets"] == 48
    assert client.get("/api/data/minute5-quality/buckets?trade_date=2026-07-08").json()["items"][0]["symbols"] == 2
    assert client.get("/api/data/minute5-quality/sample?trade_date=2026-07-08&mode=low_coverage&limit=3").json()["items"][0]["symbol"] == "000001"
    assert client.get("/api/data/minute5-quality/symbol-bars?symbol=000001&trade_date=2026-07-08").json()["items"][0]["close"] == 10.0
    assert client.get("/api/data/minute5-quality/missing-symbols?trade_date=2026-07-08&bucket=14:55&limit=10").json()["items"][0]["missing_bars"] == 2
    assert client.get("/api/data/minute5-quality/invalid-rows?trade_date=2026-07-08&limit=10").json()["items"][0]["reason"] == "high_invalid"
    assert client.get("/api/data/minute5-quality/backfill-plan?start=2026-07-07&end=2026-07-08&limit=5").json()["items"][0]["status"] == "needs_backfill"

    assert service.calls == [
        ("summary", {}),
        ("days", {"start": date(2026, 7, 1), "end": date(2026, 7, 8), "limit": 5}),
        ("buckets", {"trade_date": date(2026, 7, 8)}),
        ("sample", {"trade_date": date(2026, 7, 8), "mode": "low_coverage", "limit": 3}),
        ("symbol_bars", {"symbol": "000001", "trade_date": date(2026, 7, 8)}),
        ("missing_symbols", {"trade_date": date(2026, 7, 8), "bucket": "14:55", "limit": 10}),
        ("invalid_rows", {"trade_date": date(2026, 7, 8), "limit": 10}),
        ("backfill_plan", {"start": date(2026, 7, 7), "end": date(2026, 7, 8), "limit": 5}),
    ]


def test_minute5_quality_invalid_repair_runs_inline_delete_and_refetch_job(tmp_path) -> None:
    service = FakeMinute5QualityService()
    repair_calls = []

    def fake_repair(start, end, limit, symbols=None, include_st=False, progress=None):
        repair_calls.append({"start": start, "end": end, "limit": limit, "symbols": symbols, "include_st": include_st})
        if progress:
            progress(80, "fetching", "重新拉取异常分钟线")
        return {"success": len(symbols or []), "inserted_rows": 48}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        run_jobs_inline=True,
        minute5_quality_service=service,
        minute5_invalid_repair_runner=fake_repair,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/minute5-quality/repair-invalid",
        json={"trade_date": "2026-07-08", "mode": "delete_and_refetch"},
    )

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["kind"] == "minute5_invalid_repair"
    assert job["status"] == "success"
    assert job["result"]["symbols"] == ["000001"]
    assert job["result"]["delete"]["deleted_symbols"] == ["000001"]
    assert repair_calls == [{"start": date(2026, 7, 8), "end": date(2026, 7, 8), "limit": 0, "symbols": ["000001"], "include_st": True}]
    assert service.calls[-3:] == [
        ("invalid_rows", {"trade_date": date(2026, 7, 8), "limit": 1000}),
        ("delete_symbol_day_rows", {"trade_date": date(2026, 7, 8), "symbols": ["000001"]}),
        ("invalid_rows", {"trade_date": date(2026, 7, 8), "limit": 1000}),
    ]


def test_minute5_quality_missing_repair_runs_inline_history_backfill_job(tmp_path) -> None:
    service = FakeMinute5QualityService()
    repair_calls = []

    def fake_repair(start, end, limit, symbols=None, include_st=False, progress=None):
        repair_calls.append({"start": start, "end": end, "limit": limit, "symbols": symbols, "include_st": include_st})
        if progress:
            progress(70, "fetching", "回补缺口分钟线")
        return {"target_symbols": len(symbols or []), "inserted_rows": 96}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        run_jobs_inline=True,
        minute5_quality_service=service,
        minute5_invalid_repair_runner=fake_repair,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/minute5-quality/repair-missing",
        json={"trade_date": "2026-07-08", "limit": 50},
    )

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["kind"] == "minute5_missing_repair"
    assert job["status"] == "success"
    assert job["result"]["symbols"] == ["000002", "000003"]
    assert repair_calls == [{"start": date(2026, 7, 8), "end": date(2026, 7, 8), "limit": 0, "symbols": ["000002", "000003"], "include_st": True}]
