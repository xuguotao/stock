from __future__ import annotations

from datetime import date
import time
import pandas as pd
from src.strategy.factors.tail_session import TailSessionFactor

def _multi_bars(symbols: list[str], periods: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=periods)
    rows = []
    for si, symbol in enumerate(symbols):
        price = 10 + si * 5
        for di, d in enumerate(dates):
            price *= 1 + 0.001 * (si + 1) + 0.0002 * di
            rows.append({
                "date": d, "symbol": symbol,
                "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price,
                "volume": 1_000_000 * (1 + si * 0.1),
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })
    return pd.DataFrame(rows).set_index(["date", "symbol"])

def test_tail_session_factor_returns_values() -> None:
    bars = _multi_bars(["000001.SZ", "600519.SH"])
    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    result = factor.compute(bars)

    assert not result.empty
    assert "tail_session" in result.columns
    assert result.index.names == ["date", "symbol"]

def test_tail_session_factor_only_scores_symbols_present_on_date() -> None:
    bars = _multi_bars(["000001.SZ", "600519.SH"])
    last_date = bars.index.get_level_values("date").max()
    bars = bars.drop(index=(last_date, "600519.SH"))

    result = TailSessionFactor(breakout_window=20, trend_window=5).compute(bars)

    assert "600519.SH" not in result.loc[last_date].index

def test_factor_returns_zero_for_no_breakout() -> None:
    """Flat prices = no breakout = factor 0."""
    dates = pd.bdate_range("2025-01-01", periods=30)
    rows = []
    for di, d in enumerate(dates):
        rows.append({
            "date": d, "symbol": "000001.SZ",
            "open": 10.0, "high": 10.0, "low": 10.0,
            "close": 10.0, "volume": 1_000_000,
            "amount": 10_000_000, "adjusted_close": 10.0,
        })
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])

    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    result = factor.compute(bars)

    # All values should be 0 (no breakout, flat trend)
    assert (result["tail_session"] == 0.0).all()

def test_factor_empty_bars_returns_empty() -> None:
    factor = TailSessionFactor()
    result = factor.compute(pd.DataFrame())
    assert result.empty


def test_tail_session_factor_blocks_breakout_below_ma20() -> None:
    dates = pd.bdate_range("2025-01-01", periods=26)
    closes = [20.0] * 20 + [10.0, 10.2, 10.4, 10.6, 10.8, 11.0]
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d,
            "symbol": "000001.SZ",
            "open": closes[i] * 0.99,
            "high": closes[i] * 1.01,
            "low": closes[i] * 0.98,
            "close": closes[i],
            "volume": 5_000_000 if i == len(dates) - 1 else 1_000_000,
            "amount": closes[i] * (5_000_000 if i == len(dates) - 1 else 1_000_000),
            "adjusted_close": closes[i],
        })
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])

    loose = TailSessionFactor(breakout_window=5, trend_window=3).compute(bars)
    strict = TailSessionFactor(
        breakout_window=5,
        trend_window=3,
        min_close_above_ma20=True,
    ).compute(bars)

    last_key = (dates[-1], "000001.SZ")
    assert loose.loc[last_key, "tail_session"] > 0
    assert strict.loc[last_key, "tail_session"] == 0


def test_tail_session_factor_blocks_overextended_daily_return() -> None:
    bars = _multi_bars(["000001.SZ"], periods=30).reset_index()
    last_idx = bars.index[-1]
    prev_close = float(bars.loc[last_idx - 1, "close"])
    bars.loc[last_idx, ["open", "high", "low", "close", "adjusted_close"]] = [
        prev_close * 1.18,
        prev_close * 1.21,
        prev_close * 1.16,
        prev_close * 1.20,
        prev_close * 1.20,
    ]
    bars.loc[last_idx, "volume"] = 5_000_000
    bars.loc[last_idx, "amount"] = float(bars.loc[last_idx, "close"]) * 5_000_000
    bars = bars.set_index(["date", "symbol"])

    loose = TailSessionFactor(breakout_window=20, trend_window=5).compute(bars)
    strict = TailSessionFactor(
        breakout_window=20,
        trend_window=5,
        max_daily_return=0.08,
    ).compute(bars)

    last_key = (bars.index.get_level_values("date").max(), "000001.SZ")
    assert loose.loc[last_key, "tail_session"] > 0
    assert strict.loc[last_key, "tail_session"] == 0


def test_tail_session_factor_blocks_low_turnover_value() -> None:
    bars = _multi_bars(["000001.SZ"], periods=30).copy()
    bars["amount"] = 0
    bars["volume"] = 100

    loose = TailSessionFactor(breakout_window=20, trend_window=5).compute(bars)
    strict = TailSessionFactor(
        breakout_window=20,
        trend_window=5,
        min_turnover_value=10_000_000,
    ).compute(bars)

    last_key = (bars.index.get_level_values("date").max(), "000001.SZ")
    assert loose.loc[last_key, "tail_session"] > 0
    assert strict.loc[last_key, "tail_session"] == 0


def test_tail_session_factor_blocks_when_market_breadth_is_weak() -> None:
    dates = pd.bdate_range("2025-01-01", periods=30)
    rows = []
    for symbol, closes in {
        "000001.SZ": [10.0 + i * 0.1 for i in range(30)],
        "600519.SH": [20.0 - i * 0.1 for i in range(30)],
    }.items():
        for i, d in enumerate(dates):
            close = closes[i]
            rows.append({
                "date": d,
                "symbol": symbol,
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 5_000_000 if i == len(dates) - 1 else 1_000_000,
                "amount": close * (5_000_000 if i == len(dates) - 1 else 1_000_000),
                "adjusted_close": close,
            })
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])

    loose = TailSessionFactor(breakout_window=20, trend_window=5).compute(bars)
    strict = TailSessionFactor(
        breakout_window=20,
        trend_window=5,
        min_market_breadth_above_ma20=0.75,
    ).compute(bars)

    last_key = (dates[-1], "000001.SZ")
    assert loose.loc[last_key, "tail_session"] > 0
    assert strict.loc[last_key, "tail_session"] == 0


def test_overnight_momentum_positive_on_gap_up() -> None:
    """Close lower than next open = positive overnight momentum."""
    from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
    dates = pd.bdate_range("2025-01-01", periods=10)
    rows = []
    for i, d in enumerate(dates):
        close = 10.0 + i * 0.1
        open_next = close + 0.05 if i > 0 else close
        rows.append({
            "date": d, "symbol": "000001.SZ",
            "open": open_next if i > 0 else close,
            "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": 1_000_000,
            "amount": close * 1_000_000,
            "adjusted_close": close,
        })
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])

    factor = OvernightMomentumFactor()
    result = factor.compute(bars)

    assert "overnight_momentum" in result.columns
    first_value = result["overnight_momentum"].iloc[0]
    assert pd.isna(first_value)
    valid = result["overnight_momentum"].dropna()
    assert (valid > 0).all()


def test_tail_session_backtest_runs() -> None:
    from src.strategy.engine.backtest import BacktestEngine
    from src.strategy.factors.tail_session import TailSessionFactor
    from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
    from config.settings import reset_settings
    reset_settings()
    bars = _multi_bars(["000001.SZ", "600519.SH", "300750.SZ", "000858.SZ", "601318.SH"])

    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    engine = BacktestEngine(
        bars=bars,
        factors=[factor],
        top_n=3,
        rebalance_days=1,
        initial_capital=100_000,
        equal_weight=True,
    )

    result = engine.run()
    assert result.initial_capital == 100_000
    assert result.final_value > 0
    assert len(result.daily_returns) > 0
    metrics = result.metrics
    assert "sharpe_ratio" in metrics
    assert "win_rate" in metrics
    assert metrics["trading_days"] > 0


def test_tail_session_factor_handles_medium_panel_quickly() -> None:
    symbols = [f"{i:06d}.SZ" for i in range(1, 13)]
    bars = _multi_bars(symbols, periods=220)
    factor = TailSessionFactor(breakout_window=20, trend_window=5)

    start = time.perf_counter()
    result = factor.compute(bars)
    elapsed = time.perf_counter() - start

    assert not result.empty
    assert elapsed < 1.0
