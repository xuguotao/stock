from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.fund_tail_market_data import refresh_fund_tail_proxy_quotes


class FakeFundTailRepository:
    def __init__(self) -> None:
        self.proxy_rows = []
        self.benchmark_rows = []

    def insert_proxy_quotes(self, rows):
        self.proxy_rows.extend(rows)
        return {"proxy_rows": len(rows)}

    def insert_benchmark_quotes(self, rows):
        self.benchmark_rows.extend(rows)
        return {"benchmark_rows": len(rows)}


class FakeQuoteSource:
    name = "tencent"

    def __init__(self) -> None:
        self.calls = []

    def fetch_realtime_quotes(self, symbols):
        self.calls.append(list(symbols))
        return pd.DataFrame(
            [
                {"symbol": "399396.SZ", "price": 14026.16, "volume": 100.0, "timestamp": "2026-06-18 14:55:00"},
                {"symbol": "000300.SH", "price": 4941.60, "volume": 200.0, "timestamp": "2026-06-18 14:55:00"},
            ]
        )


def test_refresh_fund_tail_proxy_quotes_updates_selected_proxies_and_benchmark() -> None:
    repository = FakeFundTailRepository()
    quote_source = FakeQuoteSource()

    result = refresh_fund_tail_proxy_quotes(
        repository,
        fund_codes=["001632"],
        proxy_specs={
            "001632": ("cni", "399396", "sz399396"),
        },
        quote_source=quote_source,
        trade_date=date(2026, 6, 18),
    )

    assert quote_source.calls == [["399396.SZ", "000300.SH"]]
    assert repository.proxy_rows == [
        {
            "fund_code": "001632",
            "proxy_provider": "cni",
            "proxy_code": "399396",
            "date": date(2026, 6, 18),
            "close": 14026.16,
            "volume": 100.0,
            "source": "tencent",
            "timestamp": "2026-06-18 14:55:00",
        }
    ]
    assert repository.benchmark_rows == [
        {
            "date": date(2026, 6, 18),
            "close": 4941.60,
            "volume": 200.0,
            "source": "tencent",
            "timestamp": "2026-06-18 14:55:00",
        }
    ]
    assert result["source"] == "tencent"
    assert result["proxy_rows"] == 1
    assert result["benchmark_rows"] == 1
    assert result["missing_symbols"] == []


def test_refresh_fund_tail_proxy_quotes_skips_non_a_share_proxy_codes() -> None:
    repository = FakeFundTailRepository()
    quote_source = FakeQuoteSource()

    result = refresh_fund_tail_proxy_quotes(
        repository,
        fund_codes=["017437"],
        proxy_specs={
            "017437": ("us_sina", "QQQ"),
        },
        quote_source=quote_source,
        trade_date=date(2026, 6, 18),
    )

    assert quote_source.calls == [["000300.SH"]]
    assert repository.proxy_rows == []
    assert result["skipped_funds"] == ["017437"]
