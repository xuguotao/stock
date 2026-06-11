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
        min_close_above_ma20: bool = False,
        max_daily_return: float | None = None,
        min_turnover_value: float | None = None,
        min_market_breadth_above_ma20: float | None = None,
    ):
        self.breakout_window = breakout_window
        self.trend_window = trend_window
        self.volume_ratio_threshold = volume_ratio_threshold
        self.min_close_above_ma20 = min_close_above_ma20
        self.max_daily_return = max_daily_return
        self.min_turnover_value = min_turnover_value
        self.min_market_breadth_above_ma20 = min_market_breadth_above_ma20

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

        quality = pd.Series(True, index=frame.index)
        if self.min_close_above_ma20:
            ma20 = grouped["close"].apply(lambda s: s.rolling(20, min_periods=20).mean())
            quality &= (close > ma20).fillna(False)
        if self.max_daily_return is not None:
            daily_return = grouped["close"].pct_change()
            quality &= (daily_return <= self.max_daily_return).fillna(False)
        if self.min_turnover_value is not None:
            quality &= (_traded_value(frame) >= self.min_turnover_value).fillna(False)
        if self.min_market_breadth_above_ma20 is not None:
            ma20 = grouped["close"].apply(lambda s: s.rolling(20, min_periods=20).mean())
            breadth = (close > ma20).groupby(level="date").mean()
            allowed_dates = breadth[breadth >= self.min_market_breadth_above_ma20].index
            quality &= pd.Series(frame.index.get_level_values("date").isin(allowed_dates), index=frame.index)

        values = pd.Series(0.0, index=frame.index, name=self.name)
        values.loc[breakout & quality] = 0.4
        values.loc[breakout & trend & quality] = 0.7
        values.loc[breakout & trend & volume & quality] = 1.0
        return values.to_frame()


def _linear_slope(values: np.ndarray) -> float:
    x = np.arange(len(values), dtype=float)
    slope, _ = np.polyfit(x, values, 1)
    return float(slope)


def _traded_value(frame: pd.DataFrame) -> pd.Series:
    if "amount" in frame.columns:
        amount = pd.to_numeric(frame["amount"], errors="coerce").fillna(0)
        if (amount > 0).any():
            return amount
    close = pd.to_numeric(frame["close"], errors="coerce").fillna(0)
    volume = pd.to_numeric(frame.get("volume", 0), errors="coerce").fillna(0)
    return close * volume
