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
    _load_bars,
    _sanitize_for_json,
)
from src.core.broker_base import FeeCalculator
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


def _overnight_forward_return_horizon(bars: pd.DataFrame, h: int) -> pd.DataFrame:
    """h 日隔夜 forward return: open(t+h)/close(t) - 1。

    沿用 compute_overnight_forward_return 的 stack 口径（open/close，非收盘-收盘），
    仅把 shift(-1) 推广为 shift(-h)。衰减探针用此构造多日 horizon 的隔夜收益。
    """
    bars = bars.sort_index()
    close = bars["close"].unstack(level="symbol")
    open_ = bars["open"].unstack(level="symbol").shift(-h)
    ret = open_ / close - 1.0
    return (
        ret.stack(future_stack=True)
        .to_frame(name="return")
        .rename_axis(["date", "symbol"])["return"]
        .to_frame()
    )


def autocorrelation_probe(bars, factor, horizons=(1, 2, 3, 5)) -> dict:
    """自相关三项：多日衰减 ICIR + 滞后基线 + 换手率代理。

    区分"隔夜 ICIR 0.36 是真实 edge"与"机械自相关"。overnight_momentum = 滞后隔夜，
    forward return = 次日隔夜；若隔夜序列自相关，IC 看似高但并非可交易 edge。

    1) 衰减：各 horizon 的隔夜 forward（open(t+h)/close(t)-1）对因子算 ICIR。
       真 edge 缓慢衰减；自相关 1 日强后快速塌。
    2) 滞后基线：因子替换成"前一日隔夜收益"（按 symbol shift(1)），forward return 不变，
       算 IC —— 即 trivial 因子（昨日隔夜预测今日隔夜）的 IC，是"自相关地板"。
    3) 换手率代理：因子逐日横截面排名变动比例。自相关信号换手率极低。
    """
    fr1 = compute_overnight_forward_return(bars)  # horizon=1
    fv = factor.compute(bars)

    # 1) 衰减：各 horizon 的 ICIR + mean IC（隔夜 open/close 口径，非 ICAnalyzer.compute_forward_returns 收盘-收盘）。
    #    decay_ic_mean_by_horizon 与 lagged_baseline_corr 同为 mean IC（ICIR 是 mean/std，单位不同不可直比），
    #    让 Task 6 能像对像对比：factor mean IC@h1 ≈ lagged_baseline_corr → 自相关；≫ 则真 edge。
    decay_icir = {}
    decay_ic_mean = {}
    for h in horizons:
        fr_h = _overnight_forward_return_horizon(bars, h)
        ic = ICAnalyzer(forward_period=h)
        ic_series = ic.compute_ic(fv, fr_h)
        rank_ic = ic.compute_rank_ic(fv, fr_h)
        summary = ic.ic_summary(ic_series, rank_ic)
        decay_icir[h] = summary.icir
        decay_ic_mean[h] = summary.ic_mean

    # 2) 滞后基线：因子替换成"前一日隔夜收益"（按 symbol shift），forward return 不变（1 日）。
    #    按 symbol shift（groupby(level="symbol").shift(1)）避免跨 symbol 边界串味；
    #    列名 "lagged_factor" 避开与 forward return 列 "return" 在 compute_ic join 时的碰撞。
    lagged_factor = (
        fr1.groupby(level="symbol")["return"].shift(1).to_frame(name="lagged_factor")
    )
    ic_base = ICAnalyzer(forward_period=1)
    base_ic = ic_base.compute_ic(lagged_factor, fr1).dropna()
    lagged_baseline_corr = float(base_ic.mean()) if len(base_ic) > 0 else None

    # 3) 换手率代理：因子逐日横截面排名变动比例 = rank(t)!=rank(t-1) 的 symbol 占比均值。
    #    droplevel("date")：groupby(level="date") 后各组仍带 (date,symbol) 全 MultiIndex，
    #      不丢 date 则相邻日 grp.index.intersection(prev.index) 比较 (date,symbol) 全元组、
    #      交集恒为空 → turnover 恒 None。必须 droplevel 让 index 退化为 symbol。
    #    NaN 守卫：仅比较 prev/cur 均非 NaN 的 symbol，避免 NaN!=NaN（pandas 下为 True）虚增换手。
    ranks = fv.groupby(level="date").rank(pct=True)
    rank_series = ranks.iloc[:, 0]
    by_date = rank_series.groupby(level="date")
    turnover_days = []
    prev = None
    for _d, grp in by_date:
        cur = grp.droplevel("date")
        if prev is not None:
            common = cur.index.intersection(prev.index)
            if len(common) > 0:
                c = cur.loc[common]
                p = prev.loc[common]
                valid = ~(c.isna() | p.isna())
                n_valid = int(valid.sum())
                if n_valid > 0:
                    changed = int((c[valid] != p[valid]).sum())
                    turnover_days.append(float(changed) / n_valid)
        prev = cur
    turnover_proxy = float(pd.Series(turnover_days).mean()) if turnover_days else None

    return {
        "factor": factor.name,
        "decay_icir_by_horizon": {int(h): v for h, v in decay_icir.items()},
        "decay_ic_mean_by_horizon": {int(h): v for h, v in decay_ic_mean.items()},
        "lagged_baseline_corr": lagged_baseline_corr,
        "turnover_proxy": turnover_proxy,
    }


def net_edge(bars, factor, trade_capital=100000, top_n=5, n_quantiles=5) -> dict:
    """扣成本净 edge：口径 A 做多单边 + 口径 B 多空价差。

    成本复用 FeeCalculator.from_settings()（真实费率，与回测引擎一致）。成本率依赖
    金额（min_commission=5 下限），故用典型交易额建模：单笔金额 = trade_capital /
    top_n（如 10 万 / 5 = 2 万/笔），让 min_commission 真实生效。

    - 口径 A 做多单边：top 分位组平均隔夜收益 − 买入成本率（贴实盘，S01 只做多）。
    - 口径 B 多空价差：top−bottom 价差 − 往返成本率（纯因子信号，S01 不做空，
      价差高估实际可赚）。

    收益率为日度平均（未年化，与 horizon=1 一致）。
    """
    fr = compute_overnight_forward_return(bars)
    fv = factor.compute(bars)
    qa = QuantileAnalyzer(n_quantiles=n_quantiles)
    qresult = qa.analyze(fv, fr)

    # 分位组日度平均收益
    qr = qresult.quantile_returns
    top_col = qr.columns[-1]
    gross_top = float(qr[top_col].mean()) if len(qr) else 0.0
    gross_spread = float(qresult.spread) if qresult.spread is not None else 0.0

    # 成本率（典型交易额 = trade_capital / top_n）
    fees = FeeCalculator.from_settings()
    amount = trade_capital / top_n
    cost_buy_rate = fees.calc_commission(amount, "buy") / amount
    cost_sell_rate = fees.calc_commission(amount, "sell") / amount
    cost_roundtrip_rate = cost_buy_rate + cost_sell_rate

    return {
        "factor": factor.name,
        "gross_top_quantile_return": gross_top,
        "gross_spread": gross_spread,
        "trade_amount_per_leg": float(amount),
        "cost_buy_rate": float(cost_buy_rate),
        "cost_sell_rate": float(cost_sell_rate),
        "cost_roundtrip_rate": float(cost_roundtrip_rate),
        "net_long_only": float(gross_top - cost_buy_rate),        # 口径 A
        "net_long_short": float(gross_spread - cost_roundtrip_rate),  # 口径 B
    }


def run_walkforward(bars, train_days=60, step_days=10, horizons=(1, 2, 3, 5), trade_capital=100000, top_n=5, n_quantiles=5) -> dict:
    factors = [
        TailSessionFactor(breakout_window=20, trend_window=5, volume_ratio_threshold=1.2),
        OvernightMomentumFactor(smoothing_window=1),
    ]
    out_factors = []
    for f in factors:
        out_factors.append({
            "factor": f.name,
            "walk_forward": walk_forward_stability(bars, f, train_days, step_days, n_quantiles),
            "autocorrelation": autocorrelation_probe(bars, f, horizons=horizons),
            "net_edge": net_edge(bars, f, trade_capital=trade_capital, top_n=top_n, n_quantiles=n_quantiles),
        })
    return {
        "forward_return": "overnight_open/close-1",
        "window": {"train_days": train_days, "step_days": step_days, "horizons": list(horizons)},
        "factors": out_factors,
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-forward IC validation for tail factors.")
    parser.add_argument("--bars-dataset")
    parser.add_argument("--offline-cache", action="store_true")
    parser.add_argument("--bars-cache-dir", default="data/cache/bars")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-06-01")
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=10)
    parser.add_argument("--n-quantiles", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--trade-capital", type=float, default=100000)
    parser.add_argument("--horizons", type=int, nargs="+", default=[1, 2, 3, 5])
    parser.add_argument("--out", default="reports/tail_session/factor_diagnosis_walkforward.json")
    args = parser.parse_args()

    bars = _load_bars(args)
    result = run_walkforward(
        bars, train_days=args.train_days, step_days=args.step_days,
        horizons=tuple(args.horizons), trade_capital=args.trade_capital,
        top_n=args.top_n, n_quantiles=args.n_quantiles,
    )
    result = _sanitize_for_json(result)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
