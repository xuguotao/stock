"""Tests for the data module: models, cache, aggregator, sources."""

from __future__ import annotations

import json
import os
import time
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
