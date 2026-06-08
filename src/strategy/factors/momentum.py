"""Momentum factor.

Measures price momentum over a lookback window.
Higher return = higher factor value (more bullish).

Usage:
    factor = MomentumFactor(window=60)  # 60-day momentum
    values = factor.compute(bars)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.strategy.base import Factor


class MomentumFactor(Factor):
    """Price momentum: close[t] / close[t-window] - 1."""

    name = "momentum"
    description = "Price momentum over N trading days"

    def __init__(self, window: int = 60):
        self.window = window

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute momentum factor.

        Args:
            bars: MultiIndex DataFrame (date, symbol) with 'close' column.
            **kwargs: Override window via window=<int>.

        Returns:
            DataFrame with momentum values.
        """
        window = kwargs.get("window", self.window)

        close = bars["close"]
        momentum = close.groupby(level=1).pct_change(window)

        result = momentum.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result
