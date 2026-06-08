"""Mean reversion factor.

Based on Bollinger Band z-score.
When price is far below the mean, factor is high (expect reversion up).
When price is far above the mean, factor is low (expect reversion down).

Usage:
    factor = MeanReversionFactor(window=20, std_dev=2.0)
    values = factor.compute(bars)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.strategy.base import Factor


class MeanReversionFactor(Factor):
    """Bollinger Band z-score mean reversion factor.

    Factor = -(close - ma) / std
    Negative z-score (price below mean) gives positive factor.
    """

    name = "mean_reversion"
    description = "Bollinger Band z-score reversion signal"

    def __init__(self, window: int = 20, std_dev: float = 2.0):
        self.window = window
        self.std_dev = std_dev

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute mean reversion factor."""
        window = kwargs.get("window", self.window)

        close = bars["close"]
        ma = close.groupby(level=1).rolling(window, min_periods=1).mean()
        std = close.groupby(level=1).rolling(window, min_periods=1).std()
        ma.index = close.index
        std.index = close.index

        # Z-score: (close - ma) / std
        # Invert: we want positive signal when price is below mean
        zscore = (close - ma) / std.replace(0, float("nan"))
        factor = -zscore  # Invert: below mean = bullish
        factor = factor.fillna(0)

        result = factor.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result
