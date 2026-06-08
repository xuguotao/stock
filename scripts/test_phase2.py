#!/usr/bin/env python3
"""Test Phase 2: Factor library + Backtest engine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

import numpy as np
import pandas as pd

from config.settings import get_settings
from src.data.aggregator import DataAggregator
from src.data.sina_source import SinaSource
from src.strategy.base import Factor, CompositeFactor
from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor, MACrossSignal
from src.strategy.factors.mean_reversion import MeanReversionFactor
from src.strategy.factors.value import ValueFactor
from src.strategy.execution.broker import SimulatedBroker
from src.strategy.execution.order import Order, OrderResult
from src.strategy.engine.backtest import BacktestEngine, BacktestResult
from src.core.types import Side


def create_sample_bars() -> pd.DataFrame:
    """Create synthetic multi-bar data for testing."""
    np.random.seed(42)
    symbols = ["000001.SZ", "600519.SH", "300750.SZ"]
    dates = pd.bdate_range("2024-01-01", periods=60)

    rows = []
    for sym in symbols:
        price = 10.0 + np.random.random() * 100
        for d in dates:
            ret = np.random.normal(0.001, 0.02)
            price *= (1 + ret)
            rows.append({
                "date": d,
                "symbol": sym,
                "open": price * (1 + np.random.normal(0, 0.005)),
                "high": price * (1 + abs(np.random.normal(0, 0.01))),
                "low": price * (1 - abs(np.random.normal(0, 0.01))),
                "close": price,
                "volume": int(1e6 * np.random.random()),
                "amount": price * 1e6 * np.random.random(),
                "adjusted_close": price,
            })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index(["date", "symbol"])


def test_factors():
    """Test all factor implementations."""
    print("=" * 60)
    print("Phase 2 Test: Factor Library")
    print("=" * 60)

    bars = create_sample_bars()
    print(f"Sample bars: {len(bars)} rows, {bars.index.nlevels} levels")
    print(f"  Symbols: {bars.index.get_level_values('symbol').unique().tolist()}")
    print(f"  Dates: {bars.index.get_level_values('date').min()} to {bars.index.get_level_values('date').max()}")
    print()

    factors = [
        ("Momentum(20)", MomentumFactor(window=20)),
        ("Momentum(60)", MomentumFactor(window=60)),
        ("Trend(5,20)", TrendFactor(short_window=5, long_window=20)),
        ("MeanReversion(20)", MeanReversionFactor(window=20)),
        ("Value", ValueFactor()),
        ("MA_Cross(5,20)", MACrossSignal(short_window=5, long_window=20)),
    ]

    all_passed = True
    for name, factor in factors:
        try:
            values = factor.compute(bars)
            if values.empty:
                print(f"  ❌ {name}: Empty result")
                all_passed = False
            else:
                last_date = values.index.get_level_values("date").max()
                last_vals = values.loc[last_date].squeeze()
                print(f"  ✅ {name}: {len(values)} values, range=[{values.min().iloc[0]:.4f}, {values.max().iloc[0]:.4f}]")
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            all_passed = False

    print()
    # Test composite
    print("Testing CompositeFactor:")
    composite = CompositeFactor([
        (MomentumFactor(20), 0.3),
        (TrendFactor(5, 20), 0.3),
        (ValueFactor(), 0.4),
    ])
    try:
        cv = composite.compute(bars)
        if not cv.empty:
            print(f"  ✅ Composite: {len(cv)} values")
        else:
            print(f"  ❌ Composite: Empty")
            all_passed = False
    except Exception as e:
        print(f"  ❌ Composite: {e}")
        all_passed = False

    print()
    return all_passed


def test_broker():
    """Test SimulatedBroker with A-share rules."""
    print("=" * 60)
    print("Phase 2 Test: SimulatedBroker (A-share rules)")
    print("=" * 60)

    broker = SimulatedBroker(initial_capital=1_000_000.0)
    from datetime import date as d

    today = d(2025, 6, 3)

    # Test 1: Buy
    print("\n[1] Buy 100 shares of 000001.SZ at 11.00:")
    order = Order(symbol="000001.SZ", side=Side.BUY, quantity=100)
    result = broker.submit_order(order, today, 11.00)
    print(f"    Status: {result.status.value}")
    print(f"    Filled: {result.filled_quantity} @ {result.filled_price:.2f}")
    print(f"    Commission: {result.commission:.2f}")
    print(f"    Cash remaining: {broker.cash:.2f}")
    assert result.is_filled
    assert broker.cash < 1_000_000

    # Test 2: T+1 violation (same day sell)
    print("\n[2] T+1 violation - sell same day:")
    order2 = Order(symbol="000001.SZ", side=Side.SELL, quantity=100)
    result2 = broker.submit_order(order2, today, 11.10)
    print(f"    Status: {result2.status.value}")
    print(f"    Reason: {result2.reject_reason}")
    assert result2.is_rejected

    # Test 3: T+1 release next day
    print("\n[3] T+1 release - sell next day:")
    tomorrow = d(2025, 6, 4)
    broker.update_available_positions(tomorrow)
    result3 = broker.submit_order(order2, tomorrow, 11.10)
    print(f"    Status: {result3.status.value}")
    print(f"    Filled: {result3.filled_quantity} @ {result3.filled_price:.2f}")
    print(f"    Commission: {result3.commission:.2f}")
    assert result3.is_filled

    # Test 4: Lot size enforcement
    print("\n[4] Lot size enforcement (buy 150):")
    order4 = Order(symbol="000001.SZ", side=Side.BUY, quantity=150)
    result4 = broker.submit_order(order4, tomorrow, 11.00)
    print(f"    Requested: 150, Adjusted to: {result4.filled_quantity}")
    assert result4.filled_quantity == 100  # Rounded down to 100

    # Test 5: Insufficient cash
    print("\n[5] Insufficient cash:")
    order5 = Order(symbol="000001.SZ", side=Side.BUY, quantity=1_000_000)
    result5 = broker.submit_order(order5, tomorrow, 11.00)
    print(f"    Status: {result5.status.value}")
    print(f"    Reason: {result5.reject_reason[:50]}")
    assert result5.is_rejected

    summary = broker.summary()
    print(f"\n    Broker summary:")
    print(f"      Trades: {summary['total_trades']} (B:{summary['buys']}, S:{summary['sells']})")
    print(f"      Total commission: {summary['total_commission']:.2f}")

    print()
    return True


def test_backtest():
    """Test full backtest run."""
    print("=" * 60)
    print("Phase 2 Test: Backtest Engine")
    print("=" * 60)

    bars = create_sample_bars()

    print("\n[1] Running backtest with Momentum + Trend factors...")
    engine = BacktestEngine(
        bars=bars,
        factors=[
            MomentumFactor(window=10),
            TrendFactor(short_window=3, long_window=10),
        ],
        factor_weights=[0.5, 0.5],
        top_n=2,
        rebalance_days=5,
        initial_capital=1_000_000.0,
    )

    result = engine.run()

    print(f"\n[2] Results:")
    print(f"    Trading days: {len(result.daily_returns)}")
    print(f"    Initial capital: {result.initial_capital:,.2f}")
    print(f"    Final value: {result.final_value:,.2f}")
    print(f"    Total trades: {len(result.trades)}")

    metrics = result.metrics
    print(f"\n[3] Performance Metrics:")
    for key, val in metrics.items():
        if isinstance(val, float) and "ratio" in key:
            print(f"    {key}: {val:.3f}")
        elif isinstance(val, float) and ("return" in key or "drawdown" in key or "vol" in key):
            print(f"    {key}: {val:.2f}%")
        else:
            print(f"    {key}: {val}")

    # Verify result makes sense
    assert len(result.daily_returns) > 0
    assert result.final_value > 0
    assert result.metrics["sharpe_ratio"] is not None

    print()
    return True


def test_live_data():
    """Test backtest with real Sina data."""
    print("=" * 60)
    print("Phase 2 Test: Real Data Backtest")
    print("=" * 60)

    agg = DataAggregator()

    symbols = ["600519.SH", "000001.SZ", "300750.SZ", "000858.SZ", "601318.SH"]

    print("\n[1] Fetching real data for 5 stocks...")
    df = agg.get_bars_batch(symbols, date(2025, 1, 1), date(2025, 6, 3))
    print(f"    Got {len(df)} bars for {df.index.get_level_values('symbol').nunique()} symbols")

    if df.empty:
        print("    ❌ No data - skipping")
        return True

    print("\n[2] Running backtest...")
    engine = BacktestEngine(
        bars=df,
        factors=[
            MomentumFactor(window=10),
            TrendFactor(short_window=5, long_window=20),
        ],
        factor_weights=[0.4, 0.6],
        top_n=2,
        rebalance_days=5,
        initial_capital=1_000_000.0,
    )

    result = engine.run()

    print(f"\n[3] Results:")
    print(f"    Days: {len(result.daily_returns)}")
    print(f"    P&L: {result.final_value - result.initial_capital:+,.2f}")
    print(f"    Trades: {len(result.trades)}")

    metrics = result.metrics
    for key, val in metrics.items():
        if isinstance(val, float) and ("return" in key or "drawdown" in key or "vol" in key):
            print(f"    {key}: {val:.2f}%")
        elif isinstance(val, float):
            print(f"    {key}: {val:.3f}")
        else:
            print(f"    {key}: {val}")

    print()
    return True


if __name__ == "__main__":
    all_ok = True

    # Test 1: Factors
    all_ok &= test_factors()

    # Test 2: Broker
    all_ok &= test_broker()

    # Test 3: Backtest (synthetic)
    all_ok &= test_backtest()

    # Test 4: Real data backtest
    all_ok &= test_live_data()

    print("=" * 60)
    if all_ok:
        print("✅ ALL PHASE 2 TESTS PASSED")
    else:
        print("❌ Some tests failed")
    print("=" * 60)
