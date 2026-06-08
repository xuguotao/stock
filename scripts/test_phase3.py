#!/usr/bin/env python3
"""Test Phase 3: Factor Research Pipeline + Portfolio Optimization."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

import numpy as np
import pandas as pd

from src.data.aggregator import DataAggregator
from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor
from src.strategy.factors.mean_reversion import MeanReversionFactor
from src.research.factor_analysis.ic_analysis import ICAnalyzer
from src.research.factor_analysis.quantile import QuantileAnalyzer
from src.research.factor_analysis.neutralization import FactorNeutralizer
from src.research.portfolio.optimizer import PortfolioOptimizer


def create_test_data():
    """Get real data from Sina."""
    agg = DataAggregator()
    symbols = ["600519.SH", "000001.SZ", "300750.SZ", "000858.SZ", "601318.SH",
               "600036.SH", "000333.SZ", "601888.SH", "002714.SZ", "600900.SH"]
    return agg.get_bars_batch(symbols, date(2025, 1, 1), date(2025, 6, 3))


def test_ic_analysis():
    """Test IC analysis."""
    print("=" * 60)
    print("Phase 3 Test: IC Analysis")
    print("=" * 60)

    bars = create_test_data()
    if bars.empty:
        print("  No data")
        return False

    print(f"  Data: {len(bars)} bars, {bars.index.get_level_values(1).nunique()} symbols")
    prices = bars["close"].unstack(level=1)

    momentum = MomentumFactor(window=10)
    fv = momentum.compute(bars)

    analyzer = ICAnalyzer(forward_period=1)
    fr = analyzer.compute_forward_returns(prices)
    ic = analyzer.compute_ic(fv, fr)
    rank_ic = analyzer.compute_rank_ic(fv, fr)

    print(f"  IC days: {len(ic)}")
    summary = analyzer.ic_summary(ic, rank_ic)
    for k, v in summary.to_dict().items():
        print(f"    {k}: {v}")
    print(f"  ✅ IC analysis complete\n")
    return True


def test_quantile():
    """Test quantile analysis."""
    print("=" * 60)
    print("Phase 3 Test: Quantile Analysis")
    print("=" * 60)

    bars = create_test_data()
    if bars.empty:
        return False

    prices = bars["close"].unstack(level=1)
    ic_analyzer = ICAnalyzer(forward_period=1)
    fr = ic_analyzer.compute_forward_returns(prices)

    for name, factor in [("Momentum(5)", MomentumFactor(5)), ("Trend(3,10)", TrendFactor(3, 10))]:
        fv = factor.compute(bars)
        qa = QuantileAnalyzer(n_quantiles=3)
        result = qa.analyze(fv, fr)

        if result.quantile_returns.empty:
            print(f"  {name}: no valid data")
            continue

        print(f"  {name}: spread={result.spread*100:.4f}%, mono={result.monotonicity:.4f}")
        print(f"  ✅ {name} quantile analysis complete")

    print()
    return True


def test_neutralization():
    """Test factor neutralization."""
    print("=" * 60)
    print("Phase 3 Test: Factor Neutralization")
    print("=" * 60)

    bars = create_test_data()
    if bars.empty:
        return False

    fv = MomentumFactor(10).compute(bars)
    symbols = bars.index.get_level_values("symbol").unique()
    dates = bars.index.get_level_values("date").unique()

    industry_map = {
        "600519.SH": "食品饮料", "000001.SZ": "银行", "300750.SZ": "电气设备",
        "000858.SZ": "食品饮料", "601318.SH": "非银金融", "600036.SH": "银行",
        "000333.SZ": "家用电器", "601888.SH": "旅游餐饮", "002714.SZ": "农林牧渔",
        "600900.SH": "公用事业",
    }
    idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
    industry = pd.Series([industry_map.get(s, "综合") for s in symbols] * len(dates), index=idx)
    mcap = pd.Series(np.random.lognormal(20, 1, len(idx)), index=idx)

    neutralizer = FactorNeutralizer()
    raw = fv.mean().iloc[0]
    neutral = neutralizer.neutralize(fv, industry_codes=industry)
    neutral2 = neutralizer.neutralize(fv, industry_codes=industry, market_cap=mcap)

    print(f"  Raw mean: {raw:.6f}")
    print(f"  Neutralized (industry): {neutral.mean().iloc[0]:.6f}")
    print(f"  Neutralized (industry+mcap): {neutral2.mean().iloc[0]:.6f}")
    print(f"  ✅ Neutralization complete\n")
    return True


def test_portfolio_optimizer():
    """Test portfolio optimization."""
    print("=" * 60)
    print("Phase 3 Test: Portfolio Optimization (CVXPY)")
    print("=" * 60)

    bars = create_test_data()
    if bars.empty:
        return False

    prices = bars["close"].unstack(level=1)
    returns = prices.pct_change().dropna()
    symbols = returns.columns.tolist()
    n = len(symbols)

    print(f"  Assets: {n}")
    mu = returns.mean().values * 252
    cov = returns.cov().values * 252

    opt = PortfolioOptimizer(max_weight=0.30)

    # Equal weight
    ew = opt.equal_weight(n)
    m_ew = opt.portfolio_metrics(ew, mu, cov)
    print(f"\n  Equal Weight: sharpe={m_ew['sharpe_ratio']}, vol={m_ew['volatility']}%")

    # Max Sharpe
    ms = opt.max_sharpe(mu, cov)
    m_ms = opt.portfolio_metrics(ms, mu, cov)
    print(f"\n  Max Sharpe:")
    for k, v in m_ms.items():
        print(f"    {k}: {v}")
    for sym, w in zip(symbols, ms):
        if w > 0.001:
            print(f"    {sym}: {w*100:.1f}%")

    # Min Variance
    mv = opt.min_variance(cov)
    m_mv = opt.portfolio_metrics(mv, mu, cov)
    print(f"\n  Min Variance: sharpe={m_mv['sharpe_ratio']}, vol={m_mv['volatility']}%")

    # Risk Parity
    rp = opt.risk_parity(cov)
    m_rp = opt.portfolio_metrics(rp, mu, cov)
    print(f"\n  Risk Parity: sharpe={m_rp['sharpe_ratio']}, vol={m_rp['volatility']}%")

    print()
    return True


if __name__ == "__main__":
    all_ok = True
    all_ok &= test_ic_analysis()
    all_ok &= test_quantile()
    all_ok &= test_neutralization()
    all_ok &= test_portfolio_optimizer()

    print("=" * 60)
    print("ALL PHASE 3 TESTS PASSED" if all_ok else "Some tests failed")
    print("=" * 60)
