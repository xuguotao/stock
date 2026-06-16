from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.mootdx_source import MootdxSource, is_mootdx_available


class FakeMootdxClient:
    def __init__(self):
        self.bars_calls = []
        self.quotes_calls = []

    def bars(self, *, symbol: str, category: int, market: int | None = None, offset: int = 0):
        self.bars_calls.append((symbol, category, market, offset))
        return pd.DataFrame(
            [
                {
                    "datetime": "2026-06-12 14:30:00",
                    "open": 10.0,
                    "close": 10.2,
                    "high": 10.3,
                    "low": 9.9,
                    "vol": 1000,
                    "amount": 10200.0,
                },
                {
                    "datetime": "2026-06-12 14:35:00",
                    "open": 10.2,
                    "close": 10.4,
                    "high": 10.5,
                    "low": 10.1,
                    "vol": 1200,
                    "amount": 12480.0,
                },
            ]
        )

    def quotes(self, *, symbol: list[str]):
        self.quotes_calls.append(symbol)
        return pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "price": 11.06,
                    "last_close": 11.24,
                    "open": 11.20,
                    "high": 11.30,
                    "low": 11.00,
                    "vol": 100000,
                    "amount": 110600000.0,
                    "bid1": 11.05,
                    "ask1": 11.06,
                    "bid_vol1": 200,
                    "ask_vol1": 300,
                    "servertime": "2026-06-15 15:00:00",
                }
            ]
        )


def test_is_mootdx_available_false_when_module_missing(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mootdx.quotes":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert is_mootdx_available() is False


def test_mootdx_source_parses_5m_intraday_bars() -> None:
    client = FakeMootdxClient()
    source = MootdxSource(client_factory=lambda: client, rate_limit=0.0)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 12), "5m")

    assert client.bars_calls == [("000001", 8, 0, 800)]
    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert result["time"].tolist() == [
        pd.Timestamp("2026-06-12 14:30:00").time(),
        pd.Timestamp("2026-06-12 14:35:00").time(),
    ]
    assert result["close"].tolist() == [10.2, 10.4]


def test_mootdx_source_parses_daily_bars() -> None:
    client = FakeMootdxClient()
    source = MootdxSource(client_factory=lambda: client, rate_limit=0.0)

    result = source.fetch_bars("600519.SH", date(2026, 6, 12), date(2026, 6, 12), "daily")

    assert client.bars_calls == [("600519", 4, 1, 800)]
    assert result["symbol"].tolist() == ["600519.SH", "600519.SH"]
    assert result["date"].tolist() == [date(2026, 6, 12), date(2026, 6, 12)]
    assert result["adjusted_close"].tolist() == [10.2, 10.4]


def test_mootdx_source_parses_quotes_with_order_book_columns() -> None:
    client = FakeMootdxClient()
    source = MootdxSource(client_factory=lambda: client, rate_limit=0.0)

    result = source.fetch_realtime_quotes(["000001.SZ"])

    assert client.quotes_calls == [["000001"]]
    assert result.iloc[0]["symbol"] == "000001.SZ"
    assert result.iloc[0]["price"] == 11.06
    assert result.iloc[0]["change_pct"] == round((11.06 - 11.24) / 11.24 * 100, 2)
    assert result.iloc[0]["bid1"] == 11.05
    assert result.iloc[0]["ask_vol1"] == 300
