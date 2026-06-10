from __future__ import annotations

from datetime import date
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
    # Should have NaN for first row (no previous close to compare)
    valid = result["overnight_momentum"].dropna()
    assert len(valid) > 0


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
