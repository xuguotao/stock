from __future__ import annotations

from datetime import date

import pandas as pd

from src.strategy.base import Factor
from src.strategy.scoring import FactorScoreEngine
from src.strategy.tail_session.history import build_historical_selection_rows


class StaticFactor(Factor):
    name = "static"

    def __init__(self, values: dict[tuple[str, str], float]):
        self.values = values

    def compute(self, bars: pd.DataFrame, **kwargs):
        rows = []
        for idx in bars.index:
            date_value, symbol = idx
            rows.append(self.values.get((pd.Timestamp(date_value).strftime("%Y-%m-%d"), symbol)))
        return pd.DataFrame({self.name: rows}, index=bars.index)


def _bars() -> pd.DataFrame:
    rows = []
    for symbol in ["000001.SZ", "600519.SH", "300750.SZ"]:
        rows.append({
            "date": pd.Timestamp("2025-01-02"),
            "symbol": symbol,
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 1000,
            "amount": 10_000,
            "adjusted_close": 10.0,
        })
    return pd.DataFrame(rows).set_index(["date", "symbol"])


def test_factor_score_engine_returns_ranked_daily_selections() -> None:
    factor = StaticFactor({
        ("2025-01-02", "000001.SZ"): 0.2,
        ("2025-01-02", "600519.SH"): 0.9,
        ("2025-01-02", "300750.SZ"): 0.5,
    })
    engine = FactorScoreEngine([factor], top_n=2)

    selections = engine.select(_bars(), date(2025, 1, 2))

    assert [(s.rank, s.symbol, round(s.score, 6)) for s in selections] == [
        (1, "600519.SH", 1.0),
        (2, "300750.SZ", 0.666667),
    ]


def test_factor_score_engine_applies_min_raw_score_before_ranking() -> None:
    factor = StaticFactor({
        ("2025-01-02", "000001.SZ"): 0.2,
        ("2025-01-02", "600519.SH"): 0.9,
        ("2025-01-02", "300750.SZ"): 0.5,
    })
    engine = FactorScoreEngine([factor], top_n=3, min_score=0.6)

    selections = engine.select(_bars(), date(2025, 1, 2))

    assert [s.symbol for s in selections] == ["600519.SH"]


def test_build_historical_selection_rows_uses_score_engine_contract() -> None:
    factor = StaticFactor({
        ("2025-01-02", "000001.SZ"): 0.2,
        ("2025-01-02", "600519.SH"): 0.9,
        ("2025-01-02", "300750.SZ"): 0.5,
    })

    rows = build_historical_selection_rows(
        bars=_bars(),
        factors=[factor],
        factor_weights=[1.0],
        start=date(2025, 1, 2),
        end=date(2025, 1, 2),
        top_n=2,
    )

    assert rows == [
        {"date": "2025-01-02", "rank": 1, "symbol": "600519.SH", "score": 1.0},
        {"date": "2025-01-02", "rank": 2, "symbol": "300750.SZ", "score": 0.666667},
    ]
