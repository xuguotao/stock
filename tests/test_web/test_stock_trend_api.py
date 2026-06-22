from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_stock_trend_api_returns_symbol_trend(tmp_path) -> None:
    def fake_runner(symbol: str, *, trade_date: date | None = None, daily_window: int = 90) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "name": "紫金矿业",
            "trade_date": trade_date.isoformat() if trade_date else "2026-06-16",
            "latest_price": 18.2,
            "latest_intraday_time": "14:35:00",
            "quote": {"source": "snapshot", "price": 18.2, "change_pct": 0.8, "pe_ttm": 12.3},
            "metrics": {"daily_return_5d": 0.032, "intraday_return": 0.008},
            "daily": [{"date": "2026-06-15", "open": 17.8, "high": 18.1, "low": 17.6, "close": 18.0, "ma5": 17.5, "ma10": 17.2, "ma20": 16.8, "ma60": 15.9}],
            "intraday": [{"time": "14:35:00", "close": 18.2, "volume": 120000}],
        }

    app = create_app(db_path=tmp_path / "jobs.sqlite3", stock_trend_runner=fake_runner)
    client = TestClient(app)

    response = client.get("/api/stocks/601899.SH/trend?trade_date=2026-06-16&daily_window=60")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "601899.SH"
    assert payload["name"] == "紫金矿业"
    assert payload["latest_intraday_time"] == "14:35:00"
    assert payload["quote"]["source"] == "snapshot"
    assert payload["metrics"]["daily_return_5d"] == 0.032
