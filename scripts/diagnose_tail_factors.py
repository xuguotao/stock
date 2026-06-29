"""尾盘因子诊断：度量 tail_session / overnight_momentum 是否有预测力。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.factor_analysis.ic_analysis import ICAnalyzer
from src.research.factor_analysis.quantile import QuantileAnalyzer
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.factors.tail_session import TailSessionFactor


def compute_overnight_forward_return(bars: pd.DataFrame) -> pd.DataFrame:
    """S01 隔夜持仓 forward return: open(t+1)/close(t) - 1。

    禁止用 ICAnalyzer.compute_forward_returns（收盘-收盘）。
    """
    bars = bars.sort_index()
    close = bars["close"].unstack(level="symbol")          # date × symbol
    nxt_open = bars["open"].unstack(level="symbol").shift(-1)
    overnight = (nxt_open / close - 1.0)
    return (
        overnight.stack(future_stack=True)
        .to_frame(name="return")
        .rename_axis(["date", "symbol"])["return"]
        .to_frame()
    )


def diagnose_factor(bars, factor, forward_returns, n_quantiles=5):
    fv = factor.compute(bars)
    ic = ICAnalyzer(forward_period=1)
    ic_series = ic.compute_ic(fv, forward_returns)
    rank_ic = ic.compute_rank_ic(fv, forward_returns)
    summary = ic.ic_summary(ic_series, rank_ic)
    qa = QuantileAnalyzer(n_quantiles=n_quantiles)
    qresult = qa.analyze(fv, forward_returns)
    return {
        "factor": factor.name,
        "ic": summary.to_dict(),
        "quantile": qresult.summary,
    }


def run_diagnosis(bars, n_quantiles=5):
    fr = compute_overnight_forward_return(bars)
    factors = [
        TailSessionFactor(breakout_window=20, trend_window=5, volume_ratio_threshold=1.2),
        OvernightMomentumFactor(smoothing_window=1),
    ]
    return {"forward_return": "overnight_open/close-1", "factors": [diagnose_factor(bars, f, fr, n_quantiles) for f in factors]}


def main():
    # 数据加载在 Task 3 接入；此处先放 CLI 骨架
    parser = argparse.ArgumentParser(description="Diagnose tail-session factors (IC/quantile).")
    parser.add_argument("--bars-dataset", help="parquet research dataset path")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-06-01")
    parser.add_argument("--out", default="reports/tail_session/factor_diagnosis.json")
    args = parser.parse_args()
    print(json.dumps({"todo": "wire data loading in Task 3"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
