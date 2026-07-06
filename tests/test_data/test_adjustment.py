"""Tests for adjustment calculation functions."""
from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.adjustment import (
    apply_backward_adjustment,
    apply_forward_adjustment,
    compute_adjustment_ratios,
)


def test_compute_ratios_no_events():
    """No xdxr events should return empty DataFrame."""
    events = pd.DataFrame(columns=["ex_date", "fenhong", "songzhuangu", "peigu", "suogu", "pre_close"])
    result = compute_adjustment_ratios(events)
    assert len(result) == 0


def test_compute_ratios_cash_dividend():
    """Cash dividend only: ratio = (pre_close - fenhong) / pre_close."""
    events = pd.DataFrame([
        {
            "ex_date": date(2023, 6, 15),
            "fenhong": 0.5,
            "songzhuangu": 0.0,
            "peigu": 0.0,
            "suogu": 0.0,
            "pre_close": 10.0,
        }
    ])
    result = compute_adjustment_ratios(events)
    assert len(result) == 1
    # ratio = (10.0 - 0.5 + 0) / (10.0 + 0 + 0) = 0.95
    assert abs(result.iloc[0]["ratio"] - 0.95) < 1e-9


def test_compute_ratios_bonus_shares():
    """Bonus shares only: ratio = pre_close / (pre_close + songzhuangu)."""
    events = pd.DataFrame([
        {
            "ex_date": date(2023, 6, 15),
            "fenhong": 0.0,
            "songzhuangu": 0.3,
            "peigu": 0.0,
            "suogu": 0.0,
            "pre_close": 10.0,
        }
    ])
    result = compute_adjustment_ratios(events)
    assert len(result) == 1
    # ratio = (10.0 - 0 + 0) / (10.0 + 0.3 + 0) = 10.0 / 10.3
    expected = 10.0 / 10.3
    assert abs(result.iloc[0]["ratio"] - expected) < 1e-9


def test_compute_ratios_rights_issue():
    """Rights issue with peigujia: ratio includes peigu * peigujia term."""
    events = pd.DataFrame([
        {
            "ex_date": date(2023, 6, 15),
            "fenhong": 0.0,
            "songzhuangu": 0.0,
            "peigu": 0.2,
            "suogu": 0.0,
            "pre_close": 10.0,
            "peigujia": 8.0,
        }
    ])
    result = compute_adjustment_ratios(events)
    assert len(result) == 1
    # ratio = (10.0 - 0 + 0.2 * 8.0) / (10.0 + 0 + 0.2) = 11.6 / 10.2
    expected = 11.6 / 10.2
    assert abs(result.iloc[0]["ratio"] - expected) < 1e-9


def test_compute_ratios_consolidation():
    """Share consolidation: ratio = suogu (post-consolidation shares per pre-share)."""
    events = pd.DataFrame([
        {
            "ex_date": date(2023, 6, 15),
            "fenhong": 0.0,
            "songzhuangu": 0.0,
            "peigu": 0.0,
            "suogu": 0.5,
            "pre_close": 10.0,
        }
    ])
    result = compute_adjustment_ratios(events)
    assert len(result) == 1
    # ratio = (10.0 - 0 + 0) / (10.0 + 0 + 0) * 0.5 = 1.0 * 0.5 = 0.5
    assert abs(result.iloc[0]["ratio"] - 0.5) < 1e-9


def test_compute_ratios_mixed_event():
    """Combined dividend + bonus + rights issue."""
    events = pd.DataFrame([
        {
            "ex_date": date(2023, 6, 15),
            "fenhong": 0.3,
            "songzhuangu": 0.2,
            "peigu": 0.1,
            "suogu": 0.0,
            "pre_close": 10.0,
            "peigujia": 8.0,
        }
    ])
    result = compute_adjustment_ratios(events)
    assert len(result) == 1
    # ratio = (10.0 - 0.3 + 0.1 * 8.0) / (10.0 + 0.2 + 0.1) = 10.5 / 10.3
    expected = 10.5 / 10.3
    assert abs(result.iloc[0]["ratio"] - expected) < 1e-9


def test_compute_ratios_multiple_events_sorted_by_date():
    """Multiple events should be sorted by ex_date ascending."""
    events = pd.DataFrame([
        {
            "ex_date": date(2024, 1, 10),
            "fenhong": 0.5,
            "songzhuangu": 0.0,
            "peigu": 0.0,
            "suogu": 0.0,
            "pre_close": 12.0,
        },
        {
            "ex_date": date(2023, 6, 15),
            "fenhong": 0.3,
            "songzhuangu": 0.0,
            "peigu": 0.0,
            "suogu": 0.0,
            "pre_close": 10.0,
        },
    ])
    result = compute_adjustment_ratios(events)
    assert len(result) == 2
    assert result.iloc[0]["ex_date"] == date(2023, 6, 15)
    assert result.iloc[1]["ex_date"] == date(2024, 1, 10)


def _sample_bars():
    """5 trading days around one xdxr event on date(2024, 1, 10)."""
    return pd.DataFrame([
        {"date": date(2024, 1, 8),  "close": 10.0, "open": 9.8, "high": 10.2, "low": 9.7,
         "volume": 1000, "amount": 10000.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 9),  "close": 10.5, "open": 10.1, "high": 10.6, "low": 10.0,
         "volume": 1200, "amount": 12600.0, "symbol": "000001.SZ"},
        # ex-date: cum-rights close = 10.5, ex-ref = 10.0, ratio = 10.0/10.5
        {"date": date(2024, 1, 10), "close": 10.0, "open": 9.9, "high": 10.1, "low": 9.8,
         "volume": 1500, "amount": 15000.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 11), "close": 10.2, "open": 10.0, "high": 10.3, "low": 9.9,
         "volume": 1100, "amount": 11220.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 12), "close": 10.4, "open": 10.1, "high": 10.5, "low": 10.0,
         "volume": 1300, "amount": 13520.0, "symbol": "000001.SZ"},
    ])


def _sample_ratio():
    """One xdxr event with ratio = 10.0/10.5 on ex_date 2024-01-10."""
    return pd.DataFrame([
        {"ex_date": date(2024, 1, 10), "ratio": 10.0 / 10.5},
    ])


def test_forward_adjustment_latest_price_unchanged():
    """Forward adjustment: latest date should keep original price."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_forward_adjustment(bars, ratios)

    # Latest date (2024-01-12) has no future xdxr → adjusted_close = close
    latest = result[result["date"] == date(2024, 1, 12)]
    assert abs(latest.iloc[0]["adjusted_close"] - 10.4) < 1e-9


def test_forward_adjustment_historical_prices_reduced():
    """Forward adjustment: historical prices are scaled down."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_forward_adjustment(bars, ratios)

    # Before ex-date, adjusted_close = close * ratio = close * (10.0/10.5)
    pre_event = result[result["date"] == date(2024, 1, 9)]
    expected = 10.5 * (10.0 / 10.5)
    assert abs(pre_event.iloc[0]["adjusted_close"] - expected) < 1e-9


def test_forward_adjustment_ex_date_and_after_unchanged():
    """Forward adjustment: on and after ex-date, prices stay as-is."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_forward_adjustment(bars, ratios)

    for d in [date(2024, 1, 10), date(2024, 1, 11), date(2024, 1, 12)]:
        row = result[result["date"] == d].iloc[0]
        assert abs(row["adjusted_close"] - row["close"]) < 1e-9


def test_backward_adjustment_earliest_price_unchanged():
    """Backward adjustment: earliest date keeps original price."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_backward_adjustment(bars, ratios)

    earliest = result[result["date"] == date(2024, 1, 8)]
    assert abs(earliest.iloc[0]["adjusted_close"] - 10.0) < 1e-9


def test_backward_adjustment_after_ex_date_increased():
    """Backward adjustment: after ex-date, prices scaled up."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_backward_adjustment(bars, ratios)

    # After ex-date: adjusted_close = close / ratio = close * (10.5/10.0)
    post_event = result[result["date"] == date(2024, 1, 11)]
    expected = 10.2 * (10.5 / 10.0)
    assert abs(post_event.iloc[0]["adjusted_close"] - expected) < 1e-9


def test_forward_adjustment_no_events():
    """No xdxr events → adjusted_close = close."""
    bars = _sample_bars()
    empty_ratios = pd.DataFrame(columns=["ex_date", "ratio"])

    result = apply_forward_adjustment(bars, empty_ratios)

    assert (result["adjusted_close"] == result["close"]).all()


def test_backward_adjustment_no_events():
    """No xdxr events → adjusted_close = close."""
    bars = _sample_bars()
    empty_ratios = pd.DataFrame(columns=["ex_date", "ratio"])

    result = apply_backward_adjustment(bars, empty_ratios)

    assert (result["adjusted_close"] == result["close"]).all()


def test_forward_adjustment_multiple_events():
    """Multiple xdxr events accumulate correctly."""
    bars = pd.DataFrame([
        {"date": date(2024, 1, 5),  "close": 20.0, "open": 19.5, "high": 20.5,
         "low": 19.0, "volume": 1000, "amount": 20000.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 10), "close": 19.0, "open": 18.5, "high": 19.5,
         "low": 18.0, "volume": 1200, "amount": 22800.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 15), "close": 18.0, "open": 17.5, "high": 18.5,
         "low": 17.0, "volume": 1500, "amount": 27000.0, "symbol": "000001.SZ"},
    ])
    ratios = pd.DataFrame([
        {"ex_date": date(2024, 1, 10), "ratio": 0.95},  # 5% drop
        {"ex_date": date(2024, 1, 15), "ratio": 0.90},  # 10% drop
    ])

    result = apply_forward_adjustment(bars, ratios)

    # 2024-01-05: affected by BOTH events → 20.0 * 0.95 * 0.90 = 17.1
    jan5 = result[result["date"] == date(2024, 1, 5)]
    assert abs(jan5.iloc[0]["adjusted_close"] - 17.1) < 1e-6

    # 2024-01-10: affected by second event only → 19.0 * 0.90 = 17.1
    jan10 = result[result["date"] == date(2024, 1, 10)]
    assert abs(jan10.iloc[0]["adjusted_close"] - 17.1) < 1e-6

    # 2024-01-15: no future events → 18.0
    jan15 = result[result["date"] == date(2024, 1, 15)]
    assert abs(jan15.iloc[0]["adjusted_close"] - 18.0) < 1e-6
