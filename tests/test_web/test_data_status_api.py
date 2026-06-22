from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi.testclient import TestClient

from src.web.backend.app import _resolve_trade_date, create_app
from src.web.backend.data_status import inspect_stock_database


def _create_stock_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table stocks (symbol text, name text, industry text, market text, list_date text, updated_at text)"
    )
    conn.execute("create table trade_calendar (date text, is_open integer)")
    conn.execute(
        "create table daily_kline (symbol text, date text, open real, high real, low real, close real, volume real, amount real, amplitude real, pct_change real, change real, turnover real)"
    )
    conn.execute(
        "create table minute5_kline (symbol text, datetime text, open real, high real, low real, close real, volume real, amount real)"
    )
    conn.executemany(
        "insert into stocks values (?, ?, ?, ?, ?, ?)",
        [
            ("000001", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-12 15:10:00"),
            ("000004", "*ST国华", "软件", "SZ", "1990-12-01", "2026-06-12 15:10:00"),
        ],
    )
    conn.executemany(
        "insert into trade_calendar values (?, ?)",
        [("2026-06-12", 1), ("2026-06-13", 0)],
    )
    conn.executemany(
        "insert into daily_kline values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("000001", "2026-06-11", 10, 10.5, 9.9, 10.2, 1000, 10200, 0, 0, 0, 0),
            ("000001", "2026-06-12", 10.2, 10.8, 10.1, 10.6, 1200, 12600, 0, 0, 0, 0),
            ("000004", "2026-06-12", 5, 5.1, 4.9, 5.0, 800, 4000, 0, 0, 0, 0),
        ],
    )
    conn.executemany(
        "insert into minute5_kline values (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("000001", "2026-06-12 14:55:00", 10.5, 10.7, 10.4, 10.6, 100, 1060),
            ("000001", "2026-06-12 15:00:00", 10.6, 10.8, 10.5, 10.7, 120, 1284),
        ],
    )
    conn.commit()
    conn.close()


def test_data_status_api_returns_stock_db_coverage(tmp_path) -> None:
    stock_db = tmp_path / "stock.db"
    _create_stock_db(stock_db)
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        data_status_runner=lambda: inspect_stock_database(stock_db),
    )
    client = TestClient(app)

    response = client.get("/api/data/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["exists"] is True
    assert payload["database"]["path"] == str(stock_db)
    assert payload["stock_summary"] == {
        "stock_count": 2,
        "non_st_stock_count": 1,
        "st_stock_count": 1,
    }
    assert payload["tables"]["daily_kline"]["row_count"] == 3
    assert payload["tables"]["daily_kline"]["date_range"] == {
        "start": "2026-06-11",
        "end": "2026-06-12",
    }
    assert payload["tables"]["daily_kline"]["symbol_count"] == 2
    assert payload["tables"]["minute5_kline"]["date_range"]["end"] == "2026-06-12 15:00:00"
    assert payload["health"]["daily_latest_date"] == "2026-06-12"
    assert payload["health"]["minute5_latest_datetime"] == "2026-06-12 15:00:00"


def test_data_status_api_reports_missing_database(tmp_path) -> None:
    stock_db = tmp_path / "missing.db"
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        data_status_runner=lambda: inspect_stock_database(stock_db),
    )
    client = TestClient(app)

    response = client.get("/api/data/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["exists"] is False
    assert payload["tables"] == {}
    assert payload["health"]["status"] == "missing_database"


def test_data_sync_api_runs_inline_job_and_returns_refreshed_status(tmp_path) -> None:
    stock_db = tmp_path / "stock.db"
    _create_stock_db(stock_db)

    def fake_sync(remote, dest, backup, progress=None):
        if progress:
            progress(40, "copying", "同步 stock.db")
        assert remote == "host:/stock.db"
        assert dest == stock_db
        assert backup is True
        return {
            "remote": remote,
            "dest": str(dest),
            "size_bytes": stock_db.stat().st_size,
            "integrity": "ok",
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        run_jobs_inline=True,
        stock_db_sync_runner=fake_sync,
        data_status_runner=lambda: inspect_stock_database(stock_db),
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/sync-stock-db",
        json={"remote": "host:/stock.db", "backup": True},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "stock_db_sync"
    assert job["status"] == "success"
    assert job["progress"] == {"percent": 100, "stage": "completed", "message": "旧 Stock DB 同步完成"}
    assert job["result"]["legacy"] is True
    assert job["result"]["sync"]["integrity"] == "ok"
    assert job["result"]["status"]["stock_summary"]["stock_count"] == 2


def test_minute5_sync_api_runs_inline_job_and_returns_refreshed_status(tmp_path) -> None:
    stock_db = tmp_path / "stock.db"
    _create_stock_db(stock_db)

    def fake_sync(db_path, trade_date, limit, symbols=None, source=None, include_st=False, progress=None):
        if progress:
            progress(65, "fetching", "更新 5m 分钟线")
        assert db_path == stock_db
        assert trade_date.isoformat() == "2026-06-12"
        assert limit == 0
        assert symbols is None
        assert include_st is False
        return {
            "trade_date": "2026-06-12",
            "target_symbols": 1,
            "success": 1,
            "failed": 0,
            "inserted_rows": 2,
            "coverage_after": {"symbol_count": 1},
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        run_jobs_inline=True,
        minute5_sync_runner=fake_sync,
        data_status_runner=lambda: inspect_stock_database(stock_db),
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/sync-minute5",
        json={"trade_date": "2026-06-12", "limit": 0},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "minute5_sync"
    assert job["status"] == "success"
    assert job["progress"] == {"percent": 100, "stage": "completed", "message": "5m 分钟线更新完成"}
    assert job["result"]["sync"]["success"] == 1
    assert job["result"]["status"]["health"]["minute5_symbol_count"] == 1


def test_data_health_repair_plan_api_returns_actionable_warnings(tmp_path) -> None:
    status = {
        "quality": {
            "status": "warning",
            "issues": ["minute5_kline_missing_1_symbols"],
            "minute5": {"latest_datetime": "2026-06-12 14:55:00", "missing_symbols": 1},
            "daily": {"latest_date": "2026-06-12", "missing_symbols": 0},
            "quote_snapshots": {"status": "ok", "issues": []},
            "scheduled_checks": {"completeness_30d": {"affected_symbols": 0}},
        }
    }
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        data_status_runner=lambda: status,
    )
    client = TestClient(app)

    response = client.get("/api/data/health-repair-plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["actions"][0]["key"] == "minute5_sync"
    assert payload["actions"][0]["trade_date"] == "2026-06-12"


def test_data_reliability_api_returns_dashboard_report(tmp_path) -> None:
    status = {
        "health": {"daily_latest_date": "2026-06-12"},
        "quality": {
            "status": "warning",
            "issues": ["minute5_kline_missing_1_symbols"],
            "daily": {"status": "ok", "latest_date": "2026-06-12", "missing_symbols": 0},
            "minute5": {
                "status": "warning",
                "latest_datetime": "2026-06-12 14:55:00",
                "missing_symbols": 1,
                "covered_symbols": 1,
                "expected_symbols": 2,
                "coverage_ratio": 0.5,
            },
            "quote_snapshots": {"status": "ok", "issues": []},
            "scheduled_checks": {"completeness_30d": {"affected_symbols": 0}},
        },
    }
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        data_status_runner=lambda: status,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    response = client.get("/api/data/reliability")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["rows"] == 4
    assert payload["data_status"] == status
    assert payload["repair_plan"]["summary"]["auto_repair_count"] >= 1
    assert any(action["key"] == "minute5_sync" for action in payload["repair_plan"]["actions"])
    assert {row["key"] for row in payload["rows"]} == {"daily", "minute5", "quote_snapshots", "health_checks"}
    minute5 = next(row for row in payload["rows"] if row["key"] == "minute5")
    assert minute5["health"] == "warning"
    assert minute5["coverage"] == "1 / 2（50.00%）"


def test_data_health_repair_api_runs_inline_auto_repairs(tmp_path) -> None:
    stock_db = tmp_path / "stock.db"
    _create_stock_db(stock_db)
    before_status = {
        "quality": {
            "status": "warning",
            "issues": [
                "daily_kline_missing_1_symbols",
                "minute5_kline_missing_1_symbols",
                "stock_quote_snapshots_missing_1_symbols",
            ],
            "daily": {
                "latest_date": "2026-06-12",
                "missing_symbols": 1,
                "missing_samples": [{"symbol": "000001.SZ", "name": "平安银行"}],
            },
            "minute5": {
                "latest_datetime": "2026-06-12 14:55:00",
                "missing_symbols": 1,
                "missing_samples": [{"symbol": "000001.SZ", "name": "平安银行"}],
            },
            "quote_snapshots": {"status": "warning", "issues": ["stock_quote_snapshots_missing_1_symbols"]},
            "scheduled_checks": {"completeness_30d": {"affected_symbols": 0}},
        }
    }
    after_status = {
        "quality": {
            "status": "ok",
            "issues": [],
            "daily": {"latest_date": "2026-06-12", "missing_symbols": 0},
            "minute5": {"latest_datetime": "2026-06-12 14:55:00", "missing_symbols": 0},
            "quote_snapshots": {"status": "ok", "issues": []},
            "scheduled_checks": {"completeness_30d": {"affected_symbols": 0}},
        }
    }
    statuses = [before_status, after_status]
    calls = []

    def fake_status():
        return statuses.pop(0) if statuses else after_status

    def fake_minute5(db_path, trade_date, limit, symbols=None, include_st=False, progress=None):
        calls.append(("minute5", trade_date.isoformat(), symbols))
        return {"success": 1}

    def fake_daily_repair(trade_date):
        calls.append(("daily", trade_date.isoformat()))
        return {"inserted_rows": 1}

    def fake_quote_snapshot(**kwargs):
        calls.append(("quote", kwargs["symbols"], kwargs["limit"]))
        return {"inserted_rows": 1}

    def fake_quality_snapshot(quality):
        calls.append(("snapshot", quality["status"]))
        return {"inserted_rows": 4}

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        run_jobs_inline=True,
        data_status_runner=fake_status,
        minute5_sync_runner=fake_minute5,
        quote_snapshot_sync_runner=fake_quote_snapshot,
        daily_repair_runner=fake_daily_repair,
        quality_snapshot_writer=fake_quality_snapshot,
    )
    client = TestClient(app)

    response = client.post("/api/data/health-repair", json={})
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert calls == [
        ("minute5", "2026-06-12", ["000001.SZ"]),
        ("daily", "2026-06-12"),
        ("quote", None, 0),
        ("snapshot", "ok"),
    ]
    assert job["result"]["after_plan"]["status"] == "ok"


def test_daily_maintenance_runs_sync_retry_and_strategy_review(tmp_path) -> None:
    stock_db = tmp_path / "stock.db"
    _create_stock_db(stock_db)
    status_calls = [
        {
            "database": {"exists": True, "type": "clickhouse", "size_bytes": 0},
            "stock_summary": {"stock_count": 2, "non_st_stock_count": 2, "st_stock_count": 0},
            "health": {
                "status": "ok",
                "daily_latest_date": "2026-06-12",
                "daily_symbol_count": 2,
                "minute5_latest_datetime": "2026-06-11 15:00:00",
                "minute5_symbol_count": 1,
            },
            "tables": {},
        },
        {
            "database": {"exists": True, "type": "clickhouse", "size_bytes": 0},
            "stock_summary": {"stock_count": 2, "non_st_stock_count": 2, "st_stock_count": 0},
            "health": {
                "status": "ok",
                "daily_latest_date": "2026-06-12",
                "daily_symbol_count": 2,
                "minute5_latest_datetime": "2026-06-12 15:00:00",
                "minute5_symbol_count": 2,
            },
            "tables": {},
        },
    ]
    sync_calls = []
    repair_calls = []
    index_calls = []
    quality_calls = []

    def fake_status():
        return status_calls[min(len(sync_calls), 1)]

    def fake_sync(db_path, trade_date, limit, symbols=None, source=None, include_st=False, progress=None):
        sync_calls.append({"trade_date": trade_date.isoformat(), "limit": limit, "symbols": symbols})
        if progress:
            progress(50, "fetching", "更新 5m 分钟线")
        if symbols:
            return {
                "trade_date": trade_date.isoformat(),
                "target_symbols": len(symbols),
                "success": len(symbols),
                "no_data": 0,
                "no_data_symbols": [],
                "failed": 0,
                "inserted_rows": 48,
            }
        return {
            "trade_date": trade_date.isoformat(),
            "target_symbols": 2,
            "success": 1,
            "no_data": 1,
            "no_data_symbols": ["000002.SZ"],
            "failed": 0,
            "inserted_rows": 48,
        }

    def fake_tail_runner(payload, progress=None):
        if progress:
            progress(95, "strategy_review", "复核尾盘策略")
        assert payload.trade_date.isoformat() == "2026-06-12"
        assert payload.ignore_session is True
        return {
            "mode": "selection",
            "trade_date": "2026-06-12",
            "scanned_count": 2,
            "selected_count": 1,
            "ranked_signals": [{"symbol": "000001.SZ"}],
            "selections": [{"symbol": "000001.SZ"}],
            "diagnostics": {"empty_reason": ""},
        }

    def fake_daily_repair(*, trade_date):
        repair_calls.append(trade_date.isoformat())
        return {"trade_date": trade_date.isoformat(), "inserted_rows": 1}

    def fake_index_sync(*, start, end):
        index_calls.append({"start": start.isoformat(), "end": end.isoformat()})
        return {"start": start.isoformat(), "end": end.isoformat(), "inserted_rows": 2, "failures": []}

    def fake_quality_snapshot(*, quality=None):
        quality_calls.append(quality)
        return {"checked_at": "2026-06-12 16:00:00", "rows": 4}

    class FakeSignalRepository:
        def save_selection_result(self, *, job_id, result):
            return {"trade_date": result["trade_date"], "signal_count": 1, "selected_count": 1}

        def compute_and_save_outcomes(self, *, signal_date, symbols):
            return {"signal_date": signal_date.isoformat(), "outcome_count": 0, "missing_symbols": symbols}

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        run_jobs_inline=True,
        minute5_sync_runner=fake_sync,
        data_status_runner=fake_status,
        tail_live_runner=fake_tail_runner,
        tail_signal_repository=FakeSignalRepository(),
        daily_repair_runner=fake_daily_repair,
        index_daily_sync_runner=fake_index_sync,
        quality_snapshot_writer=fake_quality_snapshot,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/daily-maintenance",
        json={"trade_date": "2026-06-12", "retry_no_data": True, "run_strategy_review": True, "strategy_limit": 2},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "daily_maintenance"
    assert job["status"] == "success"
    assert [call["symbols"] for call in sync_calls] == [None, ["000002.SZ"]]
    assert job["result"]["trade_date"] == "2026-06-12"
    assert job["result"]["retry"]["success"] == 1
    assert repair_calls == ["2026-06-12"]
    assert index_calls == [{"start": "2026-06-06", "end": "2026-06-12"}]
    assert len(quality_calls) == 1
    assert job["result"]["daily_repair"] == {"trade_date": "2026-06-12", "inserted_rows": 1}
    assert job["result"]["index_daily"] == {
        "start": "2026-06-06",
        "end": "2026-06-12",
        "inserted_rows": 2,
        "failures": [],
    }
    assert job["result"]["health_snapshot"] == {"checked_at": "2026-06-12 16:00:00", "rows": 4}
    assert job["result"]["verification"]["minute5_complete_symbols"] == 2
    assert job["result"]["strategy_review"] == {
        "mode": "selection",
        "scanned_count": 2,
        "ranked_count": 1,
        "selected_count": 1,
        "empty_reason": "",
        "persistence": {
            "signals": {"trade_date": "2026-06-12", "signal_count": 1, "selected_count": 1},
            "outcomes": {"signal_date": "2026-06-12", "outcome_count": 0, "missing_symbols": ["000001.SZ"]},
        },
    }


def test_daily_maintenance_prefers_latest_minute5_date_when_daily_is_stale(tmp_path) -> None:
    stock_db = tmp_path / "stock.db"
    _create_stock_db(stock_db)
    status = {
        "database": {"exists": True, "type": "clickhouse", "size_bytes": 0},
        "stock_summary": {"stock_count": 2, "non_st_stock_count": 2, "st_stock_count": 0},
        "health": {
            "status": "ok",
            "daily_latest_date": "2026-06-18",
            "daily_symbol_count": 2,
            "minute5_latest_datetime": "2026-06-22 15:00:00",
            "minute5_symbol_count": 2,
        },
        "tables": {},
    }
    sync_dates = []
    repair_dates = []

    def fake_sync(db_path, trade_date, limit, symbols=None, source=None, include_st=False, progress=None):
        sync_dates.append(trade_date.isoformat())
        return {
            "trade_date": trade_date.isoformat(),
            "target_symbols": 2,
            "success": 2,
            "no_data": 0,
            "no_data_symbols": [],
            "failed": 0,
            "inserted_rows": 0,
        }

    def fake_daily_repair(*, trade_date):
        repair_dates.append(trade_date.isoformat())
        return {"trade_date": trade_date.isoformat(), "inserted_rows": 2}

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=stock_db,
        run_jobs_inline=True,
        minute5_sync_runner=fake_sync,
        data_status_runner=lambda: status,
        daily_repair_runner=fake_daily_repair,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
    )
    client = TestClient(app)

    response = client.post(
        "/api/data/daily-maintenance",
        json={"retry_no_data": True, "run_strategy_review": False},
    )

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "success"
    assert job["result"]["trade_date"] == "2026-06-22"
    assert sync_dates == ["2026-06-22"]
    assert repair_dates == ["2026-06-22"]


def test_resolve_trade_date_uses_current_trading_day_after_post_close() -> None:
    status = {
        "health": {
            "daily_latest_date": "2026-06-18",
            "minute5_latest_datetime": "2026-06-18 15:00:00",
        }
    }

    assert _resolve_trade_date(status, now=datetime(2026, 6, 22, 15, 10)) == datetime(2026, 6, 22).date()


def test_resolve_trade_date_uses_previous_trading_day_before_post_close() -> None:
    status = {
        "health": {
            "daily_latest_date": "2026-06-18",
            "minute5_latest_datetime": "2026-06-22 14:55:00",
        }
    }

    assert _resolve_trade_date(status, now=datetime(2026, 6, 22, 14, 50)) == datetime(2026, 6, 18).date()


def test_resolve_trade_date_uses_previous_trading_day_on_non_trading_day() -> None:
    status = {
        "health": {
            "daily_latest_date": "2026-06-18",
            "minute5_latest_datetime": "2026-06-18 15:00:00",
        }
    }

    assert _resolve_trade_date(status, now=datetime(2026, 6, 20, 16, 0)) == datetime(2026, 6, 18).date()


def test_data_ops_scheduler_endpoint_can_run_maintenance_once(tmp_path) -> None:
    maintenance_calls = []

    def fake_auto_maintenance():
        maintenance_calls.append("run")
        return {"job_id": "auto-1", "status": "success"}

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        run_jobs_inline=True,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
        auto_start_data_ops_scheduler=False,
        data_ops_maintenance_runner=fake_auto_maintenance,
    )
    client = TestClient(app)

    initial = client.get("/api/data/ops-scheduler").json()
    assert initial["running"] is False
    assert initial["tasks"]["post_close_maintenance"]["enabled"] is True

    response = client.post("/api/data/ops-scheduler/run-once")

    assert response.status_code == 200
    payload = response.json()
    assert payload["last_result"] == {"job_id": "auto-1", "status": "success"}
    assert maintenance_calls == ["run"]


def test_clickhouse_dataset_build_api_runs_inline_job_and_lists_dataset(tmp_path) -> None:
    data_root = tmp_path / "research"

    def fake_builder(start, end, output_path, manifest_path=None, symbols=None, limit=0, client=None):
        import pandas as pd

        pd.DataFrame([
            {
                "date": "2026-06-12",
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "close": 10.2,
                "volume": 1000.0,
                "amount": 10200.0,
                "adjusted_close": 10.2,
            }
        ]).to_parquet(output_path, index=False)
        manifest = {
            "dataset_path": str(output_path),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "symbols": ["000001.SZ"],
            "missing_symbols": [],
            "symbol_count": 1,
            "row_count": 1,
            "source": "clickhouse",
            "built_at": "2026-06-15T10:00:00",
        }
        Path(manifest_path).write_text("{}", encoding="utf-8")
        return manifest

    from pathlib import Path

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        dataset_root=data_root,
        run_jobs_inline=True,
        clickhouse_dataset_builder=fake_builder,
    )
    client = TestClient(app)

    response = client.post(
        "/api/datasets/build-clickhouse",
        json={
            "start": "2026-06-12",
            "end": "2026-06-12",
            "name": "daily_clickhouse_test",
            "symbols": ["000001.SZ"],
        },
    )

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["kind"] == "dataset_build"
    assert job["status"] == "success"
    assert job["result"]["manifest"]["source"] == "clickhouse"

    datasets = client.get("/api/datasets").json()["items"]
    assert [dataset["id"] for dataset in datasets] == ["daily_clickhouse_test.parquet"]
