from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data.mootdx_source import MootdxSource, normalize_mootdx_bars, normalize_mootdx_quotes


class FakeMootdxClient:
    def stocks(self, market: int) -> pd.DataFrame:
        if market == 0:
            return pd.DataFrame([
                {"code": "000001", "name": "平安银行"},
                {"code": "395001", "name": "主板Ａ股"},
            ])
        if market == 1:
            return pd.DataFrame([
                {"code": "600519", "name": "贵州茅台\x00"},
                {"code": "999999", "name": "上证指数"},
            ])
        return pd.DataFrame([
            {"code": "920001", "name": "北证样本"},
        ])

    def quotes(self, symbol: list[str]) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "code": "000001",
                "price": 10.5,
                "last_close": 10.0,
                "open": 10.1,
                "high": 10.8,
                "low": 10.0,
                "vol": 1234,
                "volume": 123400,
                "amount": 567890.0,
                "servertime": "2026-07-09 14:30:00",
            }
        ])

    def bars(self, symbol: str, frequency: str | int, start: int = 0, offset: int = 800, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "open": 10.1,
                    "close": 10.4,
                    "high": 10.5,
                    "low": 10.0,
                    "vol": 100,
                    "amount": 100000.0,
                    "datetime": "2026-07-09 09:35",
                    "volume": 10000,
                },
                {
                    "open": 10.4,
                    "close": 10.6,
                    "high": 10.7,
                    "low": 10.3,
                    "vol": 120,
                    "amount": 130000.0,
                    "datetime": "2026-07-09 09:40",
                    "volume": 12000,
                },
            ]
        )


def test_fetch_stock_list_normalizes_supported_markets() -> None:
    source = MootdxSource(client=FakeMootdxClient(), include_beijing=True)

    stocks = source.fetch_stock_list()

    assert [item.symbol for item in stocks] == ["000001.SZ", "600519.SH", "920001.BJ"]
    assert [item.name for item in stocks] == ["平安银行", "贵州茅台", "北证样本"]


def test_fetch_realtime_quotes_normalizes_project_quote_schema() -> None:
    source = MootdxSource(client=FakeMootdxClient())

    quotes = source.fetch_realtime_quotes(["000001.SZ"])

    assert quotes.to_dict("records") == [
        {
            "symbol": "000001.SZ",
            "price": 10.5,
            "open": 10.1,
            "prev_close": 10.0,
            "high": 10.8,
            "low": 10.0,
            "volume": 123400,
            "amount": 567890.0,
            "change_pct": pytest.approx(5.0),
            "timestamp": "2026-07-09 14:30:00",
        }
    ]


def test_fetch_daily_bars_filters_range_and_uses_project_schema() -> None:
    source = MootdxSource(client=FakeMootdxClient())

    bars = source.fetch_bars("000001.SZ", date(2026, 7, 9), date(2026, 7, 9), "daily")

    assert list(bars.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjusted_close",
        "symbol",
    ]
    assert bars.iloc[0].to_dict() == {
        "date": date(2026, 7, 9),
        "open": 10.1,
        "high": 10.5,
        "low": 10.0,
        "close": 10.4,
        "volume": 10000,
        "amount": 100000.0,
        "adjusted_close": 10.4,
        "symbol": "000001.SZ",
    }


def test_fetch_intraday_bars_normalizes_datetime_and_frequency_alias() -> None:
    source = MootdxSource(client=FakeMootdxClient())

    bars = source.fetch_intraday_bars("000001.SZ", date(2026, 7, 9), "5m")

    assert list(bars.columns) == ["datetime", "time", "symbol", "open", "high", "low", "close", "volume", "amount"]
    assert bars["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist() == ["2026-07-09 09:35", "2026-07-09 09:40"]
    assert bars["time"].astype(str).tolist() == ["09:35:00", "09:40:00"]


def test_normalizers_return_empty_frame_for_missing_datetime_or_code() -> None:
    assert normalize_mootdx_bars(pd.DataFrame([{"open": 1.0}]), "000001.SZ").empty
    assert normalize_mootdx_quotes(pd.DataFrame([{"price": 1.0}])).empty


def test_lazy_import_reports_optional_dependency_when_missing() -> None:
    source = MootdxSource(quotes_factory=lambda **kwargs: (_ for _ in ()).throw(ModuleNotFoundError("mootdx")))

    with pytest.raises(RuntimeError, match="mootdx is not installed"):
        source.fetch_realtime_quotes(["000001.SZ"])


def test_mootdx_source_exposes_f10_helpers() -> None:
    class Client:
        def F10C(self, symbol):
            return pd.DataFrame([{"title": "最新提示"}])

        def F10(self, symbol, name):
            return "详情正文"

    source = MootdxSource(client=Client())

    assert source.fetch_f10_catalog("000001.SZ").iloc[0]["title"] == "最新提示"
    assert source.fetch_f10_detail("000001.SZ", "最新提示") == "详情正文"


def test_mootdx_source_fetch_affair_files_uses_injected_fetcher() -> None:
    source = MootdxSource(client=object(), affair_files_fetcher=lambda: [{"filename": "gpcw20260331.zip"}])

    assert source.fetch_affair_files() == [{"filename": "gpcw20260331.zip"}]
