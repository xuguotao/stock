from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.intraday_fallback import FallbackIntradaySource


class FakeSource:
    def __init__(self, empty_symbols: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.empty_symbols = empty_symbols or set()

    def fetch_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.calls.append(symbol)
        if symbol in self.empty_symbols:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 14:55:00"),
                    "time": pd.Timestamp(f"{trade_date.isoformat()} 14:55:00").time(),
                    "symbol": symbol,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10100.0,
                }
            ]
        )


class FakeBatchSource(FakeSource):
    def __init__(self, provided_symbols: set[str]) -> None:
        super().__init__()
        self.provided_symbols = provided_symbols
        self.batch_calls: list[tuple[list[str], date, str]] = []

    def fetch_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.batch_calls.append((symbols, trade_date, frequency))
        frames = [
            super().fetch_intraday_bars(symbol, trade_date, frequency)
            for symbol in symbols
            if symbol in self.provided_symbols
        ]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


def test_fallback_intraday_source_uses_batch_source_then_fills_missing_symbols() -> None:
    primary = FakeBatchSource({"000001.SZ"})
    fallback = FakeSource()
    source = FallbackIntradaySource([primary, fallback])

    result = source.fetch_intraday_bars_batch(["000001.SZ", "600000.SH"], date(2026, 6, 12), "5m")

    assert primary.batch_calls == [(["000001.SZ", "600000.SH"], date(2026, 6, 12), "5m")]
    assert fallback.calls == ["600000.SH"]
    assert sorted(result["symbol"].unique().tolist()) == ["000001.SZ", "600000.SH"]
