from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.tail_live import TailLiveSelectionRequest, run_tail_live_selection


def test_tail_live_selection_api_runs_inline_job(tmp_path) -> None:
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
    assert result["diagnostics"]["empty_reason"] == "no_intraday_candidates"
    assert result["diagnostics"]["has_intraday_data_count"] == 0
    assert "没有股票形成尾盘候选信号" in result["diagnostics"]["empty_message"]
