from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.watchlist_monitor import get_watchlist_report


def test_watchlist_monitor_report_api_returns_items(tmp_path) -> None:
    def fake_runner(trade_date: date | None = None) -> dict[str, Any]:
        return {
            "trade_date": (trade_date or date(2026, 6, 17)).isoformat(),
            "summary": {"entry_zone": 1, "hot_wait": 1},
            "items": [
                {
                    "symbol": "601899",
                    "name": "紫金矿业",
                    "theme": "金铜资源",
                    "notes": "关注金铜。",
                    "latest_price": 29.7,
                    "daily_change_pct": -1.2,
                    "return_5d": -0.03,
                    "return_20d": -0.1,
                    "ma5": 30.1,
                    "ma20": 31.2,
                    "volume_ratio": 1.1,
                    "status": "entry_zone",
                    "reasons": ["价格进入试仓区。"],
                    "levels": {
                        "observe": [30.0, 30.5],
                        "entry": [29.5, 29.8],
                        "add": [28.5, 29.0],
                        "invalid": 27.0,
                        "breakout": 32.0,
                    },
                    "data_status": "ok",
                }
            ],
        }

    app = create_app(
        db_path=tmp_path / "jobs.json",
        watchlist_monitor_runner=fake_runner,
        auto_start_minute5_monitor=False,
        auto_start_quote_snapshot_monitor=False,
    )
    client = TestClient(app)

    response = client.get("/api/watchlist-monitor/report?trade_date=2026-06-17")

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "2026-06-17"
    assert payload["items"][0]["symbol"] == "601899"
    assert payload["items"][0]["status"] == "entry_zone"


def test_watchlist_report_prefers_clickhouse_quote_snapshots(tmp_path) -> None:
    config_path = tmp_path / "watchlist.yaml"
    config_path.write_text(
        """
stocks:
  - symbol: "601899"
    name: "紫金矿业"
    theme: "金铜资源"
    notes: "关注金铜。"
    levels:
      observe: [30.0, 30.5]
      entry: [29.5, 29.8]
      add: [28.5, 29.0]
      invalid: 27.0
      breakout: 32.0
""".strip(),
        encoding="utf-8",
    )

    class FakeSnapshotSource:
        def fetch_latest_quote_snapshots(self, symbols, trade_date):
            return pd.DataFrame([
                {
                    "symbol": "601899.SH",
                    "price": 29.7,
                    "change_pct": -1.2,
                    "snapshot_at": pd.Timestamp("2026-06-17 10:58:08"),
                    "quote_time": pd.Timestamp("2026-06-17 10:57:54"),
                }
            ])

        def fetch_bars(self, symbol, start, end, frequency):
            return pd.DataFrame([
                {"date": date(2026, 6, 16), "close": 31.0, "volume": 100},
                {"date": date(2026, 6, 17), "close": 35.0, "volume": 120},
            ])

    class FakeAggregator:
        sources = [FakeSnapshotSource()]

        def get_bars(self, symbol, start, end, frequency):
            return self.sources[0].fetch_bars(symbol, start, end, frequency)

    report = get_watchlist_report(
        trade_date=date(2026, 6, 17),
        config_path=config_path,
        aggregator=FakeAggregator(),
    )

    item = report["items"][0]
    assert item["latest_price"] == 29.7
    assert item["daily_change_pct"] == -1.2
    assert item["data_status"] == "snapshot_ok"
    assert item["quote_time"] == "2026-06-17 10:57:54"
    assert item["status"] == "entry_zone"
