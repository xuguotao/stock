from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.tail_live import TailLiveSelectionRequest, run_tail_live_selection


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

    assert request.limit == 200
    assert request.liquidity_min_bars == 60


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
