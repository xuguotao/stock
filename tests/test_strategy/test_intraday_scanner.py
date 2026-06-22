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


class BatchFakeAggregator(FakeAggregator):
    def __init__(self, bars: pd.DataFrame):
        super().__init__(bars)
        self.batch_calls = []
        self.single_calls = []

    def get_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.batch_calls.append((symbols, trade_date, frequency))
        return self.bars[self.bars["symbol"].isin(symbols)].copy()

    def get_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.single_calls.append(symbol)
        return super().get_intraday_bars(symbol, trade_date, frequency)


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
    assert signals[0].tail_high_return > 0
    assert signals[0].pullback_from_high <= 0
    assert 0 <= signals[0].close_position <= 1


def test_intraday_scanner_marks_tail_pullback_after_spike() -> None:
    bars = pd.DataFrame(
        [
            {"datetime": datetime(2025, 6, 3, 14, 0), "time": datetime(2025, 6, 3, 14, 0).time(), "symbol": "000001.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000, "amount": 10000},
            {"datetime": datetime(2025, 6, 3, 14, 5), "time": datetime(2025, 6, 3, 14, 5).time(), "symbol": "000001.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000, "amount": 10000},
            {"datetime": datetime(2025, 6, 3, 14, 30), "time": datetime(2025, 6, 3, 14, 30).time(), "symbol": "000001.SZ", "open": 10.0, "high": 10.9, "low": 10.0, "close": 10.7, "volume": 9000, "amount": 96300},
            {"datetime": datetime(2025, 6, 3, 14, 35), "time": datetime(2025, 6, 3, 14, 35).time(), "symbol": "000001.SZ", "open": 10.7, "high": 10.72, "low": 10.2, "close": 10.25, "volume": 5000, "amount": 51250},
            {"datetime": datetime(2025, 6, 3, 14, 40), "time": datetime(2025, 6, 3, 14, 40).time(), "symbol": "000001.SZ", "open": 10.25, "high": 10.3, "low": 10.1, "close": 10.2, "volume": 4000, "amount": 40800},
        ]
    )
    scanner = IntradayScanner(FakeAggregator(bars), volume_ratio_threshold=1.5, min_tail_return=0.0)

    ranked, candidates = scanner.scan_with_rank(["000001.SZ"], date(2025, 6, 3))

    assert len(candidates) == 1
    assert round(ranked[0].tail_high_return, 4) == 0.09
    assert ranked[0].pullback_from_high < -0.06
    assert ranked[0].close_position < 0.25


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


def test_intraday_scanner_ignores_bars_after_max_bar_time() -> None:
    bars = _intraday_bars(tail_volume=1000, tail_close=10.0)
    bars = pd.concat(
        [
            bars,
            pd.DataFrame(
                [
                    {
                        "datetime": datetime(2025, 6, 3, 14, 45),
                        "time": datetime(2025, 6, 3, 14, 45).time(),
                        "symbol": "000001.SZ",
                        "open": 10.0,
                        "high": 10.5,
                        "low": 10.0,
                        "close": 10.5,
                        "volume": 5000,
                        "amount": 52500,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    scanner = IntradayScanner(
        FakeAggregator(bars),
        volume_ratio_threshold=1.5,
        min_tail_return=0.01,
        confirmation_count=1,
        max_bar_time=datetime(2025, 6, 3, 14, 40).time(),
    )

    ranked, candidates = scanner.scan_with_rank(["000001.SZ"], date(2025, 6, 3))

    assert candidates == []
    assert ranked[0].last_price == 10.0


def test_intraday_scanner_uses_batch_intraday_read_when_available() -> None:
    bars = pd.concat([
        _intraday_bars("000001.SZ"),
        _intraday_bars("600000.SH", tail_volume=1100),
    ], ignore_index=True)
    aggregator = BatchFakeAggregator(bars)
    scanner = IntradayScanner(
        aggregator,
        volume_ratio_threshold=1.5,
        min_tail_return=0.01,
        confirmation_count=1,
    )

    ranked, candidates = scanner.scan_with_rank(["000001.SZ", "600000.SH"], date(2025, 6, 3))

    assert aggregator.batch_calls == [(["000001.SZ", "600000.SH"], date(2025, 6, 3), "5m")]
    assert aggregator.single_calls == []
    assert [signal.symbol for signal in ranked] == ["000001.SZ", "600000.SH"]
    assert [signal.symbol for signal in candidates] == ["000001.SZ"]
