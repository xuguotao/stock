from __future__ import annotations

from datetime import date
from time import sleep

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.minute5_monitor import _monitor_wait_seconds


def test_minute5_monitor_subtracts_cycle_duration_from_wait() -> None:
    assert _monitor_wait_seconds(interval_seconds=60, duration_seconds=12.5) == 47.5
    assert _monitor_wait_seconds(interval_seconds=60, duration_seconds=70) == 1


def test_minute5_monitor_start_status_and_stop(tmp_path) -> None:
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        kwargs["progress"](55, "fetching", "增量更新分钟线")
        return {
            "trade_date": kwargs["trade_date"].isoformat(),
            "target_datetime": f"{kwargs['trade_date'].isoformat()} 14:10:00",
            "target_symbols": 2,
            "skipped": 1,
            "success": 1,
            "failed": 0,
            "inserted_rows": 24,
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        run_jobs_inline=True,
        minute5_sync_runner=fake_sync,
        minute5_monitor_session_checker=lambda trade_date: (True, "market_open"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/minute5-monitor/start",
        json={"trade_date": "2026-06-12", "limit": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is True
    assert payload["started_count"] == 1
    assert payload["cycle_count"] == 1
    assert payload["last_result"]["inserted_rows"] == 24
    assert calls[0]["trade_date"] == date(2026, 6, 12)
    assert calls[0]["limit"] == 0
    assert calls[0]["max_fetch_symbols"] == 0
    assert payload["config"]["interval_seconds"] == 60
    assert payload["config"]["max_fetch_symbols"] == 0

    status = client.get("/api/data/minute5-monitor").json()
    assert status["running"] is True
    assert status["last_progress"]["message"] == "增量更新分钟线"

    stopped = client.post("/api/data/minute5-monitor/stop").json()
    assert stopped["running"] is False


def test_minute5_monitor_skips_outside_market_hours(tmp_path) -> None:
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return {"inserted_rows": 1}

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        run_jobs_inline=True,
        minute5_sync_runner=fake_sync,
        minute5_monitor_session_checker=lambda trade_date: (False, "outside_market_hours"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/minute5-monitor/start",
        json={"trade_date": "2026-06-12", "interval_seconds": 60, "limit": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is True
    assert payload["started_count"] == 1
    assert payload["cycle_count"] == 0
    assert payload["skip_count"] == 1
    assert payload["last_result"]["skipped"] is True
    assert payload["last_result"]["skip_reason"] == "outside_market_hours"
    assert payload["last_progress"]["stage"] == "skipped"
    assert "非交易时段" in payload["last_progress"]["message"]
    assert calls == []


def test_minute5_monitor_auto_starts_on_app_startup_and_skips_when_closed(tmp_path) -> None:
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return {"inserted_rows": 1}

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        minute5_sync_runner=fake_sync,
        minute5_monitor_session_checker=lambda trade_date: (False, "outside_market_hours"),
        auto_start_minute5_monitor=True,
        minute5_auto_interval_seconds=30,
    )

    with TestClient(app) as client:
        for _ in range(20):
            status = client.get("/api/data/minute5-monitor").json()
            if status["skip_count"]:
                break
            sleep(0.05)

        assert status["running"] is True
        assert status["mode"] == "auto"
        assert status["started_count"] >= 1
        assert status["cycle_count"] == 0
        assert status["skip_count"] >= 1
        assert status["session"]["open"] is False
        assert status["session"]["reason"] == "outside_market_hours"
        assert status["next_run_at"] is not None
        assert calls == []
