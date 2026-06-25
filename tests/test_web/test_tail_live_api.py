from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from src.strategy.scanner import TailSessionSignal
from src.web.backend.app import create_app
from src.web.backend.tail_live import TailLiveSelectionRequest, _final_trade_candidates, _ranked_signal_rows, run_tail_live_selection


def test_tail_live_selection_api_runs_inline_job(tmp_path) -> None:
    class FakeSignalRepository:
        def __init__(self) -> None:
            self.saved = []
            self.outcomes = []

        def save_selection_result(self, *, job_id, result):
            self.saved.append((job_id, result))
            return {"trade_date": result["trade_date"], "signal_count": 1, "selected_count": 1}

        def compute_and_save_outcomes(self, *, signal_date, symbols):
            self.outcomes.append((signal_date, symbols))
            return {"signal_date": signal_date.isoformat(), "outcome_count": 0, "missing_symbols": symbols}

    repository = FakeSignalRepository()

    def fake_runner(
        payload: TailLiveSelectionRequest,
        progress=None,
    ) -> dict[str, Any]:
        if progress:
            progress(40, "scanning", "扫描尾盘信号")
        return {
            "trade_date": payload.trade_date.isoformat(),
            "scanned_count": 2,
            "candidate_count": 1,
            "confirmed_count": 1,
            "selected_count": 1,
            "selections": [
                {
                    "symbol": "000001.SZ",
                    "trade_date": payload.trade_date.isoformat(),
                    "strength": 0.9,
                    "last_price": 10.5,
                    "volume_ratio": 2.0,
                    "tail_return": 0.01,
                    "reason": "tail price-volume confirmation",
                }
            ],
            "files": {
                "json": "reports/tail_session/latest_selection.json",
                "csv": "reports/tail_session/latest_selection.csv",
                "report": "reports/tail_session/tail_session_2026-06-12.md",
            },
            "market_breadth": None,
            "diagnostics": {
                "empty_reason": None,
                "scan_universe_preview": ["000001.SZ", "600519.SH"],
                "has_intraday_data_count": None,
                "blocked_by_market_breadth": False,
            },
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        run_jobs_inline=True,
        tail_live_runner=fake_runner,
        tail_signal_repository=repository,
    )
    client = TestClient(app)

    response = client.post(
        "/api/tail-session/live-selection",
        json={
            "trade_date": "2026-06-12",
            "symbols": ["000001.SZ", "600519.SH"],
            "top_n": 1,
            "ignore_session": True,
            "auto_sync_minute5": False,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["kind"] == "tail_session_live_selection"
    assert job["status"] == "success"
    assert job["progress"] == {"percent": 100, "stage": "completed", "message": "今日尾盘选股完成"}
    assert job["result"]["selected_count"] == 1
    assert job["result"]["selections"][0]["symbol"] == "000001.SZ"
    assert job["result"]["files"]["csv"].endswith("latest_selection.csv")
    assert job["result"]["diagnostics"]["empty_reason"] is None
    assert job["result"]["persistence"] == {
        "signals": {"trade_date": "2026-06-12", "signal_count": 1, "selected_count": 1},
        "outcomes": {"signal_date": "2026-06-12", "outcome_count": 0, "missing_symbols": ["000001.SZ"]},
    }
    assert repository.saved[0][0] == payload["job_id"]
    assert repository.outcomes[0][1] == ["000001.SZ"]


def test_tail_signal_stats_api_returns_repository_metrics(tmp_path) -> None:
    class FakeSignalRepository:
        def signal_stats(self, *, start=None, end=None):
            return {
                "range": {"start": start.isoformat(), "end": end.isoformat()},
                "overall": {"count": 3, "win_count": 2, "win_rate": 2 / 3, "avg_open_return": 0.01, "avg_close_return": 0.02, "avg_max_return": 0.03, "avg_min_return": -0.01},
                "by_status": [],
                "by_layer": [],
                "by_filter_reason": [],
            }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        tail_signal_repository=FakeSignalRepository(),
    )
    client = TestClient(app)

    response = client.get("/api/tail-session/signal-stats?start=2026-06-01&end=2026-06-30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"]["count"] == 3
    assert payload["range"] == {"start": "2026-06-01", "end": "2026-06-30"}


def test_tail_signal_review_outcomes_api_can_compute_pending_dates(tmp_path) -> None:
    class FakeSignalRepository:
        def __init__(self) -> None:
            self.pending_args = None

        def compute_pending_selected_outcomes(self, *, start=None, end=None):
            self.pending_args = (start, end)
            return {
                "mode": "pending",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "date_count": 2,
                "outcome_count": 3,
                "missing_symbols": ["000001.SZ"],
                "dates": [],
            }

    repository = FakeSignalRepository()
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        tail_signal_repository=repository,
    )
    client = TestClient(app)

    response = client.post(
        "/api/tail-session/review-outcomes",
        json={"mode": "pending", "start": "2026-06-15", "end": "2026-06-23"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "pending"
    assert payload["date_count"] == 2
    assert payload["outcome_count"] == 3
    assert repository.pending_args[0].isoformat() == "2026-06-15"
    assert repository.pending_args[1].isoformat() == "2026-06-23"


def test_tail_signal_review_outcomes_api_requires_signal_date_for_single_date(tmp_path) -> None:
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        tail_signal_repository=object(),
    )
    client = TestClient(app)

    response = client.post("/api/tail-session/review-outcomes", json={})

    assert response.status_code == 400
    assert "signal_date is required" in response.json()["detail"]


def test_tail_live_selection_reports_chinese_session_error(monkeypatch) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return False

        def is_trading_day(self, trade_date) -> bool:
            return True

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())

    try:
        run_tail_live_selection(TailLiveSelectionRequest(trade_date="2026-06-12"))
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected session window validation to fail")

    assert "当前不在 14:30-15:00 尾盘窗口" in message
    assert "忽略时间窗口" in message


def test_tail_live_selection_defaults_to_expanded_scan_pool() -> None:
    request = TailLiveSelectionRequest(trade_date="2026-06-12")

    assert request.limit == 0
    assert request.universe == "default"
    assert request.auto_sync_minute5 is True
    assert request.liquidity_min_bars == 60
    assert request.top_n == 2


def test_tail_live_selection_job_defaults_to_snapshot_refresh_before_scanning(tmp_path) -> None:
    minute5_calls: list[dict[str, Any]] = []
    snapshot_calls: list[dict[str, Any]] = []

    class FakeSignalRepository:
        def save_selection_result(self, *, job_id, result):
            return {"trade_date": result["trade_date"], "signal_count": 0, "selected_count": 0}

        def compute_and_save_outcomes(self, *, signal_date, symbols):
            return {"signal_date": signal_date.isoformat(), "outcome_count": 0, "missing_symbols": symbols}

    def fake_minute5_runner(**kwargs):
        minute5_calls.append(kwargs)
        kwargs["progress"](100, "completed", "分钟线补齐完成")
        return {"inserted_rows": 12, "target_symbols": 2, "coverage_after": {"date_range": {"end": "2026-06-12 14:35:00"}}}

    def fake_snapshot_runner(**kwargs):
        snapshot_calls.append(kwargs)
        kwargs["progress"](100, "completed", "快照刷新完成")
        return {"inserted_rows": 2, "target_symbols": 2, "latest_snapshot_at": "2026-06-12 14:45:01"}

    def fake_tail_runner(payload: TailLiveSelectionRequest, progress=None) -> dict[str, Any]:
        assert snapshot_calls, "snapshot sync should run before strategy scan"
        assert not minute5_calls, "default mode should not run full-market minute5 sync"
        if progress:
            progress(80, "scanning", "扫描尾盘信号")
        return {
            "trade_date": payload.trade_date.isoformat(),
            "scanned_count": 2,
            "candidate_count": 0,
            "confirmed_count": 0,
            "selected_count": 0,
            "selections": [],
            "files": {"json": "x", "csv": "x", "report": "x"},
            "market_breadth": None,
            "diagnostics": {"empty_reason": None},
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        run_jobs_inline=True,
        minute5_sync_runner=fake_minute5_runner,
        quote_snapshot_sync_runner=fake_snapshot_runner,
        tail_live_runner=fake_tail_runner,
        tail_signal_repository=FakeSignalRepository(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/tail-session/live-selection",
        json={
            "trade_date": "2026-06-12",
            "symbols": ["000001.SZ", "600519.SH"],
            "ignore_session": True,
        },
    )

    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()

    assert response.status_code == 200
    assert minute5_calls == []
    assert snapshot_calls[0]["limit"] == 0
    assert snapshot_calls[0]["include_st"] is False
    assert job["status"] == "success"
    assert job["result"]["data_refresh"]["inserted_rows"] == 2
    assert job["result"]["diagnostics"]["data_refresh_mode"] == "auto"
    assert job["result"]["diagnostics"]["quote_snapshot_sync"]["inserted_rows"] == 2
    assert "stage_timings" in job["result"]
    assert "quote_snapshot_sync" in job["result"]["stage_timings"]
    assert job["result"]["persistence"]["signals"]["signal_count"] == 0


def test_tail_live_selection_auto_mode_skips_snapshot_refresh_when_fresh(monkeypatch, tmp_path) -> None:
    snapshot_calls: list[dict[str, Any]] = []

    class FakeSignalRepository:
        def save_selection_result(self, *, job_id, result):
            return {"trade_date": result["trade_date"], "signal_count": 0, "selected_count": 0}

        def compute_and_save_outcomes(self, *, signal_date, symbols):
            return {"signal_date": signal_date.isoformat(), "outcome_count": 0, "missing_symbols": symbols}

    def fake_snapshot_runner(**kwargs):
        snapshot_calls.append(kwargs)
        return {"inserted_rows": 2}

    def fake_tail_runner(payload: TailLiveSelectionRequest, progress=None) -> dict[str, Any]:
        return {
            "trade_date": payload.trade_date.isoformat(),
            "scanned_count": 2,
            "candidate_count": 0,
            "confirmed_count": 0,
            "selected_count": 0,
            "selections": [],
            "files": {"json": "x", "csv": "x", "report": "x"},
            "market_breadth": None,
            "diagnostics": {},
        }

    monkeypatch.setattr(
        "src.web.backend.app._fresh_quote_snapshot_available",
        lambda **kwargs: {
            "fresh": True,
            "latest_snapshot_at": "2026-06-12 14:45:01",
            "covered_symbols": 2,
            "expected_symbols": 2,
            "age_seconds": 8.0,
        },
    )
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        run_jobs_inline=True,
        quote_snapshot_sync_runner=fake_snapshot_runner,
        tail_live_runner=fake_tail_runner,
        tail_signal_repository=FakeSignalRepository(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/tail-session/live-selection",
        json={
            "trade_date": "2026-06-12",
            "symbols": ["000001.SZ", "600519.SH"],
            "ignore_session": True,
        },
    )
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()

    assert response.status_code == 200
    assert snapshot_calls == []
    assert job["status"] == "success"
    assert job["result"]["data_refresh"]["skipped"] is True
    assert job["result"]["data_refresh"]["skip_reason"] == "fresh_quote_snapshot"
    assert job["result"]["diagnostics"]["quote_snapshot_sync"]["skipped"] is True


def test_tail_live_selection_job_can_force_standard_minute5_refresh(tmp_path) -> None:
    minute5_calls: list[dict[str, Any]] = []
    snapshot_calls: list[dict[str, Any]] = []

    class FakeSignalRepository:
        def save_selection_result(self, *, job_id, result):
            return {"trade_date": result["trade_date"], "signal_count": 0, "selected_count": 0}

        def compute_and_save_outcomes(self, *, signal_date, symbols):
            return {"signal_date": signal_date.isoformat(), "outcome_count": 0, "missing_symbols": symbols}

    def fake_minute5_runner(**kwargs):
        minute5_calls.append(kwargs)
        kwargs["progress"](100, "completed", "分钟线补齐完成")
        return {"inserted_rows": 12, "target_symbols": 2, "coverage_after": {"date_range": {"end": "2026-06-12 14:35:00"}}}

    def fake_snapshot_runner(**kwargs):
        snapshot_calls.append(kwargs)
        return {"inserted_rows": 2}

    def fake_tail_runner(payload: TailLiveSelectionRequest, progress=None) -> dict[str, Any]:
        assert minute5_calls, "standard_minute5 should run minute5 sync before strategy scan"
        assert not snapshot_calls
        return {
            "trade_date": payload.trade_date.isoformat(),
            "scanned_count": 2,
            "candidate_count": 0,
            "confirmed_count": 0,
            "selected_count": 0,
            "selections": [],
            "files": {"json": "x", "csv": "x", "report": "x"},
            "market_breadth": None,
            "diagnostics": {},
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        run_jobs_inline=True,
        minute5_sync_runner=fake_minute5_runner,
        quote_snapshot_sync_runner=fake_snapshot_runner,
        tail_live_runner=fake_tail_runner,
        tail_signal_repository=FakeSignalRepository(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/tail-session/live-selection",
        json={
            "trade_date": "2026-06-12",
            "symbols": ["000001.SZ", "600519.SH"],
            "ignore_session": True,
            "data_refresh_mode": "standard_minute5",
        },
    )
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()

    assert response.status_code == 200
    assert minute5_calls[0]["trade_date"].isoformat() == "2026-06-12"
    assert minute5_calls[0]["symbols"] == ["000001.SZ", "600519.SH"]
    assert job["status"] == "success"
    assert job["result"]["diagnostics"]["data_refresh_mode"] == "standard_minute5"
    assert job["result"]["diagnostics"]["minute5_sync"]["inserted_rows"] == 12


def test_tail_live_selection_explains_empty_universe(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return []

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=5,
            output_dir=str(tmp_path),
        )
    )

    assert result["selected_count"] == 0
    assert result["diagnostics"]["empty_reason"] == "scan_universe_empty"
    assert result["diagnostics"]["requested_scan_limit"] == 5
    assert result["diagnostics"]["resolved_scan_count"] == 0
    assert "没有解析到可扫描股票" in result["diagnostics"]["empty_message"]


def test_tail_live_selection_explains_no_intraday_candidates(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ", "600519.SH"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            import pandas as pd

            return pd.DataFrame()

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=2,
            output_dir=str(tmp_path),
        )
    )

    assert result["selected_count"] == 0
    assert result["diagnostics"]["empty_reason"] == "no_scoreable_intraday_data"
    assert result["diagnostics"]["has_intraday_data_count"] == 0
    assert result["diagnostics"]["scoreable_count"] == 0
    assert "没有可评分的尾盘分钟数据" in result["diagnostics"]["empty_message"]


def test_tail_live_selection_returns_ranked_near_misses_when_no_candidates(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ", "600519.SH"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            base_price = 10.0 if symbol == "000001.SZ" else 20.0
            tail_return = 0.004 if symbol == "000001.SZ" else -0.002
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": base_price, "close": base_price, "volume": 1100},
                    {"time": pd.Timestamp("14:35").time(), "open": base_price, "close": base_price * (1 + tail_return), "volume": 1200},
                    {"time": pd.Timestamp("14:40").time(), "open": base_price, "close": base_price * (1 + tail_return), "volume": 1200},
                    {"time": pd.Timestamp("14:45").time(), "open": base_price, "close": base_price * (1 + tail_return), "volume": 1200},
                    {"time": pd.Timestamp("14:50").time(), "open": base_price, "close": base_price * (1 + tail_return), "volume": 1200},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=2,
            output_dir=str(tmp_path),
        )
    )

    assert result["candidate_count"] == 0
    assert result["mode"] == "selection"
    assert result["diagnostics"]["scoreable_count"] == 2
    assert [row["symbol"] for row in result["ranked_signals"]] == ["000001.SZ", "600519.SH"]
    assert {row["status"] for row in result["ranked_signals"]} == {"filtered"}
    assert {row["filter_reason"] for row in result["ranked_signals"]} == {"below_candidate_threshold"}
    assert "score_breakdown" in result["ranked_signals"][0]
    assert result["ranked_signals"][0]["score_breakdown"]["volume_ratio"] > 0


def test_tail_live_selection_exposes_v2_watchlist_for_moderate_signals(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ", "000002.SZ"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            base_price = 10.0 if symbol == "000001.SZ" else 20.0
            tail_volume = 1280 if symbol == "000001.SZ" else 900
            tail_close = base_price * 1.002 if symbol == "000001.SZ" else base_price * 0.998
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": base_price, "close": tail_close, "volume": tail_volume},
                    {"time": pd.Timestamp("14:35").time(), "open": tail_close, "close": tail_close, "volume": tail_volume},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=2,
            output_dir=str(tmp_path),
        )
    )

    assert result["selected_count"] == 0
    assert result["signal_layers"] == {"strong": 0, "watchlist": 1, "weak": 1}
    assert [row["symbol"] for row in result["watchlist_signals"]] == ["000001.SZ"]
    assert result["watchlist_signals"][0]["v2_layer"] == "watchlist"
    assert result["watchlist_signals"][0]["v2_action"] == "observe_next_open"
    assert result["watchlist_signals"][0]["v2_score"] >= 45
    assert result["weak_signals"][0]["symbol"] == "000002.SZ"
    assert result["ranked_signals"][0]["v2_breakdown"]["tail_money"] > 0


def test_tail_live_selection_runs_intraday_preview_before_tail_window(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("09:35").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("09:40").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("09:45").time(), "open": 10.0, "close": 10.0, "volume": 1100},
                    {"time": pd.Timestamp("09:50").time(), "open": 10.0, "close": 10.0, "volume": 1200},
                    {"time": pd.Timestamp("09:55").time(), "open": 10.0, "close": 10.1, "volume": 1800},
                    {"time": pd.Timestamp("10:00").time(), "open": 10.1, "close": 10.2, "volume": 2200},
                    {"time": pd.Timestamp("10:05").time(), "open": 10.2, "close": 10.25, "volume": 2300},
                    {"time": pd.Timestamp("11:30").time(), "open": 10.25, "close": 10.3, "volume": 2400},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            output_dir=str(tmp_path),
        )
    )

    assert result["diagnostics"]["empty_reason"] == "intraday_preview"
    assert result["mode"] == "preview"
    assert result["diagnostics"]["latest_intraday_time"] == "11:30:00"
    assert "盘中预演" in result["diagnostics"]["empty_message"]
    assert result["selected_count"] == 0
    assert result["preview_count"] == 1
    assert result["ranked_signals"][0]["symbol"] == "000001.SZ"
    assert result["ranked_signals"][0]["status"] == "preview"
    assert result["ranked_signals"][0]["filter_reason"] == "preview_not_final"
    assert result["ranked_signals"][0]["reason"].startswith("intraday preview")
    credibility = result["ranked_signals"][0]["credibility"]
    assert 0 <= credibility["score"] <= 100
    assert credibility["grade"] in {"高", "中", "低"}
    assert credibility["phase"] == "盘中预演"
    assert credibility["components"]["signal_strength"] > 0
    assert credibility["components"]["volume_quality"] > 0
    assert credibility["components"]["return_quality"] > 0
    assert "14:30 后用正式尾盘窗口复核" in credibility["confirmation_checks"]
    assert credibility["history"]["status"] == "样本不足"
    assert credibility["risks"]
    assert result["strategy_rules"]["tail_window"] == "14:30-15:00"
    assert result["strategy_rules"]["preview_window_bars"] == 6
    assert result["strategy_rules"]["volume_ratio_threshold"] == 1.5
    assert result["strategy_rules"]["min_tail_return"] == 0.0


def test_tail_live_selection_keeps_early_tail_data_in_preview(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 10.0, "close": 10.05, "volume": 2500},
                    {"time": pd.Timestamp("14:35").time(), "open": 10.05, "close": 10.08, "volume": 2600},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            output_dir=str(tmp_path),
        )
    )

    assert result["mode"] == "preview"
    assert result["selected_count"] == 0
    assert result["preview_count"] == 1
    assert result["diagnostics"]["empty_reason"] == "intraday_preview"
    assert result["diagnostics"]["latest_intraday_time"] == "14:35:00"
    assert "14:50" in result["diagnostics"]["empty_message"]


def test_tail_live_selection_filters_watchlist_out_of_final_selection(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 10.0, "close": 10.01, "volume": 1600},
                    {"time": pd.Timestamp("14:35").time(), "open": 10.01, "close": 10.01, "volume": 1600},
                    {"time": pd.Timestamp("14:40").time(), "open": 10.01, "close": 10.01, "volume": 1600},
                    {"time": pd.Timestamp("14:45").time(), "open": 10.01, "close": 10.01, "volume": 1600},
                    {"time": pd.Timestamp("14:50").time(), "open": 10.01, "close": 10.01, "volume": 1600},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            output_dir=str(tmp_path),
        )
    )

    assert result["mode"] == "selection"
    assert result["selected_count"] == 0
    assert result["preview_count"] == 0
    assert result["ranked_signals"][0]["v2_layer"] == "watchlist"
    assert result["ranked_signals"][0]["status"] == "filtered"
    assert result["ranked_signals"][0]["filter_reason"] == "v2_not_trade_candidate"


def test_tail_live_selection_filters_limit_up_signal_from_executable_selection(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["605255.SH", "002774.SZ"]

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame(
                [
                    {"symbol": "605255.SH", "price": 83.26, "limit_up": 83.26},
                        {"symbol": "002774.SZ", "price": 11.12, "limit_up": 13.22},
                ]
            )

        def get_intraday_bars(self, symbol, trade_date, frequency):
            base_price = 80.0 if symbol == "605255.SH" else 11.0
            close = 83.26 if symbol == "605255.SH" else 11.12
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": base_price, "high": base_price, "low": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": base_price, "high": base_price, "low": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": base_price, "high": close, "low": base_price, "close": close, "volume": 5000 if symbol == "605255.SH" else 1800},
                    {"time": pd.Timestamp("14:35").time(), "open": close, "high": close, "low": close, "close": close, "volume": 5000 if symbol == "605255.SH" else 1900},
                    {"time": pd.Timestamp("14:40").time(), "open": close, "high": close, "low": close, "close": close, "volume": 5000 if symbol == "605255.SH" else 2000},
                    {"time": pd.Timestamp("14:45").time(), "open": close, "high": close, "low": close, "close": close, "volume": 5000 if symbol == "605255.SH" else 2100},
                    {"time": pd.Timestamp("14:50").time(), "open": close, "high": close, "low": close, "close": close, "volume": 5000 if symbol == "605255.SH" else 2000},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=2,
            top_n=2,
            output_dir=str(tmp_path),
        )
    )

    assert result["selected_count"] == 1
    assert [row["symbol"] for row in result["selections"]] == ["002774.SZ"]
    ranked_by_symbol = {row["symbol"]: row for row in result["ranked_signals"]}
    assert ranked_by_symbol["605255.SH"]["status"] == "filtered"
    assert ranked_by_symbol["605255.SH"]["filter_reason"] == "limit_up_not_buyable"
    assert ranked_by_symbol["605255.SH"]["tradability"]["buyable"] is False
    assert ranked_by_symbol["605255.SH"]["tradability"]["execution_flag"] == "blocked_limit_up"
    assert ranked_by_symbol["605255.SH"]["tradability"]["score"] < 50
    assert ranked_by_symbol["002774.SZ"]["tradability"]["execution_flag"] == "executable"
    assert ranked_by_symbol["002774.SZ"]["tradability"]["limit_up_distance"] > 0.1
    assert result["diagnostics"]["quote_status"]["status"] == "ok"
    assert result["diagnostics"]["quote_status"]["covered_symbols"] == 2
    assert result["diagnostics"]["data_freshness"]["status"] == "fresh"


def test_tail_live_selection_rows_include_next_day_execution_plan(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["002774.SZ"]

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame([{"symbol": "002774.SZ", "price": 11.12, "limit_up": 13.22}])

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 11.0, "high": 11.08, "low": 11.0, "close": 11.06, "volume": 1800},
                    {"time": pd.Timestamp("14:35").time(), "open": 11.06, "high": 11.10, "low": 11.06, "close": 11.09, "volume": 1900},
                    {"time": pd.Timestamp("14:40").time(), "open": 11.09, "high": 11.13, "low": 11.08, "close": 11.11, "volume": 2100},
                    {"time": pd.Timestamp("14:45").time(), "open": 11.11, "high": 11.13, "low": 11.10, "close": 11.12, "volume": 2000},
                    {"time": pd.Timestamp("14:50").time(), "open": 11.12, "high": 11.13, "low": 11.11, "close": 11.12, "volume": 2000},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            output_dir=str(tmp_path),
        )
    )

    plan = result["selections"][0]["next_day_plan"]
    assert plan["entry_policy"] == "next_open_or_no_chase"
    assert plan["sell_policy"] == "open_or_morning_strength"
    assert plan["gap_stop_return"] == -0.015
    assert plan["intraday_stop_return"] == -0.03
    assert any("低开超过 1.5%" in rule for rule in plan["rules"])


def test_tail_live_selection_filters_tail_pullback_risk_from_final_selection(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["600198.SH", "002774.SZ"]

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame(
                [
                    {"symbol": "600198.SH", "price": 9.69, "limit_up": 10.59},
                    {"symbol": "002774.SZ", "price": 11.12, "limit_up": 13.22},
                ]
            )

        def get_intraday_bars(self, symbol, trade_date, frequency):
            if symbol == "600198.SH":
                return pd.DataFrame(
                    [
                        {"time": pd.Timestamp("14:00").time(), "open": 9.2, "high": 9.2, "low": 9.2, "close": 9.2, "volume": 1000},
                        {"time": pd.Timestamp("14:05").time(), "open": 9.2, "high": 9.2, "low": 9.2, "close": 9.2, "volume": 1000},
                        {"time": pd.Timestamp("14:30").time(), "open": 9.27, "high": 10.01, "low": 9.27, "close": 9.81, "volume": 16900},
                        {"time": pd.Timestamp("14:35").time(), "open": 9.83, "high": 9.97, "low": 9.70, "close": 9.74, "volume": 6600},
                        {"time": pd.Timestamp("14:40").time(), "open": 9.75, "high": 9.77, "low": 9.69, "close": 9.69, "volume": 2800},
                        {"time": pd.Timestamp("14:45").time(), "open": 9.69, "high": 9.70, "low": 9.68, "close": 9.69, "volume": 1600},
                        {"time": pd.Timestamp("14:50").time(), "open": 9.68, "high": 9.70, "low": 9.61, "close": 9.62, "volume": 2100},
                    ]
                )
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 11.0, "high": 11.08, "low": 11.0, "close": 11.06, "volume": 1800},
                    {"time": pd.Timestamp("14:35").time(), "open": 11.06, "high": 11.10, "low": 11.06, "close": 11.09, "volume": 1900},
                    {"time": pd.Timestamp("14:40").time(), "open": 11.09, "high": 11.13, "low": 11.08, "close": 11.11, "volume": 2100},
                    {"time": pd.Timestamp("14:45").time(), "open": 11.11, "high": 11.13, "low": 11.10, "close": 11.12, "volume": 2000},
                    {"time": pd.Timestamp("14:50").time(), "open": 11.12, "high": 11.13, "low": 11.11, "close": 11.12, "volume": 2000},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=2,
            top_n=2,
            output_dir=str(tmp_path),
        )
    )

    assert result["selected_count"] == 1
    assert [row["symbol"] for row in result["selections"]] == ["002774.SZ"]
    ranked_by_symbol = {row["symbol"]: row for row in result["ranked_signals"]}
    assert ranked_by_symbol["600198.SH"]["status"] == "filtered"
    assert ranked_by_symbol["600198.SH"]["filter_reason"] == "tail_pullback_risk"
    assert any("冲高回落" in risk for risk in ranked_by_symbol["600198.SH"]["v2_risks"])


def test_tail_live_selection_returns_ranked_signals_filtered_from_final_selection(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ", "600519.SH"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            base_price = 10.0 if symbol == "000001.SZ" else 20.0
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": base_price, "close": base_price, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": base_price, "close": base_price * 1.001, "volume": 2000},
                    {"time": pd.Timestamp("14:35").time(), "open": base_price, "close": base_price * 1.002, "volume": 2200},
                    {"time": pd.Timestamp("14:40").time(), "open": base_price, "close": base_price * 1.003, "volume": 2400},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=2,
            min_strength=0.95,
            output_dir=str(tmp_path),
        )
    )

    assert result["selected_count"] == 0
    assert [row["rank"] for row in result["ranked_signals"]] == [1, 2]
    assert {row["status"] for row in result["ranked_signals"]} == {"filtered"}
    assert {row["filter_reason"] for row in result["ranked_signals"]} == {"below_min_strength"}


def test_tail_live_selection_ranks_strategy_pool_by_v2_trade_readiness() -> None:
    hot_but_not_tradeable = TailSessionSignal(
        symbol="000001.SZ",
        trade_date=pd.Timestamp("2026-06-12").date(),
        strength=1.0,
        last_price=10.3,
        volume_ratio=3.0,
        tail_return=0.03,
        reason="hot but chase risk",
        tail_high_return=0.03,
        pullback_from_high=0.0,
        close_position=1.0,
    )
    trade_ready = TailSessionSignal(
        symbol="688768.SH",
        trade_date=pd.Timestamp("2026-06-12").date(),
        strength=0.8,
        last_price=20.1,
        volume_ratio=1.8,
        tail_return=0.01,
        reason="balanced trade candidate",
        tail_high_return=0.012,
        pullback_from_high=-0.001,
        close_position=0.9,
    )

    selected = _final_trade_candidates([hot_but_not_tradeable, trade_ready], top_n=1, min_strength=None)
    rows = _ranked_signal_rows(
        confirmed=[hot_but_not_tradeable, trade_ready],
        selected=selected,
        ranked_pool=[hot_but_not_tradeable, trade_ready],
        mode="selection",
        top_n=1,
        min_strength=None,
    )

    assert [signal.symbol for signal in selected] == ["688768.SH"]
    assert rows[0]["symbol"] == "688768.SH"
    assert rows[0]["status"] == "selected"
    assert rows[0]["raw_rank"] == 2
    assert rows[0]["final_candidate_rank"] == 1
    assert rows[1]["symbol"] == "000001.SZ"
    assert rows[1]["raw_rank"] == 1
    assert rows[1]["filter_reason"] == "v2_not_trade_candidate"


def test_tail_live_selection_uses_completed_bar_as_of_time(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ"]

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:05").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:35").time(), "open": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:40").time(), "open": 10.0, "close": 10.8, "volume": 6000},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            as_of_time="14:37:00",
            output_dir=str(tmp_path),
        )
    )

    assert result["mode"] == "preview"
    assert result["diagnostics"]["scan_as_of_time"] == "14:35:00"
    assert result["selected_count"] == 0


def test_tail_live_selection_marks_stale_data_when_latest_bar_lags_target(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ"]

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame([{"symbol": "000001.SZ", "price": 10.1, "limit_up": 11.0}])

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 10.0, "high": 10.1, "low": 10.0, "close": 10.1, "volume": 3000},
                    {"time": pd.Timestamp("14:35").time(), "open": 10.1, "high": 10.1, "low": 10.1, "close": 10.1, "volume": 3000},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            as_of_time="14:56:00",
            output_dir=str(tmp_path),
        )
    )

    assert result["diagnostics"]["data_freshness"]["status"] == "stale"
    assert result["diagnostics"]["data_freshness"]["target_time"] == "14:55:00"
    assert result["diagnostics"]["data_freshness"]["latest_time"] == "14:35:00"
    assert result["diagnostics"]["empty_reason"] == "data_stale"
    assert result["selected_count"] == 0


def test_tail_live_selection_reports_realtime_quote_failure(monkeypatch, tmp_path) -> None:
    class FakeScheduler:
        def is_tail_session(self) -> bool:
            return True

        def is_trading_day(self, trade_date) -> bool:
            return True

    class FakeAggregator:
        def get_csi300_symbols(self):
            return ["000001.SZ"]

        def get_realtime_quotes(self, symbols):
            raise RuntimeError("quote source down")

        def get_intraday_bars(self, symbol, trade_date, frequency):
            return pd.DataFrame(
                [
                    {"time": pd.Timestamp("14:00").time(), "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000},
                    {"time": pd.Timestamp("14:30").time(), "open": 10.0, "high": 10.4, "low": 10.0, "close": 10.4, "volume": 4000},
                    {"time": pd.Timestamp("14:35").time(), "open": 10.4, "high": 10.6, "low": 10.4, "close": 10.6, "volume": 4000},
                    {"time": pd.Timestamp("14:40").time(), "open": 10.6, "high": 10.8, "low": 10.6, "close": 10.8, "volume": 4000},
                    {"time": pd.Timestamp("14:45").time(), "open": 10.8, "high": 10.9, "low": 10.8, "close": 10.9, "volume": 4000},
                    {"time": pd.Timestamp("14:50").time(), "open": 10.9, "high": 11.0, "low": 10.9, "close": 11.0, "volume": 4000},
                ]
            )

    monkeypatch.setattr("src.web.backend.tail_live.TradingScheduler", lambda: FakeScheduler())
    monkeypatch.setattr("src.web.backend.tail_live.DataAggregator", lambda: FakeAggregator())

    result = run_tail_live_selection(
        TailLiveSelectionRequest(
            trade_date="2026-06-12",
            universe="default",
            limit=1,
            output_dir=str(tmp_path),
        )
    )

    assert result["diagnostics"]["quote_status"]["status"] == "failed"
    assert "quote source down" in result["diagnostics"]["quote_status"]["error"]
    assert result["ranked_signals"][0]["tradability"]["execution_flag"] == "unknown"
