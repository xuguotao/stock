import math

import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.diagnose_tail_factors_walkforward import (
    walk_forward_folds,
    diagnose_fold,
    walk_forward_stability,
    autocorrelation_probe,
)
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


def test_diagnose_fold_subsets_by_fold_dates():
    """fold_dates 必须真正限制 IC/分层的计算日期子集。

    若 diagnose_fold 内部的 .isin(date_set) 过滤变成 no-op（在全部 120 日上算 IC），
    仅靠键存在性断言无法发现。这里用两个不同大小的子集分别调用 diagnose_fold，
    断言其 IC 不同，从而证明 fold_dates 子集被真正应用。当 .isin() 失效时两次调用
    会在相同的全量数据上聚合，ic_mean 必然相等，断言失败。
    """
    bars = _fake_bars_long()
    fr = compute_overnight_forward_return(bars)
    fv = OvernightMomentumFactor(smoothing_window=1).compute(bars)
    dates = bars.index.get_level_values("date").unique().sort_values()

    # 小子集（前 20 交易日）vs 大子集（前 60 交易日）。8 symbols/日，远超
    # ICAnalyzer 的 ≥3 obs/日 与 QuantileAnalyzer 的 ≥n_quantiles 要求。
    factor = OvernightMomentumFactor(smoothing_window=1)
    result_small = diagnose_fold(fv, fr, dates[0:20], factor, n_quantiles=3)
    result_large = diagnose_fold(fv, fr, dates[0:60], factor, n_quantiles=3)

    # 键存在性仍成立。
    assert result_large["factor"] == "overnight_momentum"
    assert "ic_mean" in result_large["ic"] and "icir" in result_large["ic"]
    assert "spread_return" in result_large["quantile"]

    # 子集必须生效：不同 fold_dates → 不同 IC。若 .isin() 过滤为 no-op，两次调用都在
    # 全部 120 日上聚合，两个 ic_mean 必然相等 → 断言失败。1e-6 容差远低于实际差异
    # （约 0.006），又远高于浮点噪声，确保对退化全量相等情形依然失败。
    ic_small = result_small["ic"]["ic_mean"]
    ic_large = result_large["ic"]["ic_mean"]
    assert abs(ic_small - ic_large) > 1e-6, (
        f"small(20d) 与 large(60d) 子集 ic_mean 相同 ({ic_small} == {ic_large})，"
        "fold_dates 子集未被应用"
    )


def test_walk_forward_stability_summarizes_across_folds():
    bars = _fake_bars_long()
    result = walk_forward_stability(
        bars, OvernightMomentumFactor(smoothing_window=1), train_days=60, step_days=10, n_quantiles=3
    )
    assert result["factor"] == "overnight_momentum"
    assert result["fold_count"] > 0
    assert "icir_mean" in result and "icir_std" in result
    assert "icir_positive_fold_ratio" in result and "worst_fold_icir" in result
    assert 0.0 <= result["icir_positive_fold_ratio"] <= 1.0
    assert len(result["folds"]) == result["fold_count"]


def test_autocorrelation_probe_returns_three_signals():
    bars = _fake_bars_long()
    result = autocorrelation_probe(bars, OvernightMomentumFactor(smoothing_window=1), horizons=[1, 2, 3])
    assert result["factor"] == "overnight_momentum"
    assert set(result["decay_icir_by_horizon"].keys()) == {1, 2, 3}
    assert result["lagged_baseline_corr"] is not None
    assert 0.0 <= result["turnover_proxy"] <= 1.0


def test_lagged_baseline_uses_prior_day_overnight():
    """滞后基线：因子替换成前一日隔夜，forward return 不变。"""
    bars = _fake_bars_long(n_days=80)
    result = autocorrelation_probe(bars, OvernightMomentumFactor(smoothing_window=1), horizons=[1])
    # 应产出一个有限数值（即便数据噪声大，也不会 None）
    assert result["lagged_baseline_corr"] is not None
    assert math.isfinite(result["lagged_baseline_corr"])


def test_lagged_baseline_is_autocorrelation_floor_not_self_correlation():
    """滞后基线必须是"昨日隔夜预测今日隔夜"的 IC（自相关地板），而非 corr(因子, 因子)=1.0。

    对 overnight_momentum（smoothing_window=1），factor==fr1.shift(1) 严格相等；
    若实现误把"因子本身"当作滞后期与因子做相关（brief 草稿的 corr(fv, lagged_overnight)），
    会得到退化的 1.0。正确实现用 compute_ic(lagged_overnight, fr1) 给出有意义的自相关地板
    （对随机数据 ~0.01），远小于 1.0。
    """
    bars = _fake_bars_long()
    result = autocorrelation_probe(bars, OvernightMomentumFactor(smoothing_window=1), horizons=[1])
    assert result["lagged_baseline_corr"] is not None
    # 退化自相关 corr(factor, factor)≈1.0 必须被拒绝；真实地板远低于 1.0。
    assert abs(result["lagged_baseline_corr"] - 1.0) > 0.05
