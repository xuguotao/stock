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
