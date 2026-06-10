"""Parameter-grid analysis for the tail-session strategy."""

from __future__ import annotations

from itertools import product
from typing import Any

import pandas as pd

from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.factors.tail_session import TailSessionFactor


def expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a parameter grid into concrete config dictionaries."""
    keys = list(grid.keys())
    return [dict(zip(keys, values)) for values in product(*(grid[key] for key in keys))]


def evaluate_tail_session_grid(
    bars: pd.DataFrame,
    configs: list[dict[str, Any]],
    initial_capital: float = 100_000,
    tail_weight: float = 0.7,
    overnight_weight: float = 0.3,
) -> pd.DataFrame:
    """Run tail-session backtests for every config and return metric rows."""
    rows = []
    for i, config in enumerate(configs, start=1):
        top_n = int(config.get("top_n", 5))
        factor = TailSessionFactor(
            breakout_window=int(config.get("breakout_window", 20)),
            trend_window=int(config.get("trend_window", 5)),
            volume_ratio_threshold=float(config.get("volume_ratio_threshold", 1.2)),
        )
        overnight = OvernightMomentumFactor(
            smoothing_window=int(config.get("overnight_smoothing_window", 1))
        )
        engine = BacktestEngine(
            bars=bars,
            factors=[factor, overnight],
            factor_weights=[tail_weight, overnight_weight],
            top_n=top_n,
            rebalance_days=1,
            initial_capital=initial_capital,
            equal_weight=True,
        )
        result = engine.run()
        row = dict(config)
        row["config_id"] = i
        row["trade_count"] = len(result.trades)
        row.update(result.metrics)
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
