# 2026-06-29 尾盘选股系统当前状态分析

> **范围**：盘点"尾盘选股"四条链路的现状与已知问题，作为后续优化的认知基线。
> **方法**：读 README/ARCHITECTURE + 3 个并行 Explore agent（分别扫研究/回测路径、实盘分钟路径、ML 管线）+ 亲自读关键源码与磁盘实证产物复核。除特别标注外，结论已对到 file:line。
> **状态**：纯分析，未改代码。本文记录的是"当前理解"，不是设计 spec——优化方向尚未最终确定。
> **前序**：`docs/superpowers/reviews/2026-06-25-data-and-code-review.md`、`docs/superpowers/plans/2026-06-24-tail-ml-strategy-optimization.md`。

---

## 0. 一句话结论

"尾盘选股"在代码里其实是**四套半独立、基本不互通的系统**。其中"日频因子研究/回测路径"是本次优化的焦点，它当前**策略在亏钱、选股报告曾出现全空、且从未度量过因子是否真的有预测力**——也就是说，目前任何调参都在黑箱里进行。

---

## 1. 系统全景：四套选股器

| 系统 | 入口 | 数据 | 用途 | 与其他系统的关系 |
|---|---|---|---|---|
| **A. 日频因子研究/回测** | `scripts/run_tail_session_backtest.py`、`scripts/evaluate_tail_session_grid.py` | 日频 bars（parquet/ClickHouse） | 离线研究、参数网格、历史选股报告 | **与实盘/ML 完全脱节**，结论不喂回 |
| **B. 实盘分钟级选股** | `src/web/backend/tail_live.py`（web）/ `scripts/run_tail_session_live.py`（CLI） | 14:30–15:00 5 分钟 bars | 每天盘中实际选股 | web 用 v2 打分 + 可选 ML；CLI 用老排序、无 v2 无 ML（**两套行为**） |
| **C. ML 增强层** | `src/ml/*` + `tail_live._apply_model_*` + `app.py` 历史校准 | 日频 + minute5（ClickHouse） | 在 B 之上叠加模型打分/重排 | 依赖 B 的候选池；与 A 的因子互不引用 |
| **D. 基金尾盘** | `src/research/fund_tail_backtest.py` + `data/fund_tail/*.csv` | 基金代理数据 | 基金加仓决策（规则 + 条件统计预测） | 独立子系统，与股票尾盘不共享代码 |

ARCHITECTURE.md:110-127 明确要求 A 与 B **保持分开**（"不要假设它们是完全等价的信号"），这是有意的设计边界——但代价是三套选股器没有共享记分牌，研究结论无法回流。

本次优化聚焦 **系统 A**（研究/回测路径）。

---

## 2. 系统 A：日频因子研究/回测路径（焦点）

### 2.1 TailSessionFactor —— 4 档离散信号

`src/strategy/factors/tail_session.py`。输出是 **离散 4 档**，非连续：

| 档位 | 条件（均需过 quality 门） | 位置 |
|---|---|---|
| 0.0 | 无突破 | `tail_session.py:95` |
| 0.4 | breakout & quality | `:96` |
| 0.7 | breakout & trend & quality | `:97` |
| 1.0 | breakout & trend & volume & quality | `:98` |

- **breakout**：`close > close.shift(1).rolling(breakout_window).max()`（默认 20 日）
- **trend**：`trend_window`（默认 5 日）OLS 斜率 > 0
- **volume**：`volume > rolling(20).mean().shift(1) * volume_ratio_threshold`（默认 1.2）。注意 **volume MA 窗口硬编码 20**，未参数化。
- **quality 门**（`:80-93`）：`min_close_above_ma20`、`max_daily_return`、`min_turnover_value`、`min_market_breadth_above_ma20`。

**粗糙度**：4 档之内无量级区分——5% 突破 + 3 倍量 与 0.01% 突破 + 1.21 倍量 在 1.0 档得分完全相同。下游所有区分度都来自对这一粗标量排名 + 隔夜因子。且这不是真正的"尾盘"代理：缺实盘 scanner 抓的 close-position / pullback-from-high 形态。

### 2.2 BacktestEngine —— 回测步骤与真实度缺口

`src/strategy/engine/backtest.py`，`run()` 在 `:173-277`：

1. 按交易日遍历；调仓日（`i % rebalance_days == 0`，脚本覆盖为 1 = 日频）重算复合分。
2. 选 top-N；卖出不在名单的、买入新选股（等权）。
3. 记录每日净值、收益、持仓。

默认 `rebalance_days=5, top_n=10, equal_weight=True`，脚本用日频。

**真实度缺口（agent 报告，未逐行复核但可信）**：
- 🔴 `equal_weight=False` 是空操作：`backtest.py:236-239` 两个分支一模一样，都 `cash / top_n`。没有按分数/波动率加权的逻辑。ARCHITECTURE.md:107 也承认。
- 🔴 涨跌停检查被禁用：`submit_order` 从不传 `prev_close` → 默认 0.0 → `_check_price_limit`（`broker.py:240`）直接放行。ST/涨跌停股会被当正常成交。
- 🟠 信号与成交都用当日收盘价 → 轻微前视。
- 🟠 每个调仓日对**全历史 expanding window** 重算因子 → O(N²)。
- ✅ T+1、费率（佣金 0.025%、印花税卖出 0.05%、最低 5 元）是真实的。

### 2.3 参数网格评估 —— 串行、慢、无因子有效性度量

`scripts/evaluate_tail_session_grid.py` + `src/research/tail_session_analysis.py`：
- 扫 `breakout_window / trend_window / volume_ratio_threshold / top_n / min_score`。
- **tail/overnight 权重 0.7/0.3 硬编码**，不进网格。
- **串行**（`tail_session_analysis.py:30`，无 joblib/多进程），每配置一次完整 `BacktestEngine.run()` + 每日 expanding 重算 → 慢。磁盘上只有 2~4 配置的烟测，印证它慢。
- 输出 CSV 按 Sharpe → total_return 排序，只含组合级 metrics。
- **致命缺口**：**从不计算 IC / RankIC / ICIR / 分层收益 / 单调性**。无法区分"因子反预测"与"组合组装错了"。

### 2.4 history.py —— 历史选股报告

`src/strategy/tail_session/history.py:13-49`，`build_historical_selection_rows`：每日切片 expanding window 调 `FactorScoreEngine.select`，产出 `{date, rank, symbol, score}`。是 ARCHITECTURE.md:78-84 列出的 FactorScoreEngine 契约三消费者之一（另两个是 `BacktestEngine._compute_composite_score`、`SignalEngine._compute_composite`）——所以研究选股与回测排名用同一套评分，一致性 OK。同样是 O(N²)。

### 2.5 filters.py —— 死代码

`src/strategy/filters.py` 的 `DailyBreakoutFilter` / `DailyTrendFilter` / `StockPoolFilter`：grep 全仓只有 `tests/test_strategy/test_filters.py` 引用，**生产代码零引用**。breakout/trend 逻辑与 TailSessionFactor 重复。其 ST/次新/涨跌停池过滤**未被搬进因子**——所以研究宇宙比实盘池更脏。

### 2.6 tail_session_analysis.py —— 只有组合指标，无因子诊断

`src/research/tail_session_analysis.py`（77 行）只产出 end-to-end 组合 metrics。IC/分层工具（`src/research/factor_analysis/ic_analysis.py` 的 `ICAnalyzer`、`quantile.py` 的 `QuantileAnalyzer`）**早就写好**，但 grep 显示只被 `scripts/test_phase3.py` 冒烟和单测用，**从未接进尾盘研究路径**。

---

## 3. 系统 B：实盘分钟级选股（非本次焦点，仅记录）

`src/web/backend/tail_live.py:run_tail_live_selection`（`:61`）为主路径：

| 阶段 | 位置 |
|---|---|
| 时段/交易日守卫 | `tail_live.py:70` |
| 股票池解析 | `:580` → `tail_session/live.py:42` |
| 市场宽度门（< 阈值则短路空结果） | `tail_live.py:99`；计算 `tail_session/live.py:110` |
| 5 分钟扫描打分 | `scanner.py:63`；候选门槛 `volume_ratio>=1.5 & tail_return>=0`（`scanner.py:174`） |
| 确认（连续 N 次扫描） | `scanner.py:137` |
| v2 多因子打分 + 分层 strong/watchlist/weak | `v2_scorer.py:42` |
| 取 top-N | `tail_live.py:513-543` |
| ML 增强重排（model/hybrid 模式） | `tail_live.py:308, 396` |
| 写 JSON/CSV/MD 报告 | `reports.py:60,79,119` |

**问题（agent 报告）**：
- 三套排名函数对同一批信号给出不一致结果：`reports.select_tail_session_signals`（按 strength 排序）、`v2_scorer.score_tail_signals`（4 因子加权）、`_credibility`（`tail_live.py:956`，第三套权重）。
- 候选门槛硬编码：v2 内部用 `0.02`（追高）、`2.5`（过量）、`0.015`（回撤）等魔数，与对外报告的 `volume_ratio_threshold:1.5 / min_tail_return:0.0` 不同步。
- CLI（`scripts/run_tail_session_live.py`）走老 `reports.select`，**无 v2 无 ML**——与 web 行为分叉。

---

## 4. 系统 C：ML 增强层（非本次焦点，仅记录）

模型：sklearn `HistGradientBoostingClassifier/Regressor`（**非 LightGBM**），三模型一组——`hit`（命中下一日高点 ≥1%）、`risk`（回撤破 2%）、`high`（next_high_return 回归）。walk-forward 训练（`train_days=60/val=10`），工件落 `models/tail_session/<version>/`。

**问题（agent 报告，影响选股质量，但不在系统 A 范围）**：
- 🔴 **三套打分公式权重不一**：训练 `_risk_adjusted_score`（`tail_model.py:227`，`0.35hit+0.20high+0.15exp−0.45risk`）、推理 `TailModelInference.score`（`tail_inference.py:33`，`0.45hit+0.35high−0.20risk`）、规则基线 `_rule_score`（`tail_rule_baseline.py:35`）。
- 🔴 **重复计数**：`_risk_adjusted_model_score`（`tail_live.py:489`）把已融合 hit/risk 的 `model_score` 当作 `high_rank` 再喂回 `_risk_adjusted_score`，hit/risk 被算两遍。
- 🔴 **历史校准在 hybrid 模式基本空挂**：`calibrated_probability` 常为 `None` → `_model_selection_score = model_score*0.55 + 0*0.45`，0.45 校准权重没用上。
- 🟠 **线上模型过时**：promoted 工件只有 18 特征，代码默认已是 25（新增行业/成交额热度）；推理按模型自带 `feature_columns` 跑，新特征不重训+重 promote 不生效。

---

## 5. 实证证据（磁盘上的真实跑批，已亲自复核）

| 文件 | 结果 |
|---|---|
| `reports/tail_session/grid_recent50_key4.csv` | 4 配置全亏，total_return **−23.75% ~ −40.90%**，Sharpe −1.06 ~ −1.21，max DD 高至 **−48.4%** |
| `reports/tail_session/backtest_recent_liquid30_quality_ma20_ret8_turnover1e8.json` | **−15.71%**，Sharpe −0.849，胜率 32% |
| `reports/tail_session/grid_liquid10_smoke.csv` | 2 配置勉强打平（+2.3~2.6%，Sharpe≈0） |
| `reports/tail_session/historical_daily_selections_20260512_20260610.json` | **全空**：`selection_day_count:0, selection_count:0` |

### 5.1 🔴 找到"空报告 + 退化分数"的两个直接原因（已亲自复核）

**原因一：`min_score` 把门槛套到每个因子的原始值上。** `src/strategy/scoring.py:52-53`：

```python
if self.min_score is not None:
    values = values.where(values >= self.min_score)   # 对【每个因子】的原始值过滤
```

- 对离散 tail 因子（0/0.4/0.7/1.0）`--min-score 0.7` 当入选门槛没问题；
- 但 `OvernightMomentumFactor` 是连续隔夜跳空（≈0），任何 `min_score>0` 会把它整列 NaN → `composite.add(..., fill_value=0)` 填回 0 → **0.3 的隔夜权重整个失效**，连带把选股打空。这极可能是历史选股报告为空的主因之一。

**原因二：市场宽度门默认偏严** → 直接把整天滤空。`breadth_050`（0.5）和 `breadth_055`（0.55）两个放宽变体是**非空**的，反向佐证。

**退化证据**：非空报告里每只入选票分数全是 **`0.42`**（= `0.7 × 0.6`，5 只并列 → pct-rank 0.6 × 权重 0.7），隔夜项贡献 0。说明哪怕选出票，分数也**毫无区分度**——但这目前只是猜测，从未被 IC 度量过。

---

## 6. 发现汇总（按系统 / 严重度）

### 系统 A（本次焦点）
| 级别 | 项 | 位置 |
|---|---|---|
| 🔴 | `min_score` 逐因子过滤，NaN 掉隔夜因子 → 退化分数 + 空报告 | `scoring.py:52` ✅已复核 |
| 🔴 | 网格从不计算 IC/RankIC/ICIR/分层/单调性，无法判断因子是否有效 | `tail_session_analysis.py` |
| 🟠 | `equal_weight=False` 空操作 | `backtest.py:236-239` |
| 🟠 | 涨跌停检查被禁用（`prev_close` 不传） | `backtest.py:233,247` / `broker.py:240` |
| 🟠 | 因子 4 档离散、无量级、非真正尾盘形态 | `factors/tail_session.py:95-99` |
| 🟡 | `filters.py` 死代码，ST/次新/涨跌停未搬进因子 | `filters.py` |
| 🟡 | 网格串行 + O(N²) expanding，慢 | `tail_session_analysis.py:30` |
| 🟡 | 策略在亏钱（−15% ~ −40%），但无诊断层解释为何 | 磁盘产物 |

### 系统 B（非焦点，记录待办）
- 三套排名函数不一致；候选门槛魔数硬编码；CLI/web 行为分叉。

### 系统 C（非焦点，记录待办）
- 三套打分公式权重不一；`high_rank` 重复计数；hybrid 历史校准空挂；线上模型过时（18 vs 25 特征）。

> 2026-06-25 数据复查另有 P0/P1 数据层问题（daily 并发锁已修、`joinable_label_days` 误报 limited、ST 过滤大小写、可交易池 SQL 30/120 阈值不一、`_return` 两处语义分歧），详见前序 review，不在本文范围。

---

## 7. 验证置信度说明

为避免把猜测当事实驱动后续决策，标注每条发现的来源：

- ✅ **亲自读源码/产物复核**：系统全景（README/ARCHITECTURE）、`min_score` bug（`scoring.py`）、退化 `0.42` 分数与空报告（磁盘 JSON）、IC/Quantile 工具 API、项目结构。
- 🔶 **Explore agent 报告，未逐行复核但可信**：TailSessionFactor 4 档逻辑、BacktestEngine 真实度缺口（equal_weight 空操作 / 涨跌停禁用）、网格串行 O(N²)、`history.py` 流程、`filters.py` 死代码、`tail_session_analysis.py` 无 IC、系统 B/C 的打分公式与重复计数问题。
- 后续若要据此动手，建议先把 🔶 项逐行复核一遍。

---

## 8. 当前决策状态（brainstorming 进度）

优化方向已确定：**系统 A（研究/回测路径）**，第一版目标倾向"**先建因子诊断层 + 修导致空报告的 bug**"（看清因子到底有没有预测力，再谈优化）。

**尚未回答、需用户拍板的问题**：
1. "优化尾盘选股"的终极目标——是让**研究结论最终能喂回实盘**，还是**先把研究路径本身做对、能产出可信结论**？
2. 亏钱这个事实——更怀疑因子方向错了，还是回测/选股逻辑有 bug 把好信号弄丢了？
3. 是想先看到一份"因子有没有用"的诊断报告再定下一步，还是已有怀疑方向要我验证？

**已草拟但未选定**的方案（v1 范围）：
- 方案 A（推荐）：手术式——修 `min_score` + 可复用诊断模块 + 独立 CLI，不碰网格/web。
- 方案 B：在 A 基础上把 IC/RankIC/单调性加进网格 CSV。
- 方案 C：A + 网格 IC 列 + 回测 `--diagnose` 模式 + 版本化 scorecard 工件。

> 本文写成时**尚未选定方案、未写设计 spec**。下一步取决于上面 3 个问题的答复。

---

## 9. 关键文件索引

- 研究路径核心：`src/strategy/factors/tail_session.py`、`src/strategy/scoring.py`、`src/strategy/engine/backtest.py`、`src/strategy/tail_session/history.py`、`src/strategy/tail_session/backtest.py`、`src/research/tail_session_analysis.py`
- 可复用诊断工具（未接入）：`src/research/factor_analysis/ic_analysis.py`、`src/research/factor_analysis/quantile.py`
- 实盘路径：`src/web/backend/tail_live.py`、`src/strategy/scanner.py`、`src/strategy/tail_session/v2_scorer.py`
- ML：`src/ml/tail_features.py`、`tail_labels.py`、`tail_dataset.py`、`tail_model.py`、`tail_inference.py`、`tail_model_registry.py`
- CLI：`scripts/run_tail_session_backtest.py`、`scripts/evaluate_tail_session_grid.py`、`scripts/run_tail_session_live.py`
- 死代码：`src/strategy/filters.py`
- 磁盘实证：`reports/tail_session/grid_recent50_key4.csv`、`reports/tail_session/historical_daily_selections_20260512_20260610*.json`
