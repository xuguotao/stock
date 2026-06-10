"""Tail session breakout factor.

Combines daily breakout, trend, and volume confirmation into
a single factor value. Higher value = stronger tail session signal.

Usage:
    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    values = factor.compute(bars)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.strategy.base import Factor
from src.strategy.filters import DailyBreakoutFilter, DailyTrendFilter


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

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        dates = bars.index.get_level_values("date").unique().tolist()

        results = []
        for trade_date in dates:
            try:
                day_bars = bars.loc[trade_date]
            except KeyError:
                continue

            if isinstance(day_bars, pd.Series):
                day_bars = day_bars.to_frame().T

            # Get historical bars up to this date
            hist_mask = bars.index.get_level_values("date") <= trade_date
            hist_bars = bars[hist_mask]

            # Apply breakout filter
            breakout_filter = DailyBreakoutFilter(breakout_window=self.breakout_window)
            breakout_symbols = set(breakout_filter.filter(hist_bars, trade_date))

            # Apply trend filter
            trend_filter = DailyTrendFilter(trend_window=self.trend_window)
            trend_symbols = set(trend_filter.filter(hist_bars, trade_date))

            # Apply volume confirmation
            volume_symbols = self._volume_confirm(hist_bars, trade_date)

            # Compute factor values
            for symbol in symbols:
                in_breakout = symbol in breakout_symbols
                in_trend = symbol in trend_symbols
                in_volume = symbol in volume_symbols

                if in_breakout and in_trend and in_volume:
                    value = 1.0
                elif in_breakout and in_trend:
                    value = 0.7
                elif in_breakout:
                    value = 0.4
                else:
                    value = 0.0

                results.append({
                    "date": trade_date,
                    "symbol": symbol,
                    self.name: value,
                })

        if not results:
            return pd.DataFrame(columns=["date", "symbol", self.name])

        df = pd.DataFrame(results).set_index(["date", "symbol"])
        return df[[self.name]]

    def _volume_confirm(
        self,
        bars: pd.DataFrame,
        trade_date: date,
    ) -> set[str]:
        """Confirm volume > threshold * 20-day average."""
        try:
            day_bars = bars.loc[trade_date]
        except KeyError:
            return set()

        if isinstance(day_bars, pd.Series):
            day_bars = day_bars.to_frame().T

        if "volume" not in day_bars.columns:
            return set()

        confirmed = set()
        syms = day_bars.index.tolist() if hasattr(day_bars.index, "tolist") else [day_bars.index[0]]

        for symbol in syms:
            try:
                sym_bars = bars.xs(symbol, level="symbol")
            except KeyError:
                continue

            volumes = sym_bars["volume"].dropna()
            if len(volumes) < 21:
                continue

            today_vol = volumes.iloc[-1]
            avg_vol = volumes.iloc[-21:-1].mean()

            if avg_vol > 0 and today_vol > avg_vol * self.volume_ratio_threshold:
                confirmed.add(symbol)

        return confirmed
