from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from src.strategy.scanner import IntradayScanner


def _intraday_bars(
    symbol: str = "000001.SZ",
    tail_volume: int = 3000,
    tail_close: float = 10.3,
) -> pd.DataFrame:
    rows = []
    for dt, close, volume in [
        (datetime(2025, 6, 3, 14, 0), 10.0, 1000),
        (datetime(2025, 6, 3, 14, 5), 10.02, 1000),
        (datetime(2025, 6, 3, 14, 10), 10.03, 1000),
        (datetime(2025, 6, 3, 14, 30), 10.1, tail_volume),
        (datetime(2025, 6, 3, 14, 35), 10.2, tail_volume),
        (datetime(2025, 6, 3, 14, 40), tail_close, tail_volume),
    ]:
        rows.append({
            "datetime": dt,
            "time": dt.time(),
            "symbol": symbol,
            "open": close - 0.02,
            "high": close + 0.03,
            "low": close - 0.03,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        })
    return pd.DataFrame(rows)


class FakeAggregator:
    def __init__(self, bars: pd.DataFrame):
        self.bars = bars

    def get_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        return self.bars[self.bars["symbol"] == symbol].copy()


def test_intraday_scanner_finds_tail_price_volume_signal() -> None:
    scanner = IntradayScanner(
        FakeAggregator(_intraday_bars()),
        volume_ratio_threshold=1.5,
        min_tail_return=0.01,
        confirmation_count=1,
    )

    signals = scanner.scan(["000001.SZ"], date(2025, 6, 3))

    assert len(signals) == 1
    assert signals[0].symbol == "000001.SZ"
    assert signals[0].strength > 0
    assert "tail" in signals[0].reason.lower()


def test_intraday_scanner_rejects_weak_tail_volume() -> None:
    scanner = IntradayScanner(
        FakeAggregator(_intraday_bars(tail_volume=1100)),
        volume_ratio_threshold=1.5,
        min_tail_return=0.01,
        confirmation_count=1,
    )

    signals = scanner.scan(["000001.SZ"], date(2025, 6, 3))

    assert signals == []


def test_intraday_scanner_requires_consecutive_confirmations() -> None:
    scanner = IntradayScanner(
        FakeAggregator(_intraday_bars()),
        volume_ratio_threshold=1.5,
        min_tail_return=0.01,
        confirmation_count=3,
    )

    candidates = scanner.scan(["000001.SZ"], date(2025, 6, 3))

    assert scanner.confirm(candidates) == []
    assert scanner.confirm(candidates) == []
    confirmed = scanner.confirm(candidates)
    assert [signal.symbol for signal in confirmed] == ["000001.SZ"]
