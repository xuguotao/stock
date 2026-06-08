"""Strategy base classes.

Defines the abstract Factor interface and cross-sectional rank normalization.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class Factor(ABC):
    """Abstract base for all factors.

    Subclasses must implement `compute()` which returns factor values
    as a DataFrame with MultiIndex (date, symbol).

    Convention: higher factor value = more bullish.
    """

    name: str = "unnamed"
    description: str = ""

    @abstractmethod
    def compute(
        self,
        bars: pd.DataFrame,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Compute factor values.

        Args:
            bars: MultiIndex DataFrame (date, symbol) with columns:
                  open, high, low, close, volume, amount, adjusted_close
            **kwargs: Additional factor-specific parameters.

        Returns:
            DataFrame with same MultiIndex (date, symbol),
            single column with factor values.
        """
        ...

    def rank(self, factor_values: pd.DataFrame) -> pd.DataFrame:
        """Cross-sectional rank normalization to [0, 1]."""
        return factor_values.groupby(level=0).rank(pct=True)

    def zscore(self, factor_values: pd.DataFrame) -> pd.DataFrame:
        """Cross-sectional z-score normalization."""
        return factor_values.groupby(level=0).transform(
            lambda x: (x - x.mean()) / x.replace(0, np.nan).std()
        )


class CompositeFactor(Factor):
    """Multi-factor synthesis: weighted combination of sub-factors.

    Usage:
        composite = CompositeFactor([
            (momentum_factor, 0.3),
            (value_factor, 0.4),
            (quality_factor, 0.3),
        ])
        values = composite.compute(bars)
    """

    name = "composite"
    description = "Weighted combination of sub-factors"

    def __init__(self, factors: list[tuple[Factor, float]]):
        self.factors = factors
        total_weight = sum(w for _, w in factors)
        if total_weight > 0:
            self.factors = [(f, w / total_weight) for f, w in factors]

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute weighted composite factor."""
        composite = None
        for factor, weight in self.factors:
            values = factor.compute(bars, **kwargs)
            ranked = self.rank(values)
            if composite is None:
                composite = ranked * weight
            else:
                composite = composite + ranked * weight
        return composite if composite is not None else pd.DataFrame()
