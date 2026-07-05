"""Tests for the data module: models, cache, aggregator, sources."""

from __future__ import annotations

import json
import os
import sys
import time
import types
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.models import DailyBar, FinancialStatement, StockInfo, TradeRecord
from src.core.types import Side


# ── Models ────────────────────────────────────────────────────

class TestDailyBar:
    def test_mid_price(self) -> None:
        bar = DailyBar(
            symbol="000001.SZ",
            date=date(2025, 6, 1),
            open=10.0, high=11.0, low=9.0, close=10.5,
            volume=1_000_000, amount=10_500_000,
            adjusted_close=10.5,
        )
        assert bar.mid == 10.0

    def test_frozen_dataclass(self) -> None:
        bar = DailyBar(
            symbol="000001.SZ",
            date=date(2025, 6, 1),
            open=10.0, high=11.0, low=9.0, close=10.5,
            volume=1_000_000, amount=10_500_000,
            adjusted_close=10.5,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            bar.close = 11.0  # type: ignore

    def test_default_suspended_false(self) -> None:
        bar = DailyBar(
            symbol="000001.SZ", date=date(2025, 6, 1),
            open=10.0, high=11.0, low=9.0, close=10.5,
            volume=1_000_000, amount=10_500_000, adjusted_close=10.5,
        )
        assert bar.suspended is False


class TestStockInfo:
    def test_defaults(self) -> None:
        info = StockInfo(symbol="000001.SZ", code="000001", name="平安银行")
        assert info.industry == ""
        assert info.list_date is None
        assert info.is_st is False

    def test_is_st_only_matches_special_treatment_prefix(self) -> None:
        from src.core.constants import is_st

        assert is_st("*ST国华") is True
        assert is_st("ST测试") is True
        assert is_st("SST样本") is True
        assert is_st("best科技") is False
        assert is_st("Stable医疗") is False


class TestTradeRecord:
    def test_net_amount_buy(self) -> None:
        trade = TradeRecord(
            symbol="000001.SZ", side="buy", price=10.0,
            quantity=100, amount=1000.0, commission=5.0,
            date=date(2025, 6, 1),
        )
        assert trade.net_amount == -(1000.0 + 5.0)

    def test_net_amount_sell(self) -> None:
        trade = TradeRecord(
            symbol="000001.SZ", side="sell", price=11.0,
            quantity=100, amount=1100.0, commission=5.5,
            date=date(2025, 6, 2),
        )
        assert trade.net_amount == 1100.0 - 5.5


class TestFinancialStatement:
    def test_fields(self) -> None:
        stmt = FinancialStatement(
            symbol="000001.SZ",
            report_date=date(2025, 3, 31),
            publish_date=date(2025, 4, 15),
            revenue=1e9, net_profit=1e8, total_assets=1e10,
            total_equity=5e9, eps=1.5, roe=0.15,
            pe_ratio=10.0, pb_ratio=1.2, ps_ratio=2.0,
        )
        assert stmt.eps == 1.5
        assert stmt.pe_ratio == 10.0


# ── Cache ─────────────────────────────────────────────────────

class TestDataCache:
    @pytest.fixture
    def cache(self, tmp_path: Path) -> None:
        """Create a cache with long TTL so tests don't expire."""
        from src.data.cache import DataCache
        return DataCache(
            cache_dir=tmp_path / "cache",
            ttl_days={"bars": 365, "stock_list": 365, "financials": 365},
        )

    def test_write_and_read_bars(self, cache) -> None:
        from config.settings import reset_settings
        reset_settings()

        df = pd.DataFrame({
            "date": [date(2025, 1, 1), date(2025, 1, 2)],
            "open": [10.0, 10.1],
            "high": [10.5, 10.6],
            "low": [9.5, 9.6],
            "close": [10.2, 10.3],
            "volume": [1_000_000, 1_100_000],
            "amount": [10_200_000, 11_330_000],
            "adjusted_close": [10.2, 10.3],
        })

        cache.write_bars(df, "000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        result = cache.read_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))

        assert result is not None
        assert len(result) == 2
        assert result["close"].tolist() == [10.2, 10.3]

    def test_cache_miss_returns_none(self, cache) -> None:
        from config.settings import reset_settings
        reset_settings()

        result = cache.read_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        assert result is None

    def test_ttl_expiration(self, tmp_path: Path) -> None:
        import os

        from config.settings import reset_settings
        from src.data.cache import DataCache
        reset_settings()

        cache = DataCache(
            cache_dir=tmp_path / "cache2",
            ttl_days={"bars": 1, "stock_list": 365, "financials": 365},
        )

        df = pd.DataFrame({
            "date": [date(2025, 1, 1)],
            "open": [10.0], "high": [10.5], "low": [9.5],
            "close": [10.2], "volume": [1_000_000],
            "amount": [10_200_000], "adjusted_close": [10.2],
        })
        cache.write_bars(df, "000001.SZ", date(2025, 1, 1), date(2025, 1, 31))

        # Backdate the file by 2 days so TTL is expired
        path = cache._bars_path("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        old_time = time.time() - 2 * 86400
        os.utime(path, (old_time, old_time))

        result = cache.read_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        assert result is None

    def test_write_and_read_stock_list(self, cache) -> None:
        from config.settings import reset_settings
        reset_settings()

        df = pd.DataFrame({
            "symbol": ["000001.SZ", "600519.SH"],
            "code": ["000001", "600519"],
            "name": ["平安银行", "贵州茅台"],
        })
        cache.write_stock_list(df)
        result = cache.read_stock_list()

        assert result is not None
        assert len(result) == 2
        assert result.iloc[0]["symbol"] == "000001.SZ"

    def test_clear_all(self, cache) -> None:
        from config.settings import reset_settings
        reset_settings()

        df = pd.DataFrame({
            "date": [date(2025, 1, 1)],
            "open": [10.0], "high": [10.5], "low": [9.5],
            "close": [10.2], "volume": [1_000_000],
            "amount": [10_200_000], "adjusted_close": [10.2],
        })
        cache.write_bars(df, "000001.SZ", date(2025, 1, 1), date(2025, 1, 31))

        cache.clear()
        result = cache.read_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        assert result is None

    def test_clear_bars_only(self, cache) -> None:
        from config.settings import reset_settings
        reset_settings()

        df = pd.DataFrame({
            "date": [date(2025, 1, 1)],
            "open": [10.0], "high": [10.5], "low": [9.5],
            "close": [10.2], "volume": [1_000_000],
            "amount": [10_200_000], "adjusted_close": [10.2],
        })
        cache.write_bars(df, "000001.SZ", date(2025, 1, 1), date(2025, 1, 31))

        cache.clear("bars")
        assert cache.read_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31)) is None


# ── Aggregator ────────────────────────────────────────────────

class TestDataAggregator:
    def test_fallback_to_second_source(self, tmp_path: Path) -> None:
        from src.data.aggregator import DataAggregator
        from src.data.sina_source import SinaSource
        from config.settings import reset_settings
        reset_settings()

        # Create aggregator with SinaSource as primary
        agg = DataAggregator([SinaSource(rate_limit=0.0)])

        # Override cache to use temp dir
        agg.cache = MagicMock()
        agg.cache.read_bars.return_value = None

        # SinaSource.fetch_bars returns empty (no real network in test)
        result = agg.get_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        # Sina will try network; if it fails, returns empty DataFrame
        assert isinstance(result, pd.DataFrame)

    def test_cache_hit_returns_cached(self) -> None:
        from src.data.aggregator import DataAggregator
        from src.data.sina_source import SinaSource
        from config.settings import reset_settings
        reset_settings()

        agg = DataAggregator([SinaSource(rate_limit=0.0)])

        cached_df = pd.DataFrame({
            "date": [date(2025, 1, 1)],
            "open": [10.0], "high": [10.5], "low": [9.5],
            "close": [10.2], "volume": [1_000_000],
            "amount": [10_200_000], "adjusted_close": [10.2],
        })

        with patch.object(agg.cache, "read_bars", return_value=cached_df):
            result = agg.get_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))

        assert len(result) == 1
        assert result.iloc[0]["close"] == 10.2

    def test_bars_prefer_clickhouse_source_over_stale_cache(self) -> None:
        from src.data.aggregator import DataAggregator

        class ClickHouseLikeSource:
            name = "clickhouse"

            def fetch_bars(self, symbol, start, end, frequency="daily"):
                return pd.DataFrame({
                    "date": [start],
                    "symbol": [symbol],
                    "open": [10.0],
                    "high": [10.5],
                    "low": [9.8],
                    "close": [10.2],
                    "volume": [1_000_000],
                    "amount": [10_200_000],
                    "adjusted_close": [10.2],
                })

        agg = DataAggregator([ClickHouseLikeSource()])
        agg.cache = MagicMock()
        agg.cache.read_bars.return_value = pd.DataFrame({
            "date": [date(2026, 6, 15)],
            "symbol": ["000001.SZ"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1],
            "amount": [1],
            "adjusted_close": [1.0],
        })

        result = agg.get_bars("000001.SZ", date(2026, 6, 15), date(2026, 6, 15))

        assert result.iloc[0]["close"] == 10.2
        agg.cache.read_bars.assert_not_called()
        agg.cache.write_bars.assert_not_called()

    def test_all_sources_failed_returns_empty(self) -> None:
        from src.data.aggregator import DataAggregator
        from config.settings import reset_settings
        reset_settings()

        mock_source = MagicMock()
        mock_source.name = "mock"
        mock_source.fetch_bars.side_effect = Exception("network error")

        agg = DataAggregator([mock_source])
        agg.cache = MagicMock()
        agg.cache.read_bars.return_value = None

        result = agg.get_bars("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))
        assert result.empty

    def test_get_csi300_symbols(self) -> None:
        from src.data.aggregator import DataAggregator
        from config.settings import reset_settings
        reset_settings()

        mock_source = MagicMock()
        mock_source.name = "mock"
        mock_source.fetch_stock_list.return_value = [
            MagicMock(symbol="600519.SH", code="600519", name="贵州茅台"),
            MagicMock(symbol="000001.SZ", code="000001", name="平安银行"),
            MagicMock(symbol="300750.SZ", code="300750", name="宁德时代"),
        ]

        agg = DataAggregator([mock_source])
        agg.cache = MagicMock()
        agg.cache.read_stock_list.return_value = None

        symbols = agg.get_csi300_symbols()
        # Should include 600xxx and 000xxx, but not 300xxx (ChiNext)
        assert "600519.SH" in symbols
        assert "000001.SZ" in symbols
        assert "300750.SZ" not in symbols


    def test_default_sources_include_clickhouse_when_env_is_configured(self, monkeypatch, tmp_path: Path) -> None:
        from src.data.aggregator import DataAggregator
        from config.settings import reset_settings
        reset_settings()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STOCK_CLICKHOUSE_HOST", "<PRIVATE_CLICKHOUSE_HOST>")
        monkeypatch.setenv("STOCK_CLICKHOUSE_USER", "default")
        monkeypatch.setenv("STOCK_CLICKHOUSE_PASSWORD", "[REDACTED]")
        monkeypatch.setenv("STOCK_CLICKHOUSE_DATABASE", "stock")

        agg = DataAggregator()

        assert [source.name for source in agg.sources[:3]] == ["clickhouse", "tencent", "sina"]

    def test_stock_list_prefers_clickhouse_source_over_stale_cache(self) -> None:
        from src.data.aggregator import DataAggregator
        from src.data.models import StockInfo

        class ClickHouseLikeSource:
            name = "clickhouse"

            def fetch_stock_list(self):
                return [StockInfo(symbol="600000.SH", code="600000", name="浦发银行")]

        agg = DataAggregator([ClickHouseLikeSource()])
        agg.cache = MagicMock()
        agg.cache.read_stock_list.return_value = pd.DataFrame([
            {"symbol": "000001.SZ", "code": "000001", "name": "旧缓存"}
        ])

        stocks = agg.get_stock_list()

        assert stocks[0].symbol == "600000.SH"
        agg.cache.read_stock_list.assert_not_called()
        agg.cache.write_stock_list.assert_not_called()



def test_sina_intraday_bars_returns_dataframe() -> None:
    """Test that Sina intraday API returns a DataFrame."""
    from src.data.sina_source import SinaSource
    from config.settings import reset_settings
    reset_settings()

    source = SinaSource(rate_limit=0.0)
    df = source.fetch_intraday_bars(
        symbol="000001.SZ",
        trade_date=date(2025, 6, 3),
        frequency="5m",
    )

    assert isinstance(df, pd.DataFrame)


def test_sina_intraday_bars_uses_configured_history_window(monkeypatch) -> None:
    from src.data.sina_source import SinaSource

    calls = []

    def fake_fetch(symbol, trade_date, frequency, datalen=1000):
        calls.append((symbol, trade_date, frequency, datalen))
        return pd.DataFrame([{
            "datetime": pd.Timestamp("2026-04-01 14:30:00"),
            "time": pd.Timestamp("2026-04-01 14:30:00").time(),
            "symbol": symbol,
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 1000,
            "amount": 0.0,
        }])

    monkeypatch.setattr("src.data.intraday_source.fetch_intraday_bars", fake_fetch)
    source = SinaSource(rate_limit=0.0, intraday_datalen=10000)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 4, 1), "5m")

    assert not result.empty
    assert calls == [("000001.SZ", date(2026, 4, 1), "5m", 10000)]


def test_sina_intraday_bars_batch_uses_configured_history_window(monkeypatch) -> None:
    from src.data.sina_source import SinaSource

    calls = []

    def fake_fetch(symbol, trade_date, frequency, datalen=1000):
        calls.append((symbol, trade_date, frequency, datalen))
        return pd.DataFrame([{
            "datetime": pd.Timestamp("2026-04-01 14:30:00"),
            "time": pd.Timestamp("2026-04-01 14:30:00").time(),
            "symbol": symbol,
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 1000,
            "amount": 0.0,
        }])

    monkeypatch.setattr("src.data.intraday_source.fetch_intraday_bars", fake_fetch)
    source = SinaSource(rate_limit=0.0, intraday_datalen=10000, intraday_workers=2)

    result = source.fetch_intraday_bars_batch(["000001.SZ", "600000.SH"], date(2026, 4, 1), "5m")

    assert sorted(result["symbol"].unique().tolist()) == ["000001.SZ", "600000.SH"]
    assert sorted(calls) == [
        ("000001.SZ", date(2026, 4, 1), "5m", 10000),
        ("600000.SH", date(2026, 4, 1), "5m", 10000),
    ]


def test_sina_intraday_bars_window_uses_configured_history_window(monkeypatch) -> None:
    from src.data.sina_source import SinaSource

    calls = []

    def fake_fetch(symbol, start, end, frequency, datalen=1000):
        calls.append((symbol, start, end, frequency, datalen))
        return pd.DataFrame([{
            "datetime": pd.Timestamp("2026-04-01 14:30:00"),
            "time": pd.Timestamp("2026-04-01 14:30:00").time(),
            "symbol": symbol,
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 1000,
            "amount": 0.0,
        }])

    monkeypatch.setattr("src.data.intraday_source.fetch_intraday_bars_range", fake_fetch)
    source = SinaSource(rate_limit=0.0, intraday_datalen=10000, intraday_workers=2)

    result = source.fetch_intraday_bars_window(["000001.SZ", "600000.SH"], date(2026, 1, 8), date(2026, 6, 17), "5m")

    assert sorted(result["symbol"].unique().tolist()) == ["000001.SZ", "600000.SH"]
    assert sorted(calls) == [
        ("000001.SZ", date(2026, 1, 8), date(2026, 6, 17), "5m", 10000),
        ("600000.SH", date(2026, 1, 8), date(2026, 6, 17), "5m", 10000),
    ]


def test_data_aggregator_get_intraday_bars_uses_source_method() -> None:
    from src.data.aggregator import DataAggregator

    class IntradaySource:
        name = "fake"

        def fetch_intraday_bars(self, symbol, trade_date, frequency="5m"):
            return pd.DataFrame([{
                "datetime": pd.Timestamp("2025-06-03 14:30"),
                "time": pd.Timestamp("2025-06-03 14:30").time(),
                "symbol": symbol,
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000,
                "amount": 10_100,
            }])

    agg = DataAggregator([IntradaySource()])

    result = agg.get_intraday_bars("000001.SZ", date(2025, 6, 3), frequency="5m")

    assert not result.empty
    assert result.iloc[0]["symbol"] == "000001.SZ"


def test_data_aggregator_get_intraday_bars_batch_uses_source_batch_method() -> None:
    from src.data.aggregator import DataAggregator

    class BatchIntradaySource:
        name = "fake"

        def __init__(self):
            self.batch_calls = []
            self.single_calls = []

        def fetch_intraday_bars_batch(self, symbols, trade_date, frequency="5m"):
            self.batch_calls.append((symbols, trade_date, frequency))
            return pd.DataFrame([
                {
                    "datetime": pd.Timestamp("2025-06-03 14:30"),
                    "time": pd.Timestamp("2025-06-03 14:30").time(),
                    "symbol": symbols[0],
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10_100,
                }
            ])

        def fetch_intraday_bars(self, symbol, trade_date, frequency="5m"):
            self.single_calls.append(symbol)
            return pd.DataFrame()

    source = BatchIntradaySource()
    agg = DataAggregator([source])

    result = agg.get_intraday_bars_batch(["000001.SZ", "600519.SH"], date(2025, 6, 3), frequency="5m")

    assert not result.empty
    assert source.batch_calls == [(["000001.SZ", "600519.SH"], date(2025, 6, 3), "5m")]
    assert source.single_calls == []


def test_akshare_source_fetches_intraday_bars(monkeypatch) -> None:
    from src.data.akshare_source import AKShareSource

    fake_akshare = types.SimpleNamespace(
        stock_zh_a_hist_min_em=lambda **kwargs: pd.DataFrame(
            [
                {
                    "时间": "2026-06-12 14:30:00",
                    "开盘": 10.0,
                    "收盘": 10.2,
                    "最高": 10.3,
                    "最低": 9.9,
                    "成交量": 1000,
                    "成交额": 10200.0,
                },
                {
                    "时间": "2026-06-11 14:30:00",
                    "开盘": 9.8,
                    "收盘": 9.9,
                    "最高": 10.0,
                    "最低": 9.7,
                    "成交量": 900,
                    "成交额": 9000.0,
                },
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    source = AKShareSource(rate_limit=0.0)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 12), "5m")

    assert len(result) == 1
    assert result.iloc[0]["symbol"] == "000001.SZ"
    assert result.iloc[0]["time"] == pd.Timestamp("2026-06-12 14:30").time()
    assert result.iloc[0]["close"] == 10.2


def test_sqlite_stock_data_source_reads_stock_list_and_daily_bars(tmp_path) -> None:
    import sqlite3

    from src.data.sqlite_source import SQLiteStockDataSource

    db_path = tmp_path / "stock.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "create table stocks (symbol text, name text, industry text, market text, list_date text, updated_at text)"
    )
    conn.execute(
        "create table daily_kline (symbol text, date text, open real, high real, low real, close real, volume real, amount real, amplitude real, pct_change real, change real, turnover real)"
    )
    conn.execute(
        "insert into stocks values ('000001', '平安银行', '银行', 'SZ', '1991-04-03', '2026-06-12')"
    )
    conn.execute(
        "insert into daily_kline values ('000001', '2026-06-11', 10, 10.5, 9.9, 10.2, 1000, 10200, 0, 0, 0, 0)"
    )
    conn.execute(
        "insert into daily_kline values ('000001', '2026-06-12', 10.2, 10.8, 10.1, 10.6, 1200, 12600, 0, 0, 0, 0)"
    )
    conn.commit()
    conn.close()

    source = SQLiteStockDataSource(db_path)

    stocks = source.fetch_stock_list()
    bars = source.fetch_bars("000001.SZ", date(2026, 6, 11), date(2026, 6, 12))

    assert stocks == [StockInfo(symbol="000001.SZ", code="000001", name="平安银行", industry="银行", list_date=date(1991, 4, 3))]
    assert bars["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert bars["date"].tolist() == [date(2026, 6, 11), date(2026, 6, 12)]
    assert bars["close"].tolist() == [10.2, 10.6]
    assert bars["adjusted_close"].tolist() == [10.2, 10.6]


def test_sqlite_stock_data_source_reads_5m_intraday_bars(tmp_path) -> None:
    import sqlite3

    from src.data.sqlite_source import SQLiteStockDataSource

    db_path = tmp_path / "stock.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "create table minute5_kline (symbol text, datetime text, open real, high real, low real, close real, volume real, amount real)"
    )
    conn.execute(
        "insert into minute5_kline values ('000001', '2026-06-12 14:30:00', 10, 10.2, 9.9, 10.1, 1000, 10100)"
    )
    conn.execute(
        "insert into minute5_kline values ('000001', '2026-06-12 14:35:00', 10.1, 10.3, 10.0, 10.2, 1200, 12240)"
    )
    conn.commit()
    conn.close()

    source = SQLiteStockDataSource(db_path)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 12), "5m")

    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert result.iloc[0]["time"] == pd.Timestamp("2026-06-12 14:30").time()
    assert result.iloc[-1]["close"] == 10.2
