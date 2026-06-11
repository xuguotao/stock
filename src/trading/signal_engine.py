"""信号引擎.

从策略因子生成交易信号。
支持多种信号类型:
  - FactorSignal: 因子排名选股
  - ThresholdSignal: 因子阈值触发
  - CrossoverSignal: 指标交叉信号

Usage:
    engine = SignalEngine(top_n=5, rebalance_days=5)
    signals = engine.generate_signals(bars, factors, trade_date)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.core.types import Side
from src.strategy.base import Factor
from src.strategy.scoring import FactorScoreEngine

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """A trading signal."""
    date: date
    symbol: str
    side: Side
    strength: float       # Signal strength [0, 1], higher = stronger
    factor_name: str = ""
    reason: str = ""


class SignalEngine:
    """Generate trading signals from factors."""

    def __init__(
        self,
        top_n: int = 5,
        rebalance_days: int = 5,
        min_strength: float = 0.6,
    ):
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.min_strength = min_strength
        self._day_counter = 0
        self._current_holdings: set[str] = set()

    def generate_signals(
        self,
        bars: pd.DataFrame,
        factors: list[Factor],
        trade_date: date,
        factor_weights: list[float] | None = None,
    ) -> list[Signal]:
        """Generate buy/sell signals for a given date.

        Args:
            bars: MultiIndex (date, symbol) OHLCV data up to trade_date.
            factors: List of Factor objects.
            trade_date: Current trading date.
            factor_weights: Weights for composite score.

        Returns:
            List of Signal objects.
        """
        self._day_counter += 1

        if self._day_counter % self.rebalance_days != 0:
            return []

        # Compute composite score
        composite = self._compute_composite(bars, factors, factor_weights)
        if composite is None or composite.empty:
            return []

        # Get today's scores
        score_date = self._resolve_index_date(composite, trade_date)
        if score_date is None:
            return []

        try:
            today_scores = composite.loc[score_date]
        except KeyError:
            return []

        # Ensure we have a Series
        if isinstance(today_scores, pd.DataFrame):
            if today_scores.shape[1] == 1:
                today_scores = today_scores.iloc[:, 0]
            elif today_scores.shape[0] == 1:
                today_scores = today_scores.iloc[0]
            else:
                today_scores = today_scores.mean(axis=1)  # Multiple columns: average

        scores = today_scores.dropna().sort_values(ascending=False)
        signals = []

        # Top-N = BUY
        for i, (symbol, score) in enumerate(scores.items()):
            if i >= self.top_n:
                break
            if score < self.min_strength:
                break

            signals.append(Signal(
                date=trade_date,
                symbol=symbol,
                side=Side.BUY,
                strength=float(score),
                factor_name="composite",
                reason=f"Factor rank #{i+1} (score={score:.4f})",
            ))

        # Holdings not in top-N = SELL
        selected = {s.symbol for s in signals}
        for symbol in self._current_holdings:
            if symbol not in selected and symbol in scores.index:
                signals.append(Signal(
                    date=trade_date,
                    symbol=symbol,
                    side=Side.SELL,
                    strength=1.0 - float(scores[symbol]) if symbol in scores.index else 0.5,
                    factor_name="composite",
                    reason="Dropped from top-N",
                ))

        self._current_holdings = selected
        return signals

    def _resolve_index_date(self, values: pd.DataFrame, trade_date: date):
        """Match date or Timestamp inputs against the factor index date level."""
        dates = values.index.get_level_values(0)
        if trade_date in dates:
            return trade_date

        ts = pd.Timestamp(trade_date)
        if ts in dates:
            return ts

        normalized = dates.map(pd.Timestamp).normalize()
        matches = dates[normalized == ts.normalize()]
        if len(matches) == 0:
            return None
        return matches[0]

    def _compute_composite(
        self,
        bars: pd.DataFrame,
        factors: list[Factor],
        weights: list[float] | None,
    ) -> pd.DataFrame | None:
        """Compute weighted composite factor."""
        return FactorScoreEngine(
            factors=factors,
            factor_weights=weights,
            top_n=self.top_n,
        ).compute_scores(bars)
