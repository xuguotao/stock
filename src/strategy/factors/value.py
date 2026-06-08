"""Value factor.

Based on PE ratio (inverse).
Lower PE = higher factor value (more attractive valuation).

Usage:
    factor = ValueFactor()
    values = factor.compute(bars, fundamentals=financial_df)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.strategy.base import Factor


class ValueFactor(Factor):
    """Inverse PE ratio value factor.

    Factor = 1 / PE
    When PE is negative or zero, factor is 0.
    """

    name = "value"
    description = "Inverse PE ratio (lower PE = higher value)"

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute value factor from fundamentals."""
        fundamentals: pd.DataFrame | None = kwargs.get("fundamentals")

        if fundamentals is None or fundamentals.empty:
            # Fallback: use price-to-book approximation from price/volume
            # Not ideal, but allows testing without fundamentals
            return self._fallback(bars)

        pe = fundamentals.get("pe_ratio", pd.Series(index=fundamentals.index))
        # Invert PE: lower PE = higher value
        factor = pd.Series(0.0, index=fundamentals.index, name=self.name)
        valid = pe > 0
        factor[valid] = 1.0 / pe[valid]

        result = factor.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result

    def _fallback(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Fallback: use 1/price as a crude value proxy when no fundamentals."""
        close = bars["close"]
        factor = (1.0 / close.replace(0, float("nan"))).fillna(0)
        result = factor.to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result
