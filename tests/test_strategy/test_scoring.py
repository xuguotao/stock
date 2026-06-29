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


def _bars_with_symbols(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
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


def test_min_score_dict_only_gates_named_factor_not_overnight() -> None:
    """Dict min_score gates only the named factor; overnight momentum survives.

    Regression for the bug where a scalar ``min_score`` (set to gate the
    discrete tail_session factor at e.g. 0.7) NaN'd the entire continuous
    overnight_momentum column (values ~0), so ``composite.add(fill_value=0)``
    filled it to 0 and the 0.3 overnight weight was silently dropped.
    """
    tail_factor = StaticFactor({
        ("2025-01-02", "000001.SZ"): 1.0,
        ("2025-01-02", "600519.SH"): 0.7,
        ("2025-01-02", "300750.SZ"): 0.4,
        ("2025-01-02", "002594.SZ"): 0.0,
    })
    tail_factor.name = "tail_session"
    overnight_factor = StaticFactor({
        ("2025-01-02", "000001.SZ"): 0.001,
        ("2025-01-02", "600519.SH"): -0.002,
        ("2025-01-02", "300750.SZ"): 0.003,
        ("2025-01-02", "002594.SZ"): 0.0005,
    })
    overnight_factor.name = "overnight_momentum"

    bars = _bars_with_symbols(["000001.SZ", "600519.SH", "300750.SZ", "002594.SZ"])

    # Fixed behavior: dict gates ONLY tail_session; overnight is not gated.
    engine = FactorScoreEngine(
        factors=[tail_factor, overnight_factor],
        factor_weights=[0.7, 0.3],
        min_score={"tail_session": 0.7},
    )
    composite = engine.compute_scores(bars)
    assert composite is not None

    today = composite.loc[pd.Timestamp("2025-01-02")]
    overnight_contrib = today["overnight_momentum"]
    # Overnight contribution (rank * 0.3) survives for at least one symbol.
    assert overnight_contrib.abs().sum() > 0

    # Buggy scalar gate NaNs the whole overnight column -> zero contribution.
    buggy_engine = FactorScoreEngine(
        factors=[tail_factor, overnight_factor],
        factor_weights=[0.7, 0.3],
        min_score=0.7,
    )
    buggy_composite = buggy_engine.compute_scores(bars)
    buggy_today = buggy_composite.loc[pd.Timestamp("2025-01-02")]
    assert buggy_today["overnight_momentum"].abs().sum() == 0


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
