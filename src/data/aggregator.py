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
from pathlib import Path

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
            sources = []
            from src.data.clickhouse_source import ClickHouseStockDataSource
            sources.append(ClickHouseStockDataSource.from_env() or ClickHouseStockDataSource())
            from src.data.tencent_source import TencentQuoteSource
            sources.append(TencentQuoteSource(rate_limit=0.2))
            try:
                from src.data.akshare_source import AKShareSource
                sources.extend([SinaSource(rate_limit=0.2), AKShareSource(rate_limit=0.3)])
            except ImportError:
                sources.append(SinaSource(rate_limit=0.2))

        self.sources = sources
        self.cache = DataCache()

    def _prefer_source_over_cache(self) -> bool:
        """Return true when the first source should be treated as authoritative."""
        return bool(
            self.sources and getattr(self.sources[0], "name", "") == "clickhouse"
        )

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
        prefer_source = self._prefer_source_over_cache()
        # Check cache
        if use_cache and not prefer_source:
            cached = self.cache.read_bars(symbol, start, end)
            if cached is not None and not cached.empty:
                return cached

        # Try each source
        for source in self.sources:
            try:
                df = source.fetch_bars(symbol, start, end, frequency)
                if df is not None and not df.empty:
                    # Cache result
                    if use_cache and not prefer_source:
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
        prefer_source = self._prefer_source_over_cache()
        if use_cache and not prefer_source:
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
                    if use_cache and not prefer_source:
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

    def rank_liquid_symbols(
        self,
        start: date,
        end: date,
        limit: int,
        min_bars: int,
        min_end_date: date | None = None,
    ) -> list[dict]:
        """Rank liquid symbols through configured authoritative sources."""
        for source in self.sources:
            ranker = getattr(source, "rank_liquid_symbols", None)
            if ranker is None:
                continue
            try:
                ranking = ranker(
                    start=start,
                    end=end,
                    limit=limit,
                    min_bars=min_bars,
                    min_end_date=min_end_date,
                )
                if ranking:
                    return ranking
            except Exception as e:
                logger.warning(f"Source {source.name} liquid ranking failed: {e}")
                continue
        return []

    def get_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        """Get intraday bars with fallback across configured sources."""
        for source in self.sources:
            fetcher = getattr(source, "fetch_intraday_bars", None)
            if fetcher is None:
                continue
            try:
                df = fetcher(symbol, trade_date, frequency)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"Source {source.name} intraday failed for {symbol}: {e}")
                continue

        return pd.DataFrame()

    def get_intraday_bars_batch(
        self,
        symbols: list[str],
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        """Get intraday bars for multiple symbols, preferring source-native batch reads."""
        if not symbols:
            return pd.DataFrame()
        for source in self.sources:
            batch_fetcher = getattr(source, "fetch_intraday_bars_batch", None)
            if batch_fetcher is not None:
                try:
                    df = batch_fetcher(symbols, trade_date, frequency)
                    if df is not None and not df.empty:
                        return df
                except Exception as e:
                    logger.warning(f"Source {source.name} intraday batch failed: {e}")
                    continue

        frames = [self.get_intraday_bars(symbol, trade_date, frequency) for symbol in symbols]
        frames = [frame for frame in frames if frame is not None and not frame.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

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
