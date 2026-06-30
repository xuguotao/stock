# 2026-06-29 尾盘因子 Walk-Forward IC 验证报告（动态结论）

> **范围**：用 walk-forward 滚动 IC + 自相关探针 + 扣成本净 edge，逐条确认或推翻单次诊断报告（§4）对 overnight 因子打的三個折扣：①样本内 / ②自相关 / ③未扣成本。
> **方法**：新建 `scripts/diagnose_tail_factors_walkforward.py`，复用 `compute_overnight_forward_return` + `ICAnalyzer`/`QuantileAnalyzer` + `FeeCalculator.from_settings()`。rolling 固定窗（60 天/步进 10，与 `tail_model.py` 一致），全窗 28 折。
> **数据**：offline parquet cache，2025-01-01 ~ 2026-06-01，28 折。全窗实跑日期 2026-06-30。
> **产物**：`reports/tail_session/factor_diagnosis_walkforward.json`（`reports/` 全目录 gitignore，本地生成物，见 §6 复现命令）。
> **前序**：`docs/superpowers/reviews/2026-06-29-tail-factor-diagnosis-report.md`（单次诊断得出 overnight ICIR 0.36、tail ICIR 0.17，打三折扣）。

---

## 0. 一句话结论

**三个折扣：①样本内已推翻（隔夜 ICIR 跨 28 折稳定为正）；②自相关坐实（隔夜因子的"预测力"本质上就是隔夜收益序列的自相关，无独立 edge）；③未扣成本部分成立（扣成本后做多单边净 edge 极薄，0.025%/日，不足以覆盖实盘摩擦）。**

且发现一个单次诊断没暴露的 nuance：**tail_session 虽 IC 弱，但 top 分位次日隔夜绝对收益反而高于 overnight（口径 A 净 0.36% vs 0.025%/日）**——IC 弱 ≠ top 分位无 edge，这对 S01（选 top-N 持有）比 IC 更有意义。

---

## 1. walk-forward 稳定性（折扣①：样本内）

| 指标 | tail_session | overnight_momentum |
|---|---|---|
| 折数 | 28 | 28 |
| ICIR 均值 | 0.1867 | **0.3231** |
| ICIR 标准差 | 0.2369 | 0.2089 |
| ICIR>0 折占比 | 0.93（26/28） | **1.00（28/28）** |
| 最差折 ICIR | −0.0641 | **0.0726** |
| IC 正比率均值 | 0.548 | 0.618 |

### 判定

- **overnight**：ICIR 跨 28 折**全部为正**（占比 100%），最差折 0.073 仍 >0，均值 0.323（略低于单次的 0.359，合理——单次是全窗一个 ICIR，walk-forward 是 28 折均值）。**折扣① 已推翻**：不是某一段偶然高，跨时段稳定。
- **tail_session**：26/28 折正，但有 2 折为负（最差 −0.064），均值 0.187 弱。**折扣① 部分推翻**：弱稳定，比单次的 0.17 略好但仍弱。

---

## 2. 自相关探针（折扣②：自相关）

三項：decay（多日 IC 衰减）+ lagged_baseline（滞后隔夜基线，两因子共享的"隔夜自相关地板"=0.1092）+ turnover（排名变动代理）。

| 探针 | tail_session | overnight_momentum |
|---|---|---|
| decay ICIR h=1 | 0.1728 | 0.3594 |
| decay ICIR h=2 | **−0.0311** | 0.2123 |
| decay ICIR h=3 | −0.0008 | 0.2319 |
| decay ICIR h=5 | −0.0280 | 0.1449 |
| decay IC_mean h=1 | 0.0419 | 0.1120 |
| lagged_baseline_corr | 0.1092 | 0.1092 |
| turnover_proxy | 0.8714 | **0.9781** |

### 关键认知澄清（重要）

**`OvernightMomentumFactor(smoothing_window=1)` 的定义是 `gap = (open_t − close_{t-1}) / close_{t-1}`——即"当日隔夜"。而 forward return 是 `open_{t+1}/close_t − 1`（次日隔夜）。所以 overnight 因子本身就是"前一日隔夜"，它的 IC 直接度量"今日隔夜 → 次日隔夜"的隔夜序列自相关。**

这意味着对 overnight 因子，**因子 IC@h1（0.112）≈ 滞后基线（0.109）不是巧合，而是同一相关关系的两个角度**——滞后基线探针把因子替换成"前一日隔夜"，但 overnight 因子本身就是前一日隔夜，所以两者度量同一件事。这确认了：overnight 因子的全部"预测力"就是隔夜收益序列的自相关，没有独立 edge。

（滞后基线对比对 tail_session 仍有效：tail_session decay_ic_mean[1]=0.0419 < 滞后基线 0.1092，即 tail_session 对次日隔夜的预测力还不如纯隔夜自相关。）

### 判定

- **overnight**：**折扣② 坐实（自相关）**。三个证据：(1) 因子定义=滞后隔夜→IC 本质是自相关；(2) decay 1→5 日衰减（0.359→0.145），1 日强后递减，自相关特征；(3) turnover=0.978 极高（排名几乎天天变），可交易性差——虽有序列自相关，但"哪些票隔夜最强"每天大换血，无法固定持有。
- **tail_session**：decay h1=0.173 → h2=**−0.031**（次日一过就转负/零），预测力仅限次日且弱；且 IC@h1（0.042）< 滞后基线（0.109），不如纯隔夜自相关。turnover=0.871 也高。

---

## 3. 扣成本净 edge（折扣③：未扣成本）

成本复用 `FeeCalculator.from_settings()`（佣金 0.00025 / 印花税 0.0005 仅卖 / 最低 5 / 过户 0.00001 / 证管 0.0000487 买卖都收），单笔金额 = 10 万 / top_n=5 = 2 万/leg。

| 指标 | tail_session | overnight_momentum |
|---|---|---|
| 毛收益 top 分位（%/日） | **0.3941** | 0.0559 |
| 毛 spread（%/日） | 0.3092 | 0.2725 |
| 买入成本率 | 0.0309% | 0.0309% |
| 往返成本率 | 0.1117% | 0.1117% |
| **口径 A 做多净 edge**（%/日） | **0.3632** | 0.0250 |
| 口径 B 多空净 edge（%/日） | 0.1975 | 0.1608 |

### 判定

- **overnight**：**折扣③ 部分成立**。口径 A（贴实盘做多 top）净 edge 仅 **0.025%/日**（年化~6%）——扣完成本后极薄，远没毛 spread 看着好。这解释了策略实跑亏钱（−15%~−40%）：理论净 edge 微正，但叠加 turnover=0.978 导致的实际换手成本/滑点/容量限制后，净 edge 被吃光。"有信号但策略不赚钱"，指向执行/组合问题，不是因子方向错。
- **tail_session**：**意外发现**——口径 A 做多净 edge **0.363%/日**（年化~91%），**远高于 overnight**。tail_session 选出的 top 分位（最强 breakout/trend/volume 信号那批票）次日隔夜确实涨得多（毛 0.39%/日），即使 IC（横截面整体排名）弱。

### 关键 nuance：IC 弱 ≠ top 分位无 edge

单次诊断用 IC 判 tail_session"预测力弱"（ICIR 0.17），但分层看 top 分位绝对收益，tail_session 反而比 overnight 强。原因：tail_session 是 4 档离散，选出的是少数强信号票；IC（全截面 Pearson 相关）被大量中间票稀释变弱，但 top 分位的少数票次日隔夜收益高。**对 S01（选 top-N 持有，不是全截面排名）而言，top 分位绝对收益比 IC 更相关。** 这修正了单次诊断对 tail_session 的悲观判断。

---

## 4. 综合判定：三折扣逐条

| 折扣 | overnight_momentum | tail_session |
|---|---|---|
| ① 样本内 | **已推翻**（28/28 折 ICIR 正，最差 0.073>0） | 部分推翻（26/28 正，2 折负，弱） |
| ② 自相关 | **坐实**（因子=滞后隔夜，IC=自相关；decay 衰减；turnover 0.978） | 弱（1 日后转负；IC<滞后基线） |
| ③ 未扣成本 | **部分成立**（口径 A 净 0.025%/日，极薄，实盘被摩擦吃光） | 口径 A 净 0.36%/日，可观 |

### 对单次诊断结论的修正

单次诊断说"overnight 有预测力（ICIR 0.36）、tail_session 弱"。walk-forward 修正为：
- **overnight 的"预测力"是自相关假象**——ICIR 跨折稳定（0.323），但稳定地高正是因为因子定义就是滞后隔夜，它的 IC 本质是隔夜序列自相关，不是独立预测 edge。扣成本后做多净 edge 仅 0.025%/日，实盘不可行。**诊断报告 §4 折扣②、③ 坐实。**
- **tail_session 被低估**——IC 弱没错，但 top 分位次日隔夜绝对收益（净 0.36%/日）反而可观。IC 不是衡量"选 top-N"策略的唯一指标，分层绝对收益更相关。

---

## 5. 下一步建议（待用户拍板，不在本 plan 范围）

1. **overnight 因子本质上不可单独交易**（自相关 + 净 edge 极薄 + turnover 0.978）。但它作为"隔夜溢价的环境指示"可能仍有价值——而非作为选股因子。
2. **tail_session 的 top 分位 edge（0.36%/日净）值得深究**——但 turnover 0.871 也高。下一步应：把"top 分位绝对收益"接进回测引擎，看真实 top-N 持仓（含换手成本）的净收益，而非因子层 IC。
3. **补 S01 缺失因子**（涨停基因/换手率/板块龙头）仍优先级低——先用上面第 2 步确认 tail_session top 分位 edge 是否真实可交易，再决定补什么。
4. **回测引擎的 forward return 口径**：诊断度量 IC 对 `open(t+1)/close(t)-1`（隔夜），但 `BacktestEngine` 若用 close-to-close 结算 PnL，则"因子预测隔夜"≠"回测按隔夜结算"——需确认回测引擎实现收益与隔夜 forward return 一致（最终 review 提及的设计一致性问题）。

---

## 6. 复现命令 + 成本来源

```bash
python scripts/diagnose_tail_factors_walkforward.py --offline-cache \
  --start 2025-01-01 --end 2026-06-01 --out reports/tail_session/factor_diagnosis_walkforward.json
```

- 成本：`FeeCalculator.from_settings()`（`src/core/broker_base.py:93`），读 `config/commission.yaml` + `config/trading_rules.yaml`，非手写魔数。单笔金额 = `--trade-capital / --top-n`（默认 10 万/5 = 2 万/leg）。
- JSON 严格合法（NaN/Inf→null，复用 `_sanitize_for_json`）。
- 运行时有 warmup `RuntimeWarning`/`ConstantInputWarning`（tail_session warmup 期常量数组导致 corr=NaN，已 dropna），属预期。

---

## 7. 限制声明（诚实标注）

- **数据窗 ~339 天**：28 折，每折 60 天。窗口偏大会折数少；偏小每折 ICIR 不稳。
- **turnover 是代理非真实换手**：因子排名变动比例，不等于组合换手（组合换手还含持仓权重变化）。报告里两个因子 turnover 都高（0.87/0.98），但实际组合换手需回测引擎算。
- **净 edge 是因子层面**：不等于真实策略收益（真实策略还含 top_n 选择、等权、容量、breadth 门、滑点）。
- **滞后基线对 overnight 是同源**（§2 已澄清）：因子定义=滞后隔夜，故该探针对 overnight 不提供独立检验，仅对 tail_session 有效。
- **口径 A 年化是粗估**：0.36%/日 × 252 是简单年化，未考虑复利/换手成本累积，仅作量级参考。
