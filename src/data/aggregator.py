"""Multi-source data aggregator with automatic fallback.

The DataAggregator chains multiple DataSource implementations in priority order.
If the primary source fails, it automatically falls back to the next source.
All data is cached locally after successful fetch.

Usage:
    from src.data.aggregator import DataAggregator
    from src.data.akshare_source import AKShareSource

    agg = DataAggregator([AKShareSource()])
    df = agg.get_bars("000001.SZ", date(2024, 1, 1), date(2024, 12, 31))
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.data.base import DataSourceBase
from src.data.cache import DataCache
from src.data.models import StockInfo

logger = logging.getLogger(__name__)


class DataAggregator:
    """Multi-source data aggregator with caching and fallback."""

    def __init__(self, sources: list[DataSourceBase] | None = None):
        if sources is None:
            # SinaSource works reliably behind proxy; AKShare as fallback
            from src.data.sina_source import SinaSource
            try:
                from src.data.akshare_source import AKShareSource
                sources = [SinaSource(rate_limit=0.2), AKShareSource(rate_limit=0.3)]
            except ImportError:
                sources = [SinaSource(rate_limit=0.2)]

        self.sources = sources
        self.cache = DataCache()

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Get daily bars with cache + fallback.

        Tries cache first, then each data source in priority order.
        """
        # Check cache
        if use_cache:
            cached = self.cache.read_bars(symbol, start, end)
            if cached is not None and not cached.empty:
                return cached

        # Try each source
        for source in self.sources:
            try:
                df = source.fetch_bars(symbol, start, end, frequency)
                if df is not None and not df.empty:
                    # Cache result
                    if use_cache:
                        self.cache.write_bars(df, symbol, start, end)
                    return df
            except Exception as e:
                logger.warning(f"Source {source.name} failed for {symbol}: {e}")
                continue

        logger.error(f"All sources failed for {symbol} ({start} to {end})")
        return pd.DataFrame()

    def get_bars_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        frequency: str = "daily",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Get bars for multiple symbols. Returns MultiIndex (date, symbol)."""
        all_dfs = []
        for sym in symbols:
            df = self.get_bars(sym, start, end, frequency, use_cache)
            if not df.empty:
                all_dfs.append(df)

        if not all_dfs:
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        combined["date"] = pd.to_datetime(combined["date"])
        return combined.set_index(["date", "symbol"])

    def get_stock_list(self, use_cache: bool = True) -> list[StockInfo]:
        """Get stock list with cache."""
        if use_cache:
            cached = self.cache.read_stock_list()
            if cached is not None and not cached.empty:
                return [
                    StockInfo(
                        symbol=row["symbol"],
                        code=row["code"],
                        name=row["name"],
                    )
                    for _, row in cached.iterrows()
                ]

        for source in self.sources:
            try:
                stocks = source.fetch_stock_list()
                if stocks:
                    # Cache
                    if use_cache:
                        df = pd.DataFrame([
                            {"symbol": s.symbol, "code": s.code, "name": s.name}
                            for s in stocks
                        ])
                        self.cache.write_stock_list(df)
                    return stocks
            except Exception as e:
                logger.warning(f"Source {source.name} fetch_stock_list failed: {e}")
                continue

        return []

    def get_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Get real-time quotes."""
        for source in self.sources:
            try:
                df = source.fetch_realtime_quotes(symbols)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"Source {source.name} realtime quotes failed: {e}")
                continue

        return pd.DataFrame()

    def get_symbols_by_board(self, board_prefixes: list[str]) -> list[str]:
        """Filter stock list by board code prefixes."""
        stocks = self.get_stock_list()
        return [
            s.symbol for s in stocks
            if any(s.code.startswith(p) for p in board_prefixes)
        ]

    def get_csi300_symbols(self) -> list[str]:
        """Get CSI 300 constituent symbols.

        For now, returns all main board stocks.
        In production, this would fetch the actual CSI 300 list.
        """
        return self.get_symbols_by_board(["600", "601", "603", "605", "000", "001"])
