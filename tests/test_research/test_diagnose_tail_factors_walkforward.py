import pandas as pd
import numpy as np
from datetime import date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.diagnose_tail_factors_walkforward import walk_forward_folds, diagnose_fold
from scripts.diagnose_tail_factors import compute_overnight_forward_return
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor


def _fake_bars_long(n_days=120, n_symbols=8):
    """n_days 交易日 × n_symbols，够分 60/10 出多折。"""
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    syms = [f"00000{i}.SZ" for i in range(n_symbols)]
    idx = pd.MultiIndex.from_product([dates, syms], names=["date", "symbol"])
    rng = np.random.default_rng(42)
    rows = len(idx)
    df = pd.DataFrame({
        "open": 10 + rng.normal(0, 0.5, rows),
        "close": 10 + rng.normal(0, 0.5, rows),
        "high": 11 + rng.normal(0, 0.5, rows),
        "low": 9 + rng.normal(0, 0.5, rows),
        "volume": 1000 + rng.integers(0, 500, rows),
        "amount": 1e6 + rng.integers(0, 500000, rows),
    }, index=idx)
    return df


def test_walk_forward_folds_are_rolling_fixed_windows():
    """rolling 固定窗:每折 60 天、步进 10。120 交易日 → 7 折。"""
    bars = _fake_bars_long()
    folds = walk_forward_folds(bars, train_days=60, step_days=10)
    # 120 交易日: i*10+60<=120 → i<=6 → i=0..6 → 7 折
    assert len(folds) == 7
    dates = bars.index.get_level_values("date").unique().sort_values()
    # 每折训练窗长度=60,且相邻折起点后移
    for i, (start, end) in enumerate(folds):
        fold_dates = dates[(dates >= start) & (dates <= end)]
        assert len(fold_dates) == 60, f"fold {i} has {len(fold_dates)} days, expected 60"
        if i > 0:
            assert start > folds[i - 1][0]  # 起点后移


def test_diagnose_fold_returns_ic_and_quantile_for_subset():
    bars = _fake_bars_long()
    fr = compute_overnight_forward_return(bars)
    fv = OvernightMomentumFactor(smoothing_window=1).compute(bars)
    dates = bars.index.get_level_values("date").unique().sort_values()
    fold_dates = dates[0:60]  # 第一折训练窗
    result = diagnose_fold(fv, fr, fold_dates, OvernightMomentumFactor(smoothing_window=1), n_quantiles=3)
    assert result["factor"] == "overnight_momentum"
    assert "ic_mean" in result["ic"] and "icir" in result["ic"]
    assert "spread_return" in result["quantile"]
