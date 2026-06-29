"""Historical daily selections for tail-session research reports."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.strategy.scoring import FactorScoreEngine


def build_historical_selection_rows(
    bars: pd.DataFrame,
    factors: list,
    factor_weights: list[float],
    start: date,
    end: date,
    top_n: int,
    min_score: float | dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build daily selection rows using the shared factor scoring contract."""
    if bars.empty:
        return []

    dates = [
        pd.Timestamp(value).date()
        for value in sorted(bars.index.get_level_values("date").unique())
        if start <= pd.Timestamp(value).date() <= end
    ]
    engine = FactorScoreEngine(
        factors=factors,
        factor_weights=factor_weights,
        top_n=top_n,
        min_score=min_score,
    )

    rows: list[dict[str, Any]] = []
    for current_date in dates:
        current_ts = pd.Timestamp(current_date)
        historical_bars = bars[bars.index.get_level_values("date") <= current_ts]
        for selection in engine.select(historical_bars, current_date):
            rows.append({
                "date": selection.date.isoformat(),
                "rank": selection.rank,
                "symbol": selection.symbol,
                "score": round(selection.score, 6),
            })
    return rows
