from __future__ import annotations

from time import sleep

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_quote_snapshot_monitor_auto_starts_and_skips_when_market_closed(tmp_path) -> None:
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return {"inserted_rows": 1}

    app = create_app(
        db_path=tmp_path / "jobs.json",
        quote_snapshot_sync_runner=fake_sync,
        quote_snapshot_session_checker=lambda: (False, "outside_market_hours"),
        auto_start_quote_snapshot_monitor=True,
        auto_start_minute5_monitor=False,
    )

    with TestClient(app) as client:
        for _ in range(20):
            status = client.get("/api/data/quote-snapshot-monitor").json()
            if status["skip_count"]:
                break
            sleep(0.05)

        assert status["running"] is True
        assert status["mode"] == "auto"
        assert status["config"]["interval_seconds"] == 10
        assert status["config"]["chunk_size"] == 850
        assert status["session"]["open"] is False
        assert status["session"]["reason"] == "outside_market_hours"
        assert status["skip_count"] >= 1
        assert status["cycle_count"] == 0
        assert status["next_run_at"] is not None
        assert calls == []


def test_quote_snapshot_monitor_can_run_inline_when_session_open(tmp_path) -> None:
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        kwargs["progress"](70, "fetching", "拉取行情快照")
        return {
            "snapshot_at": "2026-06-16 14:30:05",
            "target_symbols": 2,
            "quote_rows": 2,
            "inserted_rows": 2,
            "failed_chunks": 0,
            "latest_quote_time": "2026-06-16 14:30:00",
            "duration_seconds": 6.5,
            "timings": {"total_seconds": 6.5, "fetch_seconds": 4.0, "write_seconds": 1.5, "rollup_seconds": 1.0},
        }

    app = create_app(
        db_path=tmp_path / "jobs.json",
        quote_snapshot_sync_runner=fake_sync,
        quote_snapshot_session_checker=lambda: (True, "market_open"),
        auto_start_quote_snapshot_monitor=False,
        auto_start_minute5_monitor=False,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/quote-snapshot-monitor/start",
        json={"interval_seconds": 30, "limit": 100, "include_st": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is True
    assert payload["mode"] == "manual"
    assert payload["cycle_count"] == 1
    assert payload["last_result"]["inserted_rows"] == 2
    assert calls[0]["limit"] == 100
    assert calls[0]["include_st"] is False
    assert calls[0]["chunk_size"] == 850
    assert calls[0]["timeout_seconds"] == 8
    assert payload["timeout_count"] == 0
    assert payload["effective_chunk_size"] == 850
    assert payload["last_cycle_duration_seconds"] >= 0
    assert payload["last_result"]["timings"]["total_seconds"] == 6.5


def test_quote_snapshot_monitor_records_slow_cycle_and_reduces_chunk_size(tmp_path) -> None:
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return {
            "inserted_rows": 2,
            "duration_seconds": 12.0,
            "timings": {"total_seconds": 12.0, "fetch_seconds": 9.0, "write_seconds": 2.0, "rollup_seconds": 1.0},
        }

    app = create_app(
        db_path=tmp_path / "jobs.json",
        quote_snapshot_sync_runner=fake_sync,
        quote_snapshot_session_checker=lambda: (True, "market_open"),
        auto_start_quote_snapshot_monitor=False,
        auto_start_minute5_monitor=False,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/quote-snapshot-monitor/start",
        json={"interval_seconds": 10, "limit": 100, "include_st": False, "chunk_size": 850, "timeout_seconds": 8},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["timeout_count"] == 1
    assert payload["last_result"]["timeout"] is True
    assert payload["last_result"]["deadline_seconds"] == 8
    assert payload["last_result"]["overrun_seconds"] == 2.0
    assert payload["effective_chunk_size"] < 850
    assert calls[0]["chunk_size"] == 850
