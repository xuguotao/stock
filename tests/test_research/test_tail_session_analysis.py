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


def _bars_three_symbols() -> pd.DataFrame:
    """Three-symbol universe with differentiated turnover.

    ``600519.SH`` trades far more than the other two, so a turnover threshold
    between them zeroes the tail_session signal for the low-turnover names
    without affecting the high-turnover name. This is what makes the
    ``min_turnover_value`` filter observable at the grid level: with only two
    symbols (or ``top_n`` covering the whole universe) every bar is always
    selected and filters have no effect on the trade count.
    """
    dates = pd.bdate_range("2025-01-01", periods=60)
    rows = []
    for symbol, base, volume in [
        ("000001.SZ", 10.0, 1_000_000),
        ("600519.SH", 20.0, 5_000_000),
        ("300750.SZ", 30.0, 1_000_000),
    ]:
        for i, d in enumerate(dates):
            price = base * (1 + 0.002 * i)
            rows.append({
                "date": d,
                "symbol": symbol,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": volume + i * 1000,
                "amount": price * (volume + i * 1000),
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


def test_evaluate_tail_session_grid_high_min_score_preserves_overnight_trades() -> None:
    """A high tail_session min_score gates tail but overnight_momentum survives.

    Pre-fix, ``min_score`` was a scalar applied to every factor, so a 1.1
    threshold NaN'd both the discrete ``tail_session`` column (max 1.0) and the
    continuous ``overnight_momentum`` column (~0), zeroing all trades. Post-fix
    the grid converts the scalar to ``{"tail_session": <v>}``, so overnight is
    untouched and still drives selections: trades are NOT zeroed. The real
    discriminator on this 2-symbol fixture is ``trade_count > 0`` (both configs
    select the whole 2-symbol universe, so a ``high <= low`` comparison is
    vacuous and can't fail — it is intentionally not asserted here).
    """
    results = evaluate_tail_session_grid(
        bars=_bars(),
        configs=[
            {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0, "top_n": 2, "min_score": 0.0},
            {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0, "top_n": 2, "min_score": 1.1},
        ],
        initial_capital=100_000,
    )

    high_threshold = results.loc[results["min_score"] == 1.1, "trade_count"].iloc[0]
    assert high_threshold > 0


def test_evaluate_tail_session_grid_quality_filters_are_reported_and_applied() -> None:
    results = evaluate_tail_session_grid(
        bars=_bars_three_symbols(),
        configs=[
            {"breakout_window": 10, "trend_window": 3, "volume_ratio_threshold": 1.0, "top_n": 2, "min_score": 0.1},
            {
                "breakout_window": 10,
                "trend_window": 3,
                "volume_ratio_threshold": 1.0,
                "top_n": 2,
                "min_score": 0.1,
                "min_turnover_value": 50_000_000,
            },
        ],
        initial_capital=100_000,
    )

    assert "min_turnover_value" in results.columns
    baseline = results.loc[results["min_turnover_value"].isna(), "trade_count"].iloc[0]
    filtered = results.loc[results["min_turnover_value"] == 50_000_000, "trade_count"].iloc[0]
    # The filter is applied: zeroing the tail_session signal for low-turnover
    # names changes the cross-sectional selection (overnight alone cannot always
    # reproduce the tail-driven ranking), so the trade count differs. The
    # direction is data-dependent now that overnight survives the tail gate.
    assert filtered != baseline
