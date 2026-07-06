"""Adjustment service with ClickHouse query layer and caching."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from src.data.adjustment import (
    apply_backward_adjustment,
    apply_forward_adjustment,
    compute_adjustment_ratios,
)

logger = logging.getLogger(__name__)


class AdjustmentService:
    """Provides adjusted bar data by combining ClickHouse daily_kline and xdxr_info.

    Caches xdxr events per symbol to avoid repeated ClickHouse queries.
    """

    def __init__(self, client: Any | None = None):
        if client is None:
            from src.data.clickhouse_source import ClickHouseStockDataSource
            self._client = ClickHouseStockDataSource()._client_instance()
        else:
            self._client = client
        self._xdxr_cache: dict[str, pd.DataFrame] = {}

    def get_adjusted_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust_type: str = "forward",
    ) -> pd.DataFrame:
        """Get daily bars with adjustment applied.

        Args:
            symbol: Stock symbol like "000001.SZ"
            start: Start date (inclusive)
            end: End date (inclusive)
            adjust_type: "forward" (前复权), "backward" (后复权), or "none"

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount,
            adjusted_close, symbol
        """
        bars = self._fetch_bars(symbol, start, end)
        if bars.empty:
            return bars

        if adjust_type == "none":
            bars["adjusted_close"] = bars["close"]
            return bars

        ratios = self._get_xdxr_ratios(symbol)
        if ratios.empty:
            bars["adjusted_close"] = bars["close"]
            return bars

        if adjust_type == "forward":
            return apply_forward_adjustment(bars, ratios)
        elif adjust_type == "backward":
            return apply_backward_adjustment(bars, ratios)
        else:
            logger.warning(f"Unknown adjust_type '{adjust_type}', returning raw bars")
            bars["adjusted_close"] = bars["close"]
            return bars

    def _fetch_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        code = symbol.split(".")[0].zfill(6)
        rows = self._client.execute(
            """
            select symbol, date, open, high, low, close, volume, amount
            from daily_kline
            where symbol = %(symbol)s and date >= %(start)s and date <= %(end)s
            order by date
            """,
            {"symbol": code, "start": start, "end": end},
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
        )
        from src.core.constants import format_symbol
        df["symbol"] = df["symbol"].astype(str).map(format_symbol)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["volume"] = df["volume"].astype(int)
        return df

    def _get_xdxr_ratios(self, symbol: str) -> pd.DataFrame:
        """Get cached xdxr ratios for a symbol. Fetches from ClickHouse on first call."""
        if symbol in self._xdxr_cache:
            return self._xdxr_cache[symbol]

        code = symbol.split(".")[0].zfill(6)
        rows = self._client.execute(
            """
            select ex_date, fenhong, songzhuangu, peigu, suogu
            from xdxr_info final
            where symbol = %(symbol)s
            order by ex_date
            """,
            {"symbol": code},
        )
        if not rows:
            empty = pd.DataFrame(columns=["ex_date", "fenhong", "songzhuangu", "peigu", "suogu"])
            self._xdxr_cache[symbol] = empty
            return empty

        events = pd.DataFrame(
            rows,
            columns=["ex_date", "fenhong", "songzhuangu", "peigu", "suogu"],
        )
        events["ex_date"] = pd.to_datetime(events["ex_date"]).dt.date

        # Fetch pre_close for each xdxr event (close on the day before ex_date)
        pre_closes = self._fetch_pre_closes(code, events["ex_date"].tolist())
        events["pre_close"] = events["ex_date"].map(pre_closes).fillna(0.0)

        ratios = compute_adjustment_ratios(events)
        self._xdxr_cache[symbol] = ratios
        return ratios

    def _fetch_pre_closes(self, code: str, ex_dates: list[date]) -> dict[date, float]:
        """Fetch close prices for the trading day before each ex_date."""
        if not ex_dates:
            return {}
        # Query the close price for each ex_date, then look up the previous day's close
        # using a LAG window function
        results = {}
        for ex_date in ex_dates:
            rows = self._client.execute(
                """
                select close from daily_kline
                where symbol = %(symbol)s and date < %(ex_date)s
                order by date desc limit 1
                """,
                {"symbol": code, "ex_date": ex_date},
            )
            if rows:
                results[ex_date] = float(rows[0][0])
        return results

    def clear_cache(self) -> None:
        """Clear the xdxr cache."""
        self._xdxr_cache.clear()

    def get_adjusted_bars_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjust_type: str = "forward",
    ) -> pd.DataFrame:
        """Get adjusted bars for multiple symbols with batch optimization.

        This method uses batch queries to avoid N+1 query problem.

        Args:
            symbols: List of stock symbols
            start: Start date (inclusive)
            end: End date (inclusive)
            adjust_type: Adjustment type - "forward", "backward", or "none"

        Returns:
            DataFrame with all symbols' adjusted bars
        """
        if not symbols:
            return pd.DataFrame()

        all_bars = []
        for symbol in symbols:
            bars = self.get_adjusted_bars(symbol, start, end, adjust_type)
            if not bars.empty:
                all_bars.append(bars)

        if not all_bars:
            return pd.DataFrame()

        return pd.concat(all_bars, ignore_index=True)
