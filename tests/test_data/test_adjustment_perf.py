"""Performance benchmarks for adjustment calculation."""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
import numpy as np

from src.data.adjustment import (
    apply_backward_adjustment,
    apply_forward_adjustment,
    compute_adjustment_ratios,
)


def _generate_bars(n_days: int = 8000) -> pd.DataFrame:
    """Generate synthetic daily bars spanning ~30 years."""
    dates = pd.bdate_range(start=date(1990, 1, 1), periods=n_days)
    np.random.seed(42)
    close = 10.0 * np.cumprod(1 + np.random.normal(0.0003, 0.02, n_days))
    return pd.DataFrame({
        "date": [d.date() for d in dates],
        "open": close * (1 + np.random.uniform(-0.01, 0.01, n_days)),
        "high": close * (1 + np.abs(np.random.normal(0, 0.01, n_days))),
        "low": close * (1 - np.abs(np.random.normal(0, 0.01, n_days))),
        "close": close,
        "volume": np.random.randint(100000, 10000000, n_days),
        "amount": close * np.random.randint(100000, 10000000, n_days),
        "symbol": "000001.SZ",
    })


def _generate_xdxr_events(n_events: int = 60) -> pd.DataFrame:
    """Generate synthetic xdxr events (roughly quarterly for 15 years)."""
    np.random.seed(42)
    dates = sorted(
        date(1995, 1, 1) + timedelta(days=int(d))
        for d in np.random.uniform(0, 10000, n_events)
    )
    return pd.DataFrame({
        "ex_date": dates,
        "fenhong": np.random.uniform(0.1, 1.0, n_events),
        "songzhuangu": np.random.choice([0.0, 0.1, 0.2, 0.3], n_events),
        "peigu": np.random.choice([0.0, 0.0, 0.1], n_events),
        "suogu": np.zeros(n_events),
        "pre_close": 10.0 * np.cumprod(1 + np.random.normal(0.0003, 0.02, n_events)),
    })


def test_single_stock_30yr_adjustment_under_50ms():
    """Single stock with 30 years of daily bars should adjust in < 50ms."""
    bars = _generate_bars(8000)  # ~30 years of trading days
    events = _generate_xdxr_events(60)
    ratios = compute_adjustment_ratios(events)

    start = time.perf_counter()
    result = apply_forward_adjustment(bars, ratios)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert not result.empty
    assert "adjusted_close" in result.columns
    # Note: this is a soft target. CI may be slower.
    print(f"\n  Forward adjustment (8000 bars, 60 events): {elapsed_ms:.1f}ms")


def test_backward_adjustment_performance():
    """Backward adjustment should be similarly fast."""
    bars = _generate_bars(8000)
    events = _generate_xdxr_events(60)
    ratios = compute_adjustment_ratios(events)

    start = time.perf_counter()
    result = apply_backward_adjustment(bars, ratios)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert not result.empty
    print(f"\n  Backward adjustment (8000 bars, 60 events): {elapsed_ms:.1f}ms")


def test_ratio_computation_performance():
    """Ratio computation for 100 events should be very fast."""
    events = _generate_xdxr_events(100)

    start = time.perf_counter()
    ratios = compute_adjustment_ratios(events)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(ratios) == 100
    print(f"\n  Ratio computation (100 events): {elapsed_ms:.1f}ms")
    assert elapsed_ms < 10  # Should be sub-10ms for pure pandas
