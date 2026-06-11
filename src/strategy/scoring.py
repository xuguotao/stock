"""Factor scoring and daily selection services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.strategy.base import Factor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    """A ranked symbol selected from factor scores."""

    date: date
    rank: int
    symbol: str
    score: float


class FactorScoreEngine:
    """Compute weighted factor scores and convert them into selections."""

    def __init__(
        self,
        factors: list[Factor],
        factor_weights: list[float] | None = None,
        top_n: int = 10,
        min_score: float | None = None,
    ):
        self.factors = factors
        self.factor_weights = factor_weights or [1.0 / len(factors)] * len(factors) if factors else []
        self.top_n = top_n
        self.min_score = min_score

    def compute_scores(self, bars: pd.DataFrame) -> pd.DataFrame | None:
        """Compute weighted cross-sectional factor ranks for all dates."""
        if not self.factors:
            return None

        scores = []
        for factor, weight in zip(self.factors, self.factor_weights):
            try:
                values = factor.compute(bars)
                if values.empty:
                    continue
                if self.min_score is not None:
                    values = values.where(values >= self.min_score)
                ranked = values.groupby(level=0).rank(pct=True)
                scores.append(ranked * weight)
            except Exception as exc:
                logger.warning("Factor %s failed: %s", factor.name, exc)

        if not scores:
            return None

        composite = scores[0]
        for score in scores[1:]:
            composite = composite.add(score, fill_value=0)
        return composite

    def select(self, bars: pd.DataFrame, selection_date: date) -> list[Selection]:
        """Return top-N selections for one date from historical bars."""
        composite = self.compute_scores(bars)
        if composite is None or composite.empty:
            return []

        score_date = self._resolve_index_date(composite, selection_date)
        if score_date is None:
            return []

        try:
            today_scores = composite.loc[score_date].squeeze()
        except KeyError:
            return []

        if isinstance(today_scores, pd.DataFrame):
            today_scores = today_scores.mean(axis=1)
        if not isinstance(today_scores, pd.Series):
            return []

        scores = today_scores.dropna()
        scores = scores[scores > 0]
        if scores.empty:
            return []

        selected = scores.sort_values(ascending=False).head(self.top_n)
        return [
            Selection(
                date=selection_date,
                rank=rank,
                symbol=str(symbol),
                score=float(score),
            )
            for rank, (symbol, score) in enumerate(selected.items(), start=1)
        ]

    def _resolve_index_date(self, values: pd.DataFrame, target_date: date):
        dates = values.index.get_level_values(0)
        if target_date in dates:
            return target_date

        timestamp = pd.Timestamp(target_date)
        if timestamp in dates:
            return timestamp

        normalized = dates.map(pd.Timestamp).normalize()
        matches = dates[normalized == timestamp.normalize()]
        if len(matches) == 0:
            return None
        return matches[0]
