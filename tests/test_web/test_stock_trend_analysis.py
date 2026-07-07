from __future__ import annotations

from datetime import date, time

import pandas as pd

from src.web.backend import stock_trend


class FakeAggregator:
    def __init__(self) -> None:
        self.intraday_frequency: str | None = None

    def get_bars(self, symbol: str, start: date, end: date, frequency: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": "2026-06-15", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.2, "volume": 1000, "amount": 10000},
                {"date": "2026-06-16", "open": 10.2, "high": 10.7, "low": 10.1, "close": 10.6, "volume": 1200, "amount": 12000},
            ]
        )

    def get_intraday_bars(self, symbol: str, trade_date: date, frequency: str) -> pd.DataFrame:
        self.intraday_frequency = frequency
        return pd.DataFrame(
            [
                {"datetime": "2026-06-16 14:00:00", "time": time(14, 0), "open": 10.00, "high": 10.05, "low": 9.95, "close": 10.00, "volume": 1000, "amount": 10000},
                {"datetime": "2026-06-16 14:25:00", "time": time(14, 25), "open": 10.00, "high": 10.08, "low": 9.98, "close": 10.05, "volume": 1000, "amount": 10000},
                {"datetime": "2026-06-16 14:30:00", "time": time(14, 30), "open": 10.10, "high": 10.30, "low": 10.05, "close": 10.25, "volume": 3000, "amount": 30000},
                {"datetime": "2026-06-16 14:35:00", "time": time(14, 35), "open": 10.25, "high": 10.50, "low": 10.20, "close": 10.45, "volume": 3000, "amount": 30000},
            ]
        )

    def get_stock_list(self) -> list[object]:
        return []


def test_stock_trend_analysis_returns_tail_strategy_evidence(monkeypatch) -> None:
    fake = FakeAggregator()
    monkeypatch.setattr(stock_trend, "DataAggregator", lambda: fake)

    result = stock_trend.analyze_stock_trend("000001.SZ", trade_date=date(2026, 6, 16), granularity="1m")

    assert fake.intraday_frequency == "5m"
    assert result["granularity"] == "5m"
    assert result["tail_evidence"]["status"] == "ok"
    assert result["tail_evidence"]["volume_ratio"] == 3.0
    assert result["tail_evidence"]["tail_return"] == 0.034653
    assert result["tail_evidence"]["tail_high_return"] == 0.039604
    assert result["tail_evidence"]["pullback_from_high"] == -0.004762
    assert result["tail_evidence"]["close_position"] == 0.888889
    assert result["tail_evidence"]["source"] == "5m"
