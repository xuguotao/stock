# 2026-06-29 尾盘因子 Walk-Forward IC 验证 设计

> **状态**：设计 spec，已 brainstorm 四块定稿，待用户复核。
> **前序**：`docs/superpowers/reviews/2026-06-29-tail-factor-diagnosis-report.md`（单次诊断得出 overnight ICIR 0.36、tail ICIR 0.17，但打了三个折扣：in-sample / 自相关 / 未扣成本）。本设计逐条确认或推翻这三个折扣。
> **关联 plan 占位**：本 spec 通过后转 writing-plans 出实施 plan。

---

## 0. 一句话目标

跑完 walk-forward 报告后，能用数据明确回答："隔夜因子 ICIR 0.36 是稳定的真 edge、还是样本内偶然 / 自相关 / 未扣成本造成的假象"，并把诊断报告 §4 的三个折扣逐条确认或推翻。

---

## 1. 背景：为什么需要它

单次诊断报告（§1.1）得出 overnight_momentum ICIR 0.36、IC 正比率 64%，结论是"有方向性预测力"。但报告自己打了三个折扣：

1. **样本内**：全窗 2025-2026 一次性算 IC，没有时序切分验证，可能"换段时间就不行"。
2. **自相关**：`overnight_momentum` = 滞后隔夜跳空，forward return = 下一日隔夜跳空；IC 高可能部分是隔夜序列的机械自相关，不等于可交易 edge。
3. **未扣成本**：spread 0.27% 是毛 edge，日频换仓扣完成本可能所剩无几，与策略实跑 −15% ~ −40% 亏钱一致。

walk-forward 验证的目标就是**用数据逐条回答这三个折扣**。

### 1.1 重要更正：walk-forward 单独不能回答自相关

> brainstorming 时澄清的一个关键认知：walk-forward 只能回答"因子在不同时段是否稳定"（排除某一段偶然高）。但**自相关信号在 walk-forward 里会显得很好**——稳定高 ICIR 跨各折，因为自预测信号天然一致。所以"walk-forward IC"和"自相关探针"是**互补而非替代**，必须叠加才能区分"真 edge"和"自相关假象"。本设计采用两者叠加。

---

## 2. 范围与不做的事（YAGNI）

**做**：
- walk-forward 滚动 IC 稳定性
- 自相关探针（衰减 / 滞后基线 / 换手率代理）
- 扣成本净 edge（口径 A 单边 + 口径 B 价差，两个都报）
- 一份动态结论报告

**不做**：
- 不改回测引擎、不改网格、不改实盘路径、不改 web。
- 不做策略组合优化、不做仓位/风控——只度量因子本身的预测力与净 edge。
- 不抽库模块（方案 3 被否，YAGNI）——研究分析脚本，函数保持可 import 供日后复用即可。
- 不补 S01 缺失因子（涨停基因/换手率/板块龙头）——那是后续独立工作，依赖本验证的结论。

---

## 3. 架构

**方案 1（已选定）：新独立脚本。**

```
scripts/diagnose_tail_factors_walkforward.py   ← 新建（CLI + 分析逻辑）
        │
        │ import 复用
        ├─→ scripts/diagnose_tail_factors.py
        │      • compute_overnight_forward_return  （隔夜 open(t+1)/close(t)-1）
        │      • diagnose_factor（单次 IC/分层，walk-forward 每折调它）
        │
        ├─→ src/research/factor_analysis/ic_analysis.py  ICAnalyzer（不修改）
        ├─→ src/research/factor_analysis/quantile.py    QuantileAnalyzer（不修改）
        │
        │ walk-forward 窗口逻辑参考（不 import，照搬写法）
        ├─→ src/ml/tail_model.py:43  train_tail_model_walk_forward  （rolling 按交易日）
        │
        │ 成本费率复用
        └─→ src/core/broker_base.py  FeeCalculator.from_settings()  （真实费率，不另造魔数）
```

**输出**：
- `reports/tail_session/factor_diagnosis_walkforward.json`（本地生成物，`reports/` 仍 gitignore）
- `docs/superpowers/reviews/2026-06-29-tail-factor-walkforward-report.md`（动态结论报告，入库）

---

## 4. 组件设计

### 4.1 walk-forward 滚动 IC（对应折扣①样本内）

- **窗口**：照搬 `tail_model.py:43` 的 rolling 按交易日。每折在一个 60 天窗口上算 IC（→ 约 60 个日度 IC 值 → 一个稳定的该折 ICIR），步进 10 天。cache 约 339 个交易日 → 约 28 折。窗口大小（60/10）走 CLI 可配。
- **每折产出**：ICIR、IC 正比率、IC 均值（复用 `ICAnalyzer` 逐日 IC → `ic_summary`，但限定在该折窗口的日期子集上）。
- **跨折汇总**：ICIR 均值 / 标准差、ICIR>0 的折占比、最差一折的 ICIR、单调性是否跨折一致。
- **判定（动态）**：若 ICIR 跨折稳定为正且 >0 的折占比高（如 >70%）→ 排除"换段时间就不行"，折扣①被推翻；若各折 ICIR 大幅波动或频繁转负 → 折扣①坐实。

### 4.2 自相关探针（对应折扣②自相关）—— 三项叠加

1. **多日衰减**：forward period 从 1 日扩到 2/3/5 日，看 IC 是否随 horizon 递减。真 edge 通常缓慢衰减；纯自相关往往 1 日强、之后快速塌。
2. **滞后自相关基线**：直接算"前一日隔夜收益"与"当日隔夜收益"的相关（把因子替换成纯滞后隔夜值，forward return 不变），作为 IC 的"自相关地板"。若因子 IC ≈ 滞后基线相关 → IC 多半是自相关。
3. **换手率代理**：因子逐日排名变化比例（rank 每日变动 >某阈值的比例）。自相关信号换手率极低（排名几乎不变）；真 edge 排名随新信息变动。`ICAnalyzer`/`QuantileAnalyzer` 不提供 turnover，在脚本里自己算。
- **判定（动态）**：若衰减缓慢、滞后基线相关显著低于因子 IC、换手率非极低 → 折扣②被推翻；若 1 日 IC 强但快速塌、或 IC ≈ 滞后基线 → 折扣②坐实（IC 上界，实盘缩水）。

### 4.3 扣成本净 edge（对应折扣③未扣成本）—— 两个口径都报

复用 `FeeCalculator.from_settings()` 算真实成本，**不手写费率魔数**，与回测引擎口径完全一致（含过户费 0.00001、证管费 0.0000487，买卖都收——这两项是 `broker_base.py:114-115` 硬编码、不在 settings 里，复用 FeeCalculator 自动包含）。

- **口径 A 做多单边**（贴实盘）：top 分位组的平均隔夜收益 − 买入成本。S01 只做多 top-N，这个最贴近实际能赚的钱，但受市场 beta 影响。买入成本 = 佣金 + 过户费 + 证管费（买入不收印花税）。
- **口径 B 多空价差**（纯因子）：top−bottom 分位价差 − 往返成本（买入端 + 卖出端，含卖出印花税）。标准因子研究口径、信号更纯，但 S01 不做空，价差高估实际可赚的钱。
- **每折都报净 edge**，跨折汇总是否稳定为正。
- **判定（动态）**：
  - 若口径 A 单边净 edge 扣完成本后跨折仍为正 → 因子真有可交易 edge。
  - 若口径 B 价差正但口径 A 单边为负 → "有信号但策略不赚钱"，指向组合/执行问题（与策略实跑亏钱一致）。

### 4.4 报告与综合判定

`docs/superpowers/reviews/2026-06-29-tail-factor-walkforward-report.md`，**动态结论**（不预设隔夜 edge 真不真，跑出什么写什么）。结构：

1. walk-forward 稳定性（每折 ICIR 表 + 跨折汇总）
2. 自相关探针结论（衰减曲线、滞后基线相关、换手率代理）
3. 净 edge（口径 A + 口径 B，扣成本后跨折是否为正）
4. **综合判定**：把诊断报告 §4 的三个折扣逐条标注【已推翻 / 坐实 / 部分成立】
5. 复现命令 + 成本参数来源说明

---

## 5. 数据流

```
offline parquet cache (data/cache/bars/, ~339 交易日)
   │
   ▼
bars DataFrame (MultiIndex date,symbol + OHLCV)
   │
   ├─ compute_overnight_forward_return(bars) → fr (open(t+1)/close(t)-1)
   │
   ├─ walk-forward 折循环 (每折取窗口日期子集)
   │     ├─ factor.compute(bars 窗口) → fv
   │     ├─ ICAnalyzer.compute_ic/rank_ic/ic_summary(fv, fr 窗口) → 该折 ICIR
   │     └─ QuantileAnalyzer.analyze(fv, fr 窗口) → 该折 spread / top 分位收益
   │
   ├─ 自相关探针：多 horizon IC + 滞后基线相关 + 换手率代理
   │
   ├─ 净 edge：FeeCalculator.from_settings() 算成本 → top 分位收益 − 成本（A）/ spread − 往返成本（B）
   │
   ▼
reports/tail_session/factor_diagnosis_walkforward.json
   │
   ▼
docs/superpowers/reviews/2026-06-29-tail-factor-walkforward-report.md（动态结论）
```

---

## 6. 复用与不重复造轮子

| 需要的能力 | 复用来源 | 是否修改 |
|---|---|---|
| 隔夜 forward return | `scripts/diagnose_tail_factors.py:compute_overnight_forward_return` | 不改，import |
| 单折 IC/分层 | `scripts/diagnose_tail_factors.py:diagnose_factor` | 不改，import |
| IC/RankIC/ICIR/IC 正比率 | `src/research/factor_analysis/ic_analysis.py:ICAnalyzer` | 不改 |
| 分层 spread/单调性 | `src/research/factor_analysis/quantile.py:QuantileAnalyzer` | 不改 |
| walk-forward 窗口写法 | `src/ml/tail_model.py:43` | 照搬写法，不 import |
| 真实费率 | `src/core/broker_base.py:FeeCalculator.from_settings()` | 不改，复用 |
| 因子构造 | `TailSessionFactor` / `OvernightMomentumFactor`（与生产路径同参） | 不改 |

**新增代码**只在 `scripts/diagnose_tail_factors_walkforward.py`：折循环、自相关三项、净 edge 两口径、JSON 序列化（沿用 `diagnose_tail_factors._sanitize_for_json`）。

---

## 7. 边界与已知限制

- **forward return 仍只覆盖隔夜单日**：本设计不补多日持仓标签——4.2 的"多日衰减"是把 IC 的 forward horizon 扩到 2/3/5 日（同一隔夜序列的 forward return 不同 horizon），不是策略持仓周期变化。
- **数据窗 ~339 天**：约 28 折。若窗口设太大会折数太少；太小会每折 ICIR 不稳。默认 60/10 是和 ML 对齐的折中，CLI 可调。
- **换手率是代理不是真实换手**：因子排名变动比例，不等于组合换手（组合换手还含持仓权重变化）。报告里标注此区别。
- **无 walk-forward 跨折 ICIR 的统计检验**：报告用描述统计（均值/std/占比/最差），不上 t 检验——研究阶段够用，YAGNI。
- **净 edge 仍是因子层面**：不等于真实策略收益（真实策略还含 top_n 选择、等权、容量限制、breadth 门）。报告标注。

---

## 8. 验收标准

跑完 `scripts/diagnose_tail_factors_walkforward.py --offline-cache --start 2025-01-01 --end 2026-06-01` 后，产出 JSON + 报告，报告能回答：

1. overnight 因子 ICIR 跨 ~28 折是否稳定为正？（折扣①）
2. 衰减/滞后基线/换手率三项是否指向自相关？（折扣②）
3. 口径 A 单边净 edge 和口径 B 价差净 edge 扣成本后是否为正？（折扣③）
4. 三个折扣各自【已推翻 / 坐实 / 部分成立】的明确判定。

---

## 9. 待用户拍板（转 plan 时确认）

1. 窗口默认 60/10 是否就采用？（与 ML 对齐）
2. 多日衰减的 horizon 用 [1,2,3,5] 是否够？
3. 报告综合判定之外，是否要把"若坐实自相关，下一步怎么走"也写进报告？（倾向写一句话指针到 S01 缺失因子，不展开）
