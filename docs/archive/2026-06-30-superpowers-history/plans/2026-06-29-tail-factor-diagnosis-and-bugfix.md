# 尾盘因子诊断与 min_score 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给尾盘选股系统 A（日频因子研究/回测路径）补「看·疑」环节——先看清现有因子（tail_session + overnight_momentum）到底有没有预测力，再修掉让隔夜权重静默失效的 `min_score` bug，让后续调参脱离黑箱。

**Architecture:** 不碰网格/web。新建一个独立诊断脚本，复用现成但未接入的 `ICAnalyzer`/`QuantileAnalyzer`，对每个尾盘因子算 IC/RankIC/ICIR/分层/单调性；forward return 自定义为隔夜单日收益（匹配 S01 一夜持股法的持仓周期），不用工具默认的收盘-收盘。再以 per-factor 字典方式修 `min_score` 逐因子过滤 bug，并同步 web 后端重复逻辑。数据雷现状已确认（daily 重复 6-23 已清零、invalid OHLC 仅剩 1,203 行在 2020-2022、跑批窗 2025-2026 不撞），本计划只补一道未来脏读防线。

**Tech Stack:** Python，pandas，ClickHouse/parquet（只读），pytest，ICAnalyzer/QuantileAnalyzer（`src/research/factor_analysis/`）。

---

## Global Constraints

- **复用优先**：IC/RankIC/ICIR/分层/单调性一律用现成 `ICAnalyzer`（`src/research/factor_analysis/ic_analysis.py:47`）、`QuantileAnalyzer`（`quantile.py:38`），不重写诊断逻辑。
- **诊断与 bug 解耦**：诊断脚本读因子原始值、不过 `scoring.py`，所以可独立于 Task 2 先行。
- **forward return 必须匹配 S01 持仓周期**：尾盘买 close(t)、次日开盘 open(t+1) 卖 → forward return = `open(t+1)/close(t) - 1`。**禁止**用 `ICAnalyzer.compute_forward_returns` 默认的收盘-收盘，否则度量与策略实际赚的钱不对应。
- **不碰网格/web 现有行为**：本计划不改 `evaluate_tail_session_grid.py` 网格、不改 `tail_live.py` 实盘路径（web 后端 `backtests.py` 仅同步 min_score 重复逻辑以保持显示一致）。
- **动态结论**：诊断报告不预设因子有效/无效，跑出什么写什么（XQuant Spec 写作法「疑」）。
- **数据时点**：本计划基于 2026-06-24 ClickHouse snapshot；daily 重复已于 6-23 清零（`2026-06-23-data-quality-hardening.md` Task 2 记录），invalid OHLC 仅剩 1,203 行跨 14 个 symbol（2020-01-02 ~ 2022-04-27）。

---

## File Structure

- `scripts/diagnose_tail_factors.py`（新建）：独立诊断 CLI，加载 bars → 算各因子原始值 → 构造隔夜 forward return → 调 IC/Quantile → 输出报告。
- `tests/test_research/test_diagnose_tail_factors.py`（新建）：诊断逻辑单测（fake bars，断言 forward return 构造、IC 调用、报告字段）。
- `src/strategy/scoring.py`（改）：`min_score` 支持 per-factor 字典，只门控指定因子。
- `src/web/backend/backtests.py:600-601`（改）：同步 per-factor 查找，保持 UI 贡献度显示一致。
- `scripts/run_tail_session_backtest.py`、`scripts/evaluate_tail_session_grid.py`（改）：迁移调用点传 `{"tail_session": <score>}`。
- `tests/test_strategy/test_scoring.py`、`tests/test_strategy/test_strategy_module.py`、`tests/test_research/test_tail_session_analysis.py`（改）：更新固定语义。
- `src/data/clickhouse_research_dataset.py:107`（改）：loader 补 `close>0` 过滤，堵未来脏读。
- `docs/superpowers/reviews/2026-06-29-tail-factor-diagnosis-report.md`（新建）：诊断结论报告（动态结论）。

---

### Task 1: 堵 clickhouse_research_dataset 脏读防线（疑·排雷）

**Files:**
- Modify: `src/data/clickhouse_research_dataset.py:107`
- Test: `tests/test_data/test_clickhouse_research_dataset.py`（若无则建）

**Interfaces:**
- Consumes: `load_clickhouse_research_dataset` 现有返回 DataFrame（`date,symbol` MultiIndex + OHLCV）。
- Produces: 同签名，但 loader 内部在 `drop_duplicates` 后增加 `close>0` 过滤，保证 000937 等负价行不进 parquet。

**Background:** 该 loader（`clickhouse_research_dataset.py:86-88` 直读 `daily_kline`，`:107` 仅 `drop_duplicates(["date","symbol"])`）不过滤负价。当前 `data/research/` 空、跑批走 cache 不撞雷，但将来若有人用它从 CH 重建 2020-2021 数据集，000937 的 1,203 行 invalid OHLC 会原样进 parquet。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_data/test_clickhouse_research_dataset.py
def test_loader_drops_invalid_close_rows(monkeypatch):
    fake_rows = [
        ("2021-03-26", "000937.SZ", -0.21, -0.23, -0.20, -0.21, 1000.0),  # 负价脏行
        ("2021-03-29", "000937.SZ", 10.0, 10.2, 9.8, 10.1, 2000.0),        # 正常
        ("2021-03-29", "600519.SH", 1800.0, 1810.0, 1790.0, 1805.0, 500.0),
    ]
    monkeypatch.setattr(..., lambda **kw: fake_rows)  # 桩 ClickHouse 查询
    df = load_clickhouse_research_dataset(...)
    assert (df["close"] <= 0).sum() == 0
    assert len(df) == 2  # 负价行被滤除
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_data/test_clickhouse_research_dataset.py::test_loader_drops_invalid_close_rows -v`
Expected: FAIL（当前 loader 不过滤，断言 `(close<=0).sum()==0` 不成立）

- [ ] **Step 3: 实现过滤**

在 `src/data/clickhouse_research_dataset.py:107` 的 `drop_duplicates` 后追加：

```python
df = df.drop_duplicates(["date", "symbol"])
# 防御历史 invalid OHLC（如 000937 2020-2021 负价），避免进回测/训练 parquet
df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_data/test_clickhouse_research_dataset.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/data/clickhouse_research_dataset.py tests/test_data/test_clickhouse_research_dataset.py
git commit -m "fix: filter invalid OHLC in clickhouse research dataset loader"
```

---

### Task 2: 诊断脚本——隔夜 forward return 构造（看·诊断核心）

**Files:**
- Create: `scripts/diagnose_tail_factors.py`
- Test: `tests/test_research/test_diagnose_tail_factors.py`

**Interfaces:**
- Consumes: `TailSessionFactor`（`src/strategy/factors/tail_session.py:21`，4 档离散 0/0.4/0.7/1.0）、`OvernightMomentumFactor`（`overnight_momentum.py:18`，连续值）、`ICAnalyzer.compute_ic/compute_rank_ic/ic_summary`（`ic_analysis.py:53,92,140`）、`QuantileAnalyzer.analyze`（`quantile.py:44`，返回 `QuantileResult` 含 `.spread`/`.monotonicity`/`.summary`）。
- Produces: `compute_overnight_forward_return(bars) -> pd.DataFrame`（MultiIndex date,symbol 单列 `"return"` = `open(t+1)/close(t) - 1`），`diagnose_factor(bars, factor, forward_returns) -> dict`，`run_diagnosis(bars, ...) -> dict`。这些函数被 Task 3 复用产出报告。

**Background:** `ICAnalyzer.compute_forward_returns`（`ic_analysis.py:121`）算的是收盘-收盘 `pct_change(p).shift(-p)`，与 S01 隔夜持仓不匹配。必须自定义 forward return。bars 索引为 MultiIndex `(date, symbol)`（顺序见 `tail_session.py:57`，需 `symbol`/`date` 命名层级）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_research/test_diagnose_tail_factors.py
import pandas as pd
from scripts.diagnose_tail_factors import compute_overnight_forward_return

def _fake_bars():
    idx = pd.MultiIndex.from_tuples(
        [("2025-01-01", "000001.SZ"), ("2025-01-02", "000001.SZ"),
         ("2025-01-01", "600519.SH"), ("2025-01-02", "600519.SH")],
        names=["date", "symbol"],
    )
    return pd.DataFrame(
        {"open": [9.0, 9.9, 100.0, 102.0], "close": [10.0, 10.0, 100.0, 101.0],
         "high": [10.5, 10.5, 101.0, 103.0], "low": [8.5, 9.5, 99.0, 100.5],
         "volume": [1000, 1100, 500, 520]}, index=idx)

def test_overnight_forward_return_uses_next_open_over_close():
    bars = _fake_bars()
    fr = compute_overnight_forward_return(bars)
    # 000001: open(01-02)/close(01-01) - 1 = 9.9/10.0 - 1 = -0.01
    val = fr.loc[("2025-01-01", "000001.SZ"), "return"]
    assert round(float(val), 4) == -0.01
    # 最后一日无次日 open -> NaN
    assert pd.isna(fr.loc[("2025-01-02", "000001.SZ"), "return"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors.py::test_overnight_forward_return_uses_next_open_over_close -v`
Expected: FAIL（`ModuleNotFoundError: scripts.diagnose_tail_factors`）

- [ ] **Step 3: 实现 forward return 构造 + 诊断函数骨架**

```python
# scripts/diagnose_tail_factors.py
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_research/test_diagnose_tail_factors.py::test_overnight_forward_return_uses_next_open_over_close -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors.py tests/test_research/test_diagnose_tail_factors.py
git commit -m "feat: add overnight forward return for tail factor diagnosis"
```

---

### Task 3: 诊断脚本——数据加载与报告输出

**Files:**
- Modify: `scripts/diagnose_tail_factors.py`
- Test: `tests/test_research/test_diagnose_tail_factors.py`（追加）

**Interfaces:**
- Consumes: `load_research_dataset`（`src/data/research_dataset.py:83`，读 parquet）或 `load_bars_from_offline_cache`（`data/cache/bars/`）；Task 2 的 `run_diagnosis`/`compute_overnight_forward_return`。
- Produces: `main()` 完整 CLI，输出 `reports/tail_session/factor_diagnosis.json`（含每因子的 IC/RankIC/ICIR/ic_positive_ratio/spread/monotonicity）。

**Background:** 复用 `run_tail_session_backtest.py:100-110` 的数据加载分支（`--bars-dataset` / `--offline-cache`）。

- [ ] **Step 1: 写失败测试（run_diagnosis 端到端，fake bars）**

```python
def test_run_diagnosis_returns_ic_and_quantile_per_factor():
    bars = _fake_bars_more()  # ≥5 symbols × ≥5 days，保证 qcut 与 IC 有有效观测
    result = run_diagnosis(bars, n_quantiles=3)
    assert result["forward_return"] == "overnight_open/close-1"
    names = {f["factor"] for f in result["factors"]}
    assert names == {"tail_session", "overnight_momentum"}
    for f in result["factors"]:
        assert "ic_mean" in f["ic"] and "rank_icir" in f["ic"]
        assert "spread_return" in f["quantile"] and "monotonicity" in f["quantile"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_research/test_diagnose_tail_factors.py::test_run_diagnosis_returns_ic_and_quantile_per_factor -v`
Expected: FAIL（`_fake_bars_more` 未定义 或 run_diagnosis 链路缺数据加载）

- [ ] **Step 3: 实现 main() 数据加载 + JSON 输出**

```python
# scripts/diagnose_tail_factors.py — 替换 main()
def _load_bars(args):
    if args.bars_dataset:
        from src.data.research_dataset import load_research_dataset
        return load_research_dataset(args.bars_dataset)
    if args.offline_cache:
        from src.data.bar_repository import load_bars_from_offline_cache
        return load_bars_from_offline_cache()
    from src.data.aggregator import DataAggregator
    from datetime import date
    agg = DataAggregator()
    return agg.get_bars_batch(_default_symbols(), date.fromisoformat(args.start), date.fromisoformat(args.end))

def main():
    parser = argparse.ArgumentParser(description="Diagnose tail-session factors (IC/quantile).")
    parser.add_argument("--bars-dataset")
    parser.add_argument("--offline-cache", action="store_true")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-06-01")
    parser.add_argument("--n-quantiles", type=int, default=5)
    parser.add_argument("--out", default="reports/tail_session/factor_diagnosis.json")
    args = parser.parse_args()

    bars = _load_bars(args)
    result = run_diagnosis(bars, n_quantiles=args.n_quantiles)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
```

（`_default_symbols()` 复用 `test_phase3.py:26` 的样本符号列表即可。）

- [ ] **Step 4: 跑测试确认通过 + 小窗实跑冒烟**

Run: `pytest tests/test_research/test_diagnose_tail_factors.py -v`
Expected: PASS

实跑冒烟（小窗、若有 cache）：`python scripts/diagnose_tail_factors.py --offline-cache --start 2026-05-01 --end 2026-06-10 --out /tmp/factor_diagnosis_smoke.json`
Expected: 产出 JSON，含两个因子的 IC/quantile 字段，无异常。

- [ ] **Step 5: 提交**

```bash
git add scripts/diagnose_tail_factors.py tests/test_research/test_diagnose_tail_factors.py
git commit -m "feat: wire data loading and report output for tail factor diagnosis"
```

---

### Task 4: 撰写因子诊断报告（动态结论）

**Files:**
- Create: `docs/superpowers/reviews/2026-06-29-tail-factor-diagnosis-report.md`

**Interfaces:**
- Consumes: Task 3 产出的 `reports/tail_session/factor_diagnosis.json`。
- Produces: 诊断结论报告。

- [ ] **Step 1: 实跑诊断（全窗）**

Run: `python scripts/diagnose_tail_factors.py --offline-cache --start 2025-01-01 --end 2026-06-01 --out reports/tail_session/factor_diagnosis.json`
Expected: 产出全窗 JSON。

- [ ] **Step 2: 撰写报告（动态结论，不预设方向）**

报告模板要点（据实跑结果填）：
- 每因子：IC_mean / RankIC_mean / ICIR / IC_positive_ratio / spread_return / monotonicity
- 判读规则（写在报告里，结论据数填）：
  - `|ICIR| >= 0.3 且 IC_positive_ratio 显著偏离 0.5` → 有方向性预测力
  - `monotonicity > 0.5` → 分层单调
  - 否则标注「预测力不足」
- 对照 S01 标注缺失因子：涨停基因 / 换手率 / 板块龙头 / 分时形态（仅标注，不补）
- 不提供换手率指标（工具缺口），列为后续可选
- 末尾给 min_score 修复的优先级依据：若 overnight 有预测力 → Task 5 优先级高；若无 → 修复价值低但仍做（保持权重语义正确）

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/reviews/2026-06-29-tail-factor-diagnosis-report.md reports/tail_session/factor_diagnosis.json
git commit -m "docs: add tail factor diagnosis report"
```

---

### Task 5: 修 min_score 逐因子过滤 bug（做·修 bug）

**Files:**
- Modify: `src/strategy/scoring.py:34,52-53`
- Modify: `src/web/backend/backtests.py:600-601`
- Test: `tests/test_strategy/test_scoring.py:59`

**Interfaces:**
- Consumes: `Factor.name`（每个因子有 `name` 属性，如 `"tail_session"`/`"overnight_momentum"`）。
- Produces: `FactorScoreEngine(min_score: float | dict[str,float] | None)`；`dict` 时仅门控命中的因子，未列出的因子（隔夜）不过滤，0.3 权重保留。

**Background:** `scoring.py:52-53` `values = values.where(values >= self.min_score)` 逐因子原始值过滤；隔夜是连续 ≈0，任何 `min_score>0` 整列 NaN → rank NaN → `composite.add(fill_value=0)` 填回 0 → 0.3 权重失效。`backtests.py:600-601` 有相同重复逻辑，需同步否则 UI 贡献度显示不一致。现有测试 `test_scoring.py:59`（`test_factor_score_engine_applies_min_raw_score_before_ranking`）、`test_strategy_module.py:523`（`test_min_score_blocks_weak_signals`）、`test_tail_session_analysis.py:47` 固化「原始值过滤」语义——需更新保留「高 min_score 阻断弱 tail 信号」契约、同时不再误杀隔夜。

- [ ] **Step 1: 写失败测试（per-factor 字典不误杀隔夜）**

```python
# tests/test_strategy/test_scoring.py — 追加
def test_min_score_dict_only_gates_named_factor_not_overnight():
    # tail_session 离散 0/0.4/0.7/1.0；overnight 连续小数
    bars = _make_bars_with_tail_and_overnight()
    engine = FactorScoreEngine(
        factors=[TailSessionFactor(), OvernightMomentumFactor()],
        factor_weights=[0.7, 0.3],
        min_score={"tail_session": 0.7},   # 只门控 tail，隔夜不过滤
    )
    composite = engine.compute_scores(bars)
    # 隔夜权重 0.3 仍生效：composite 不应退化为纯 tail_rank
    overnight_contrib = ...  # 断言隔夜有非零贡献
    assert overnight_contrib != 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_strategy/test_scoring.py::test_min_score_dict_only_gates_named_factor_not_overnight -v`
Expected: FAIL（当前 `min_score` 只接受 float，dict 会被当成标量比较）

- [ ] **Step 3: 实现 per-factor 字典过滤**

```python
# src/strategy/scoring.py
def __init__(self, factors, factor_weights=None, top_n=10, min_score: float | dict[str, float] | None = None):
    ...
    self.min_score = min_score

def compute_scores(self, bars):
    ...
    for factor, weight in zip(self.factors, self.factor_weights):
        try:
            values = factor.compute(bars)
            if values.empty:
                continue
            threshold = (
                self.min_score.get(factor.name)
                if isinstance(self.min_score, dict)
                else self.min_score
            )
            if threshold is not None:
                values = values.where(values >= threshold)
            ranked = values.groupby(level=0).rank(pct=True)
            scores.append(ranked * weight)
        ...
```

同步 `src/web/backend/backtests.py:600-601` 用相同 `isinstance(self.min_score, dict)` 查找逻辑。

- [ ] **Step 4: 更新现有测试 + 跑全部相关测试**

更新 `test_scoring.py:59`、`test_strategy_module.py:523`、`test_tail_session_analysis.py:47`：保留「高 min_score 阻断弱 tail 信号」断言（用 `{"tail_session": 1.1}` 替代标量 `1.1`），新增「dict 不误杀隔夜」。

Run: `pytest tests/test_strategy/test_scoring.py tests/test_strategy/test_strategy_module.py tests/test_research/test_tail_session_analysis.py -q`
Expected: PASS

- [ ] **Step 5: 迁移调用点**

`scripts/run_tail_session_backtest.py`、`scripts/evaluate_tail_session_grid.py`、`src/web/backend/backtests.py`：把传给 `min_score` 的 float 改为 `{"tail_session": <score>}`（隔夜不列）。CLI `--min-score` 仍接受 float，内部转成 `{"tail_session": <value>}`。

- [ ] **Step 6: 提交**

```bash
git add src/strategy/scoring.py src/web/backend/backtests.py scripts/run_tail_session_backtest.py scripts/evaluate_tail_session_grid.py tests/
git commit -m "fix: gate min_score per-factor to preserve overnight momentum weight"
```

---

### Task 6: 复跑验证 bug 修复生效

**Files:**
- 无新建，复跑现有脚本。

- [ ] **Step 1: 复跑历史选股报告**

Run: `python scripts/run_tail_session_backtest.py --min-score 0.7 --offline-cache --start 2026-05-12 --end 2026-06-10`（参数据实调整，需有 cache）
Expected: `selection_count > 0`（之前 `historical_daily_selections_20260512_20260610.json` 是 0/全空），且入选票分数不再全是退化值 `0.42`（隔夜权重生效带来区分度）。

- [ ] **Step 2: 跑全量回归测试**

Run: `pytest tests/test_strategy tests/test_research tests/test_data/test_clickhouse_research_dataset.py -q`
Expected: PASS

- [ ] **Step 3: 提交验证记录（可选，写入 Task 4 报告附录）**

在 `docs/superpowers/reviews/2026-06-29-tail-factor-diagnosis-report.md` 附录记录复跑前后 `selection_count` 与代表性分数对比。

---

## Verification（端到端）

- **排雷（Task 1）**：`pytest tests/test_data/test_clickhouse_research_dataset.py`；用含负价的样本验证被滤除。
- **诊断（Task 2-3）**：`pytest tests/test_research/test_diagnose_tail_factors.py`；小窗实跑冒烟产出 JSON。
- **报告（Task 4）**：全窗实跑 → 报告动态结论。
- **修 bug（Task 5-6）**：`pytest tests/test_strategy tests/test_research`；复跑 `run_tail_session_backtest.py --min-score 0.7` 确认 `selection_count>0`、分数有区分度。

## Self-Review（spec 覆盖核对）

- 数据雷防线（R3 clickhouse_research_dataset 脏读）→ Task 1 ✅
- 因子诊断层（IC/RankIC/ICIR/分层/单调性，forward return 匹配 S01 隔夜）→ Task 2-3 ✅
- 对照 S01 查缺 → Task 4 报告 ✅
- min_score bug（含 backtests.py 重复逻辑、调用点迁移、测试更新）→ Task 5 ✅
- 复跑验证空报告修复 → Task 6 ✅
- 类型一致：`compute_overnight_forward_return` / `diagnose_factor` / `run_diagnosis` 在 Task 2 定义、Task 3 复用，签名一致 ✅

## 待用户拍板（执行前确认）

1. **数据加载源**：诊断脚本默认走 `--offline-cache`（`data/cache/bars/`），还是指定 `--bars-dataset` parquet？（cache 在 2025-2026 有数据）
2. **min_score 修法**：本计划用 (b) per-factor 字典。是否改用 (a) composite 级过滤（改动更小，但语义从「原始因子门控」偏移为「组合分门控」）？
3. **是否顺带度量多日衰减**：当前 forward return 只算隔夜单日。是否额外算 2/3/5 日衰减？（列为后续可选，默认不做）
