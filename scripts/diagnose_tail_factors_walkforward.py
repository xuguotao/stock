"""尾盘因子 walk-forward IC 验证：滚动 IC + 自相关探针 + 扣成本净 edge。"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.diagnose_tail_factors import (
    compute_overnight_forward_return,
    _sanitize_for_json,
)
from src.research.factor_analysis.ic_analysis import ICAnalyzer
from src.research.factor_analysis.quantile import QuantileAnalyzer
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.factors.tail_session import TailSessionFactor


def walk_forward_folds(bars: pd.DataFrame, train_days: int = 60, step_days: int = 10) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """按交易日生成 walk-forward 折（rolling 固定窗，与 tail_model.py 一致）。

    每折训练窗为固定 train_days 个交易日、向后滑动 step_days：
    fold_i 的训练窗 = trade_dates[i*step_days : i*step_days + train_days]。
    相邻折重叠 (train_days - step_days) 天。返回每折训练窗的 (start, end) Timestamp。
    """
    dates = bars.index.get_level_values("date").unique().sort_values()
    n = len(dates)
    folds = []
    i = 0
    while i * step_days + train_days <= n:
        start = dates[i * step_days]
        end = dates[i * step_days + train_days - 1]
        folds.append((start, end))
        i += 1
    return folds


def diagnose_fold(fv: pd.DataFrame, fr: pd.DataFrame, fold_dates, factor, n_quantiles: int = 5) -> dict:
    """对单折日期子集算 IC + 分层。

    直接用 ICAnalyzer/QuantileAnalyzer 在 fv/fr 的日期子集上算 IC 与分层，不调
    diagnose_factor：diagnose_factor 会重跑 factor.compute(bars)，而 fv 已传入，
    重算既冗余又依赖完整 bars（折子集外可能没有）。factor 仅取其 .name 用于结果
    标识。
    """
    date_set = set(pd.Timestamp(d) for d in fold_dates)
    fv_sub = fv[fv.index.get_level_values("date").isin(date_set)]
    fr_sub = fr[fr.index.get_level_values("date").isin(date_set)]
    # diagnose_factor 需要 bars 来调 factor.compute，但我们已传入 fv；直接算 IC 避免重算
    ic = ICAnalyzer(forward_period=1)
    ic_series = ic.compute_ic(fv_sub, fr_sub)
    rank_ic = ic.compute_rank_ic(fv_sub, fr_sub)
    summary = ic.ic_summary(ic_series, rank_ic)
    qa = QuantileAnalyzer(n_quantiles=n_quantiles)
    qresult = qa.analyze(fv_sub, fr_sub)
    return {
        "factor": factor.name,
        "ic": summary.to_dict(),
        "quantile": qresult.summary,
        "quantile_returns_by_q": {q: float(v) for q, v in qresult.quantile_returns.mean().items()},
    }


def walk_forward_stability(bars, factor, train_days=60, step_days=10, n_quantiles=5) -> dict:
    """滚动窗逐折算 IC，汇总跨折稳定性。"""
    fr = compute_overnight_forward_return(bars)
    fv = factor.compute(bars)
    dates = bars.index.get_level_values("date").unique().sort_values()
    folds = walk_forward_folds(bars, train_days=train_days, step_days=step_days)

    fold_results = []
    for train_start, train_end in folds:
        mask = (dates >= train_start) & (dates <= train_end)
        fold_dates = dates[mask]
        if len(fold_dates) < n_quantiles + 1:
            continue
        fold_results.append(diagnose_fold(fv, fr, fold_dates, factor, n_quantiles=n_quantiles))

    if not fold_results:
        return {"factor": factor.name, "fold_count": 0, "folds": [], "icir_mean": None,
                "icir_std": None, "icir_positive_fold_ratio": None, "worst_fold_icir": None,
                "ic_positive_ratio_mean": None}

    icirs = [f["ic"]["icir"] for f in fold_results if f["ic"]["icir"] is not None]
    ic_pos = [f["ic"]["ic_positive_ratio"] for f in fold_results if f["ic"]["ic_positive_ratio"] is not None]
    return {
        "factor": factor.name,
        "fold_count": len(fold_results),
        "folds": fold_results,
        "icir_mean": float(pd.Series(icirs).mean()) if icirs else None,
        "icir_std": float(pd.Series(icirs).std()) if icirs else None,
        "icir_positive_fold_ratio": float(sum(1 for x in icirs if x > 0) / len(icirs)) if icirs else None,
        "worst_fold_icir": float(min(icirs)) if icirs else None,
        "ic_positive_ratio_mean": float(pd.Series(ic_pos).mean()) if ic_pos else None,
    }
