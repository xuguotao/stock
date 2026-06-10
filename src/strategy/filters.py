"""Stock pool filters for the tail session strategy."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from src.core.constants import is_st


@runtime_checkable
class Filter(Protocol):
    """Protocol for stock pool filters."""

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        **kwargs,
    ) -> list[str]:
        """Return list of symbols that pass the filter."""
        ...


class DailyBreakoutFilter:
    """筛选创 N 日新高的股票。

    A stock passes if its latest close is higher than
    the maximum close in the previous `breakout_window` days.
    """

    def __init__(self, breakout_window: int = 20):
        self.breakout_window = breakout_window

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        mode: str = "breakout",
        **kwargs,
    ) -> list[str]:
        """Filter symbols.

        Args:
            mode: "breakout" (20-day high) or "ma_cross" (MA5 > MA20)
        """
        if bars.empty:
            return []

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        passing = []

        for symbol in symbols:
            try:
                sym_bars = bars.xs(symbol, level="symbol")
            except KeyError:
                continue

            closes = sym_bars["close"].dropna()

            if mode == "ma_cross":
                if len(closes) < 21:
                    continue
                ma5 = closes.tail(5).mean()
                ma20 = closes.tail(20).mean()
                if ma5 > ma20:
                    passing.append(symbol)
            else:
                if len(closes) < self.breakout_window + 1:
                    continue
                latest = closes.iloc[-1]
                prev_high = closes.iloc[-(self.breakout_window + 1): -1].max()
                if latest > prev_high:
                    passing.append(symbol)

        return passing


class DailyTrendFilter:
    """筛选近 N 日收盘价呈上升趋势的股票。

    Uses linear regression slope > 0 as the criterion.
    """

    def __init__(self, trend_window: int = 5, min_slope: float = 0.0):
        self.trend_window = trend_window
        self.min_slope = min_slope

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        **kwargs,
    ) -> list[str]:
        """Filter symbols with positive trend slope."""
        if bars.empty:
            return []

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        passing = []

        for symbol in symbols:
            try:
                sym_bars = bars.xs(symbol, level="symbol")
            except KeyError:
                continue

            closes = sym_bars["close"].dropna()
            if len(closes) < self.trend_window:
                continue

            recent = closes.tail(self.trend_window).values
            x = np.arange(len(recent), dtype=float)
            slope, _ = np.polyfit(x, recent, 1)

            if slope > self.min_slope:
                passing.append(symbol)

        return passing


class StockPoolFilter:
    """综合股票池过滤：ST、次新股、流动性、涨停。"""

    def __init__(
        self,
        min_list_days: int = 60,
        min_avg_amount: float = 5_000_000,
        limit_up_pct: float = 0.10,
    ):
        self.min_list_days = min_list_days
        self.min_avg_amount = min_avg_amount
        self.limit_up_pct = limit_up_pct

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        stock_info: dict | None = None,
        **kwargs,
    ) -> list[str]:
        """Apply all stock pool filters."""
        if bars.empty:
            return []

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        passing = []

        for symbol in symbols:
            if not self._passes(symbol, bars, trade_date, stock_info):
                continue
            passing.append(symbol)

        return passing

    def _passes(
        self,
        symbol: str,
        bars: pd.DataFrame,
        trade_date: date,
        stock_info: dict | None,
    ) -> bool:
        """Check all conditions for a single symbol."""
        try:
            sym_bars = bars.xs(symbol, level="symbol")
        except KeyError:
            return False

        # ST check
        if stock_info and symbol in stock_info:
            name = stock_info[symbol].get("name", "")
            if is_st(name):
                return False

            # New stock check
            list_date = stock_info[symbol].get("list_date")
            if list_date and isinstance(list_date, date):
                days_listed = (trade_date - list_date).days
                if days_listed < self.min_list_days:
                    return False

        # Liquidity check (avg daily amount)
        if "amount" in sym_bars.columns:
            avg_amount = sym_bars["amount"].tail(20).mean()
            if avg_amount < self.min_avg_amount:
                return False

        # Limit-up check (today's change too large)
        closes = sym_bars["close"].dropna()
        if len(closes) >= 2:
            change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
            if change >= self.limit_up_pct:
                return False

        return True
