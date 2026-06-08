"""Trend factor.

Based on moving average crossover signals.
When short-term MA > long-term MA, factor is positive.
The wider the gap, the stronger the signal.

Usage:
    factor = TrendFactor(short_window=5, long_window=20)
    values = factor.compute(bars)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.strategy.base import Factor


class TrendFactor(Factor):
    """MA crossover trend factor.

    Factor value = (close - long_ma) / close
    Positive when price is above long-term MA.
    """

    name = "trend"
    description = "Moving average crossover trend signal"

    def __init__(self, short_window: int = 5, long_window: int = 20):
        self.short_window = short_window
        self.long_window = long_window

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute trend factor."""
        short_w = kwargs.get("short_window", self.short_window)
        long_w = kwargs.get("long_window", self.long_window)

        close = bars["close"]
        long_ma = close.groupby(level=1).rolling(long_w, min_periods=1).mean()
        long_ma.index = close.index

        # Factor: how far price is above/below long-term MA
        factor = (close - long_ma) / close.replace(0, float("nan"))
        factor = factor.fillna(0)

        result = factor.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result


class MACrossSignal(Factor):
    """Pure MA crossover signal (binary: +1 if golden cross, -1 if death cross)."""

    name = "ma_cross"
    description = "Golden/death cross signal"

    def __init__(self, short_window: int = 5, long_window: int = 20):
        self.short_window = short_window
        self.long_window = long_window

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        short_w = kwargs.get("short_window", self.short_window)
        long_w = kwargs.get("long_window", self.long_window)

        close = bars["close"]
        short_ma = close.groupby(level=1).rolling(short_w, min_periods=1).mean()
        long_ma = close.groupby(level=1).rolling(long_w, min_periods=1).mean()
        short_ma.index = close.index
        long_ma.index = close.index

        signal = (short_ma > long_ma).astype(float) * 2 - 1  # +1 or -1

        result = signal.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result
