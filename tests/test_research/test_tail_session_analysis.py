from __future__ import annotations

import pandas as pd

from src.research.tail_session_analysis import evaluate_tail_session_grid, expand_grid


def _bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=40)
    rows = []
    for symbol, base in [("000001.SZ", 10.0), ("600519.SH", 20.0)]:
        for i, d in enumerate(dates):
            price = base * (1 + 0.002 * i)
            rows.append({
                "date": d,
                "symbol": symbol,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1_000_000 + i * 1000,
                "amount": price * (1_000_000 + i * 1000),
                "adjusted_close": price,
            })
    return pd.DataFrame(rows).set_index(["date", "symbol"])


def test_expand_grid_returns_parameter_combinations() -> None:
    configs = expand_grid({
        "breakout_window": [10, 20],
        "trend_window": [3],
        "volume_ratio_threshold": [1.0, 1.2],
    })

    assert configs == [
        {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0},
        {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.2},
        {"breakout_window": 20, "trend_window": 3, "volume_ratio_threshold": 1.0},
        {"breakout_window": 20, "trend_window": 3, "volume_ratio_threshold": 1.2},
    ]


def test_evaluate_tail_session_grid_returns_metrics_per_config() -> None:
    results = evaluate_tail_session_grid(
        bars=_bars(),
        configs=[
            {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0, "top_n": 1, "min_score": 0.4},
            {"breakout_window": 20, "trend_window": 5, "volume_ratio_threshold": 1.2, "top_n": 2, "min_score": 0.7},
        ],
        initial_capital=100_000,
    )

    assert len(results) == 2
    assert {
        "breakout_window",
        "trend_window",
        "volume_ratio_threshold",
        "top_n",
        "min_score",
        "total_return",
        "sharpe_ratio",
        "win_rate",
        "max_drawdown",
        "trade_count",
    }.issubset(results.columns)


def test_evaluate_tail_session_grid_min_score_can_block_trades() -> None:
    results = evaluate_tail_session_grid(
        bars=_bars(),
        configs=[
            {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0, "top_n": 2, "min_score": 0.0},
            {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0, "top_n": 2, "min_score": 1.1},
        ],
        initial_capital=100_000,
    )

    low_threshold = results.loc[results["min_score"] == 0.0, "trade_count"].iloc[0]
    high_threshold = results.loc[results["min_score"] == 1.1, "trade_count"].iloc[0]
    assert high_threshold < low_threshold
