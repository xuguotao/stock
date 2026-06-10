"""Tail session breakout factor.

Combines daily breakout, trend, and volume confirmation into
a single factor value. Higher value = stronger tail session signal.

Usage:
    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    values = factor.compute(bars)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.strategy.base import Factor


class TailSessionFactor(Factor):
    """尾盘突破因子。

    Factor value = 1.0 (breakout + trend + volume confirmed)
                 = 0.7 (breakout + trend)
                 = 0.4 (breakout only)
                 = 0.0 (no breakout)
    """

    name = "tail_session"
    description = "Tail session breakout confirmation factor"

    def __init__(
        self,
        breakout_window: int = 20,
        trend_window: int = 5,
        volume_ratio_threshold: float = 1.2,
    ):
        self.breakout_window = breakout_window
        self.trend_window = trend_window
        self.volume_ratio_threshold = volume_ratio_threshold

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute tail session factor values."""
        if bars.empty:
            return pd.DataFrame(columns=[self.name])

        frame = bars.sort_index().copy()
        grouped = frame.groupby(level="symbol", group_keys=False)

        close = frame["close"]
        prev_high = grouped["close"].apply(
            lambda s: s.shift(1).rolling(self.breakout_window, min_periods=self.breakout_window).max()
        )
        breakout = close > prev_high

        trend = grouped["close"].apply(
            lambda s: s.rolling(self.trend_window, min_periods=self.trend_window).apply(
                _linear_slope,
                raw=True,
            )
        ) > 0

        if "volume" in frame.columns:
            avg_volume = grouped["volume"].apply(
                lambda s: s.shift(1).rolling(20, min_periods=20).mean()
            )
            volume = (frame["volume"] > avg_volume * self.volume_ratio_threshold).fillna(False)
        else:
            volume = pd.Series(False, index=frame.index)

        values = pd.Series(0.0, index=frame.index, name=self.name)
        values.loc[breakout] = 0.4
        values.loc[breakout & trend] = 0.7
        values.loc[breakout & trend & volume] = 1.0
        return values.to_frame()


def _linear_slope(values: np.ndarray) -> float:
    x = np.arange(len(values), dtype=float)
    slope, _ = np.polyfit(x, values, 1)
    return float(slope)
