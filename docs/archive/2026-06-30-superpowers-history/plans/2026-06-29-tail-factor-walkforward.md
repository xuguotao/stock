# 尾盘因子 Walk-Forward IC 验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 walk-forward 诊断脚本，用滚动 IC + 自相关探针 + 扣成本净 edge 逐条确认或推翻单次诊断报告对 overnight 因子打的三個折扣（in-sample / 自相关 / 未扣成本）。

**Architecture:** 新独立脚本 `scripts/diagnose_tail_factors_walkforward.py`，import 复用 `diagnose_tail_factors` 的隔夜 forward-return + `diagnose_factor`，叠加分折循环、自相关三项、净 edge 两口径、JSON 序列化。不修改任何现有生产代码。walk-forward 窗口写法参考 `src/ml/tail_model.py:43`；成本费率复用 `src/core/broker_base.py:FeeCalculator.from_settings()`。

**Tech Stack:** Python, pandas（MultiIndex）, ICAnalyzer/QuantileAnalyzer（`src/research/factor_analysis/`）, FeeCalculator（`src/core/broker_base.py`）, pytest。

---

## Global Constraints

- **只读复用，不改生产代码**：`compute_overnight_forward_return` / `diagnose_factor` / `ICAnalyzer` / `QuantileAnalyzer` / `FeeCalculator` / 因子类全部 import 复用，不修改。所有新代码只在 `scripts/diagnose_tail_factors_walkforward.py` + 测试文件。
- **forward return 必须用隔夜 `open(t+1)/close(t)-1`**（匹配 S01 持仓周期），通过 `compute_overnight_forward_return` 复用，不自造。
- **成本用真实费率**：`FeeCalculator.from_settings()` 取数（佣金 0.00025 / 印花 0.0005 仅卖出 / 最低 5 元 / 过户费 0.00001 / 证管费 0.0000487 买卖都收），不手写魔数。
- **净 edge 两口径都报**：口径 A 做多单边（top 分位平均收益 − 买入成本，贴实盘）、口径 B 多空价差（top−bottom − 往返成本，纯因子信号）。
- **JSON 严格合法**：复用 `diagnose_tail_factors._sanitize_for_json`（NaN/Inf→null），不直接 `default=str`。
- **动态结论**：报告不预设 overnight edge 真不真，跑出什么写什么；三个折扣逐条标注【已推翻 / 坐实 / 部分成立】。
- **默认参数（§9 已定）**：walk-forward 窗口 60/10（与 `tail_model.py` 对齐）；多日衰减 horizon `[1,2,3,5]`；报告末尾写一句"若坐实自相关则指针到 S01 缺失因子"，不展开。
- **数据**：offline parquet cache（`data/cache/bars/`，~339 交易日），窗口 2025-01-01 ~ 2026-06-01。

---

## File Structure

- `scripts/diagnose_tail_factors_walkforward.py`（新建）：walk-forward CLI + 分析逻辑。内部函数：`walk_forward_folds(bars, fv, fr, train_days, step_days)` → 折迭代器；`diagnose_fold(fv, fr, fold_dates, factor, n_quantiles)` → 单折指标；`autocorrelation_probe(bars, factor, horizons)` → 衰减+滞后基线+换手率代理；`net_edge(fv, fr, fold_dates, quantile_count, trade_capital, top_n)` → 口径 A/B；`main()`。
- `tests/test_research/test_diagnose_tail_factors_walkforward.py`（新建）：各函数单测（fake bars）。
- `docs/superpowers/reviews/2026-06-29-tail-factor-walkforward-report.md`（新建）：动态结论报告。
- `reports/tail_session/factor_diagnosis_walkforward.json`（本地生成物，不入库）。

---

### Task 1: walk-forward 折迭代与单折 IC

**Files:**
- Create: `scripts/diagnose_tail_factors_walkforward.py`
- Test: `tests/test_research/test_diagnose_tail_factors_walkforward.py`

**Interfaces:**
- Consumes: `scripts/diagnose_tail_factors.py` 的 `compute_overnight_forward_return(bars)->DataFrame`（单列 `"return"`，`(date,symbol)` MultiIndex）、`diagnose_factor(bars, factor, forward_returns, n_quantiles)->dict`（返回 `{"factor","ic":{...},"quantile":{...}}`，IC 在传入的 `bars`/`forward_returns` 全量上算）。`ICAnalyzer`（`src/research/factor_analysis/ic_analysis.py:47`）。因子 `TailSessionFactor` / `OvernightMomentumFactor`（与生产同参）。
- Produces: `walk_forward_folds(bars, train_days=60, step_days=10) -> list[tuple[date,date]]`（折 (train_start, train_end) 列表，按交易日切，前 60 天为第一折训练窗、之后每步进 10 天一折）；`diagnose_fold(fv, fr, fold_dates, factor, n_quantiles=5) -> dict`（把 fv/fr 按折日期子集切片后调 `diagnose_factor`，返回单折 IC + 分层）。

**Background:** `diagnose_factor` 在传入的 `bars`/`forward_returns` 全量上算 IC，所以 walk-forward 每折需先把 fv/fr 切到该折的日期子集再调。折日期用交易日（去重后的 `index.get_level_values("date").unique()`）。

**折迭代口径：rolling 固定窗（与 `tail_model.py:67-69` 一致）**，非 expanding。每折训练窗是**固定 60 个交易日、向后滑动 10 天**：`fold_i` 的训练窗 = `trade_dates[i*step_days : i*step_days + train_days]`。第一折 = 第 0~59 个交易日，第二折 = 第 10~69 个，相邻折重叠 50 天——更接近 ML walk-forward 的"局部时段"语义。120 交易日、step=10/train=60 → `i*10+60<=120` → `i<=6` → 7 折。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_research/test_diagnose_tail_factors_walkforward.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py -v`
Expected: FAIL（`ModuleNotFoundError: scripts.diagnose_tail_factors_walkforward`）

- [ ] **Step 3: 实现折迭代 + 单折诊断**

```python
# scripts/diagnose_tail_factors_walkforward.py
"""尾盘因子 walk-forward IC 验证：滚动 IC + 自相关探针 + 扣成本净 edge。"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
from datetime import date

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.diagnose_tail_factors import (
    compute_overnight_forward_return,
    diagnose_factor,
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
    """对单折日期子集算 IC + 分层。复用 diagnose_factor（在传入子集上算）。"""
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py -v`
Expected: PASS（两测试通过）

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors_walkforward.py tests/test_research/test_diagnose_tail_factors_walkforward.py
git commit -m "feat: add walk-forward fold iteration and per-fold IC for tail factors"
```

---

### Task 2: walk-forward 稳定性汇总（对应折扣①样本内）

**Files:**
- Modify: `scripts/diagnose_tail_factors_walkforward.py`
- Test: `tests/test_research/test_diagnose_tail_factors_walkforward.py`

**Interfaces:**
- Consumes: Task 1 的 `walk_forward_folds` / `diagnose_fold`。
- Produces: `walk_forward_stability(bars, factor, train_days, step_days, n_quantiles) -> dict`，返回 `{"factor", "fold_count", "folds": [...], "icir_mean", "icir_std", "icir_positive_fold_ratio", "worst_fold_icir", "ic_positive_ratio_mean"}`。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py::test_walk_forward_stability_summarizes_across_folds -v`
Expected: FAIL（`NameError: walk_forward_stability`）

- [ ] **Step 3: 实现 walk_forward_stability**

```python
# scripts/diagnose_tail_factors_walkforward.py 追加
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors_walkforward.py tests/test_research/test_diagnose_tail_factors_walkforward.py
git commit -m "feat: summarize walk-forward IC stability across folds"
```

---

### Task 3: 自相关探针（对应折扣②自相关）—— 衰减 + 滞后基线 + 换手率代理

**Files:**
- Modify: `scripts/diagnose_tail_factors_walkforward.py`
- Test: `tests/test_research/test_diagnose_tail_factors_walkforward.py`

**Interfaces:**
- Consumes: `compute_overnight_forward_return`（隔夜 1 日）；`ICAnalyzer.compute_forward_returns`（多 horizon，收盘-收盘，**仅用于衰减对比**——标注其与隔夜口径不同）。
- Produces: `autocorrelation_probe(bars, factor, horizons=[1,2,3,5]) -> dict`，返回 `{"factor", "decay_icir_by_horizon": {1:..,2:..,3:..,5:..}, "lagged_baseline_corr": float, "turnover_proxy": float}`。

**Background:**
- **衰减**：对每个 horizon h，用隔夜序列的 h 日 forward return（`open(t+h)/close(t)-1`，自定义构造，不复用收盘-收盘的 `compute_forward_returns`），算 factor 对该 h 日 forward 的 ICIR。真 edge 缓慢衰减；自相关 1 日强后快速塌。
- **滞后基线**：把因子替换成"前一日隔夜收益"（`fr.shift(1)` 按 symbol），forward return 不变（1 日隔夜），算 IC。这是 IC 的"自相关地板"——若因子 IC ≈ 滞后基线 IC → IC 多半是自相关。
- **换手率代理**：因子逐日横截面排名变动比例 = `rank(t) != rank(t-1)` 的 symbol 占比均值。自相关信号换手率极低。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py::test_autocorrelation_probe_returns_three_signals -v`
Expected: FAIL（`NameError: autocorrelation_probe`）

- [ ] **Step 3: 实现自相关探针**

```python
# scripts/diagnose_tail_factors_walkforward.py 追加
def _overnight_forward_return_horizon(bars: pd.DataFrame, h: int) -> pd.DataFrame:
    """h 日隔夜 forward return: open(t+h)/close(t) - 1。"""
    bars = bars.sort_index()
    close = bars["close"].unstack(level="symbol")
    open_ = bars["open"].unstack(level="symbol").shift(-h)
    ret = (open_ / close - 1.0)
    return (
        ret.stack(future_stack=True)
        .to_frame(name="return")
        .rename_axis(["date", "symbol"])["return"]
        .to_frame()
    )


def autocorrelation_probe(bars, factor, horizons=(1, 2, 3, 5)) -> dict:
    """自相关三项：多日衰减 ICIR + 滞后基线相关 + 换手率代理。"""
    fr1 = compute_overnight_forward_return(bars)  # horizon=1
    fv = factor.compute(bars)

    # 1) 衰减：各 horizon 的 ICIR
    decay = {}
    for h in horizons:
        fr_h = _overnight_forward_return_horizon(bars, h)
        ic = ICAnalyzer(forward_period=h)
        ic_series = ic.compute_ic(fv, fr_h)
        rank_ic = ic.compute_rank_ic(fv, fr_h)
        summary = ic.ic_summary(ic_series, rank_ic)
        decay[h] = summary.icir

    # 2) 滞后基线：因子替换成前一日隔夜收益（按 symbol shift），forward return 不变（1 日）
    fr_lagged = fr1.groupby(level="symbol")["return"].shift(1).to_frame()
    # 对齐 fv 的索引
    aligned = fv.join(fr_lagged.rename(columns={"return": "lagged_ret"}), how="inner")
    dates = aligned.index.get_level_values("date").unique()
    corrs = []
    for d in dates:
        try:
            fv_d = aligned.loc[d].iloc[:, 0]
            lag_d = aligned.loc[d]["lagged_ret"]
        except (KeyError, IndexError):
            continue
        valid = ~(fv_d.isna() | lag_d.isna())
        if valid.sum() < 3:
            continue
        corrs.append(float(fv_d[valid].corr(lag_d[valid])))
    lagged_corr = float(pd.Series(corrs).mean()) if corrs else None

    # 3) 换手率代理：因子逐日横截面排名变动比例
    ranks = fv.groupby(level="date").rank(pct=True)
    rank_series = ranks.iloc[:, 0]
    by_date = rank_series.groupby(level="date")
    turnover_days = []
    prev = None
    for d, grp in by_date:
        if prev is not None:
            common = grp.index.intersection(prev.index)
            if len(common) > 0:
                changed = (grp.loc[common] != prev.loc[common]).sum()
                turnover_days.append(float(changed) / len(common))
        prev = grp
    turnover = float(pd.Series(turnover_days).mean()) if turnover_days else None

    return {
        "factor": factor.name,
        "decay_icir_by_horizon": {int(h): v for h, v in decay.items()},
        "lagged_baseline_corr": lagged_corr,
        "turnover_proxy": turnover,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors_walkforward.py tests/test_research/test_diagnose_tail_factors_walkforward.py
git commit -m "feat: add autocorrelation probe (decay + lagged baseline + turnover) for tail factors"
```

---

### Task 4: 扣成本净 edge（对应折扣③未扣成本）—— 口径 A 单边 + 口径 B 价差

**Files:**
- Modify: `scripts/diagnose_tail_factors_walkforward.py`
- Test: `tests/test_research/test_diagnose_tail_factors_walkforward.py`

**Interfaces:**
- Consumes: `FeeCalculator.from_settings()`（`src/core/broker_base.py:93`）→ `.calc_commission(amount, side)`（`side="buy"`/`"sell"`，含佣金+印花税+过户费+证管费）。`QuantileAnalyzer.analyze` 的 `quantile_returns`（每日各分位组平均收益）。
- Produces: `net_edge(bars, factor, trade_capital=100000, top_n=5, n_quantiles=5) -> dict`，返回 `{"factor", "gross_top_quantile_return": float, "gross_spread": float, "cost_buy_rate": float, "cost_roundtrip_rate": float, "net_long_only": float, "net_long_short": float}`。`net_long_only` = top 分位平均收益 − 买入成本率（口径 A）；`net_long_short` = top−bottom 价差 − 往返成本率（口径 B）。

**Background:** 成本是金额→费率依赖。用典型交易额建模：单笔金额 = `trade_capital / top_n`（如 10 万 / 5 = 2 万/笔），使 `min_commission=5` 真实生效。成本率 = `calc_commission(amount, side) / amount`。买入成本率 = buy 端费率（无印花税）；往返成本率 = buy + sell 端费率。收益率为日度平均（未年化，与 horizon=1 一致）。

- [ ] **Step 1: 写失败测试**

```python
def test_net_edge_subtracts_real_costs_both_calibers():
    bars = _fake_bars_long()
    result = net_edge(bars, OvernightMomentumFactor(smoothing_window=1), trade_capital=100000, top_n=5, n_quantiles=3)
    assert result["factor"] == "overnight_momentum"
    # 真实费率：买入 ≈ 0.00025+0.00001+0.0000487 ≈ 0.000309（2万/笔 > min_commission 5）
    assert result["cost_buy_rate"] > 0
    assert result["cost_roundtrip_rate"] > result["cost_buy_rate"]  # 往返含卖出印花税
    # 净 edge = 毛 - 成本
    assert abs(result["net_long_only"] - (result["gross_top_quantile_return"] - result["cost_buy_rate"])) < 1e-9
    assert abs(result["net_long_short"] - (result["gross_spread"] - result["cost_roundtrip_rate"])) < 1e-9


def test_cost_rate_from_fee_calculator_matches_settings():
    """成本率来源 FeeCalculator.from_settings()，非手写魔数。"""
    from src.core.broker_base import FeeCalculator
    fees = FeeCalculator.from_settings()
    amount = 20000  # 10万/5
    buy_rate = fees.calc_commission(amount, "buy") / amount
    sell_rate = fees.calc_commission(amount, "sell") / amount
    bars = _fake_bars_long()
    result = net_edge(bars, OvernightMomentumFactor(smoothing_window=1), trade_capital=100000, top_n=5, n_quantiles=3)
    assert abs(result["cost_buy_rate"] - buy_rate) < 1e-9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py::test_net_edge_subtracts_real_costs_both_calibers -v`
Expected: FAIL（`NameError: net_edge`）

- [ ] **Step 3: 实现净 edge**

```python
# scripts/diagnose_tail_factors_walkforward.py 追加
from src.core.broker_base import FeeCalculator


def net_edge(bars, factor, trade_capital=100000, top_n=5, n_quantiles=5) -> dict:
    """扣成本净 edge：口径 A 做多单边 + 口径 B 多空价差。"""
    fr = compute_overnight_forward_return(bars)
    fv = factor.compute(bars)
    qa = QuantileAnalyzer(n_quantiles=n_quantiles)
    qresult = qa.analyze(fv, fr)

    # 分位组日度平均收益
    qr = qresult.quantile_returns
    top_col = qr.columns[-1]
    bottom_col = qr.columns[0]
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
        "trade_amount_per_leg": amount,
        "cost_buy_rate": float(cost_buy_rate),
        "cost_sell_rate": float(cost_sell_rate),
        "cost_roundtrip_rate": float(cost_roundtrip_rate),
        "net_long_only": float(gross_top - cost_buy_rate),       # 口径 A
        "net_long_short": float(gross_spread - cost_roundtrip_rate),  # 口径 B
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors_walkforward.py tests/test_research/test_diagnose_tail_factors_walkforward.py
git commit -m "feat: add cost-adjusted net edge (long-only + long-short) using FeeCalculator"
```

---

### Task 5: main() 串联 + JSON 输出

**Files:**
- Modify: `scripts/diagnose_tail_factors_walkforward.py`
- Test: `tests/test_research/test_diagnose_tail_factors_walkforward.py`

**Interfaces:**
- Consumes: Task 1-4 的 `walk_forward_stability` / `autocorrelation_probe` / `net_edge`；`scripts/diagnose_tail_factors._load_bars`（复用数据加载分支）+ `_sanitize_for_json`。
- Produces: `run_walkforward(bars, train_days, step_days, horizons, trade_capital, top_n, n_quantiles) -> dict`（串联三块，两因子）；`main()` CLI 输出 JSON。

- [ ] **Step 1: 写失败测试**

```python
def test_run_walkforward_combines_stability_autocorr_edge():
    bars = _fake_bars_long()
    result = run_walkforward(bars, train_days=60, step_days=10, horizons=[1, 2], trade_capital=100000, top_n=5, n_quantiles=3)
    assert set(r["factor"] for r in result["factors"]) == {"tail_session", "overnight_momentum"}
    for f in result["factors"]:
        assert "walk_forward" in f and "autocorrelation" in f and "net_edge" in f
        assert f["walk_forward"]["fold_count"] > 0


def test_main_writes_strict_valid_json(tmp_path, monkeypatch):
    bars = _fake_bars_long()
    out = tmp_path / "wf.json"
    # 桩 _load_bars 返回 fake bars，避免读 cache/网络
    import scripts.diagnose_tail_factors_walkforward as mod
    monkeypatch.setattr(mod, "_load_bars", lambda args: bars, raising=False)
    monkeypatch.setattr("sys.argv", ["x", "--offline-cache", "--out", str(out), "--train-days", "60", "--step-days", "20"])
    mod.main()
    import json as _json
    payload = _json.loads(out.read_text())  # strict parse
    assert "factors" in payload
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py::test_run_walkforward_combines_stability_autocorr_edge -v`
Expected: FAIL（`NameError: run_walkforward`）

- [ ] **Step 3: 实现 run_walkforward + main**

```python
# scripts/diagnose_tail_factors_walkforward.py 追加
from scripts.diagnose_tail_factors import _load_bars


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
```

- [ ] **Step 4: 跑测试确认通过 + 小窗冒烟**

Run: `pytest tests/test_research/test_diagnose_tail_factors_walkforward.py -v`
Expected: PASS

冒烟：`python scripts/diagnose_tail_factors_walkforward.py --offline-cache --start 2026-05-01 --end 2026-06-10 --train-days 20 --step-days 5 --out /tmp/wf_smoke.json`
Expected: 产出 JSON，两因子各有 walk_forward/autocorrelation/net_edge，无异常。

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors_walkforward.py tests/test_research/test_diagnose_tail_factors_walkforward.py
git commit -m "feat: wire main() and JSON output for walk-forward factor diagnosis"
```

---

### Task 6: 全窗实跑 + 动态结论报告

**Files:**
- Create: `docs/superpowers/reviews/2026-06-29-tail-factor-walkforward-report.md`

**Interfaces:**
- Consumes: Task 5 产出的 `reports/tail_session/factor_diagnosis_walkforward.json`。
- Produces: 动态结论报告，逐条标注三折扣【已推翻 / 坐实 / 部分成立】。

- [ ] **Step 1: 全窗实跑**

Run: `python scripts/diagnose_tail_factors_walkforward.py --offline-cache --start 2025-01-01 --end 2026-06-01 --out reports/tail_session/factor_diagnosis_walkforward.json`
Expected: 产出全窗 JSON（~28 折）。

- [ ] **Step 2: 撰写报告（动态结论）**

报告结构（据实跑结果填）：
1. **walk-forward 稳定性**：overnight 每折 ICIR 表 + 跨折汇总（均值/std/正折占比/最差折）。判定【折扣① 已推翻 / 坐实 / 部分成立】。
2. **自相关探针**：衰减 ICIR by horizon（1/2/3/5）；滞后基线相关 vs 因子 ICIR；换手率代理。判定【折扣②】。
3. **净 edge**：口径 A 单边 + 口径 B 价差，扣成本后是否为正。判定【折扣③】。
4. **综合判定**：三折扣逐条结论。
5. 若坐实自相关 → 一句话指针到 S01 缺失因子（涨停基因/换手率/板块龙头），不展开。
6. 复现命令 + 成本参数来源（FeeCalculator.from_settings，非魔数）+ JSON 在 `reports/` 为本地生成物（gitignore）。

报告必须诚实标注限制（数据窗 ~339 天、换手率是代理非真实换手、净 edge 是因子层面非真实策略收益）。

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/reviews/2026-06-29-tail-factor-walkforward-report.md
git commit -m "docs: add tail factor walk-forward validation report"
```

---

## Verification（端到端）

- **折迭代/单折 IC（Task 1）**：`pytest tests/test_research/test_diagnose_tail_factors_walkforward.py`。
- **稳定性/自相关/净 edge（Task 2-4）**：同上，各函数单测全绿。
- **main 串联（Task 5）**：单测 + 小窗冒烟。
- **报告（Task 6）**：全窗实跑 → 三折扣逐条判定。

## Self-Review（spec 覆盖核对）

- 折扣①样本内 → Task 1-2 walk_forward_stability ✅
- 折扣②自相关 → Task 3 autocorrelation_probe（衰减+滞后基线+换手率代理）✅
- 折扣③未扣成本 → Task 4 net_edge（口径 A+B，FeeCalculator 真实费率）✅
- 动态结论报告 → Task 6 ✅
- 复用约束（不改生产代码、隔夜 forward return、NaN→null）→ 各 Task 显式 import ✅
- 类型一致：`walk_forward_folds` / `diagnose_fold` / `walk_forward_stability` / `autocorrelation_probe` / `net_edge` / `run_walkforward` 各 Task 定义、后续复用签名一致 ✅
