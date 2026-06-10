"""Overnight momentum factor.

Measures the gap between previous close and current open.
Higher gap = stronger overnight buying pressure.

Factor = (open_t - close_{t-1}) / close_{t-1}
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.strategy.base import Factor


class OvernightMomentumFactor(Factor):
    name = "overnight_momentum"
    description = "Overnight gap momentum (open vs prev close)"

    def __init__(self, smoothing_window: int = 1):
        self.smoothing_window = smoothing_window

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute overnight momentum factor."""
        close = bars["close"]
        open_price = bars["open"]

        # Gap = (open - prev_close) / prev_close
        prev_close = close.groupby(level=1).shift(1)
        gap = (open_price - prev_close) / prev_close.replace(0, float("nan"))

        # Optional smoothing
        if self.smoothing_window > 1:
            gap = gap.groupby(level=1).rolling(
                self.smoothing_window, min_periods=1
            ).mean()
            if hasattr(gap.index, "names"):
                gap.index = close.index

        result = gap.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result
