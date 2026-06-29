# 2026-06-29 尾盘因子诊断报告（动态结论）

> **范围**：度量尾盘选股系统 A 现有两个因子（`tail_session`、`overnight_momentum`）对"隔夜收益"的预测力，回答"因子到底有没有用"。
> **方法**：新建独立诊断脚本 `scripts/diagnose_tail_factors.py`，复用 `ICAnalyzer`/`QuantileAnalyzer`，forward return 自定义为隔夜 `open(t+1)/close(t) - 1`（匹配 S01 一夜持股法：尾盘买 close(t)、次日开盘 open(t+1) 卖）。**不预设因子有效/无效**——跑出什么写什么。
> **数据**：offline parquet cache（`data/cache/bars/`，187 文件），窗口 2025-01-01 ~ 2026-06-01。
> **产物**：`reports/tail_session/factor_diagnosis.json`（`reports/` 全目录被 `.gitignore` 排除——见 `.gitignore:56`——故为本地生成物、不入库；可用 §7 命令复现，不强制提交 JSON）。
> **前序**：`docs/superpowers/reviews/2026-06-29-tail-selection-current-state.md`、`docs/superpowers/plans/2026-06-29-tail-factor-diagnosis-and-bugfix.md`。

---

## 0. 一句话结论

**隔夜因子（被 min_score bug 静默杀掉的那个）有方向性预测力，尾盘 4 档离散因子几乎没有。** 这直接回答了上次 brainstorming 留下的怀疑："亏钱，到底是因子方向错了，还是选股逻辑有 bug 把好信号弄丢了？"——证据偏向后者：带预测力的因子被 bug 丢掉了，留下来的反而是预测力弱的因子在扛分。

但这个结论必须打折：隔夜 IC 部分可能是机械自相关，且全是样本内、未扣成本、未做 walk-forward。详见第 4 节「疑」。

---

## 1. 诊断指标（全窗 2025-01 ~ 2026-06）

| 指标 | tail_session（4 档离散） | overnight_momentum（连续） | 判读阈值 |
|---|---|---|---|
| IC_mean | 0.0419 | **0.112** | 越大越好 |
| RankIC_mean | 0.0139 | **0.0619** | 越大越好 |
| **ICIR** | 0.1728 | **0.3594** | ≥0.3 视为有方向性 |
| RankICIR | 0.0755 | **0.282** | |
| IC 正比率 | 0.5469 | **0.6409** | 显著偏离 0.5 才算有方向 |
| RankIC 正比率 | 0.5146 | **0.6053** | 同上 |
| spread（top−bottom） | 0.3092 | 0.2725 | 正=高分位跑赢低分位 |
| monotonicity | 1.0 ⚠️ | 1.0 ⚠️ | >0.5 视为分层单调 |
| top_quantile_ann_return | 169.44 ⚠️ | 15.11 ⚠️ | 见下警告 |

判读规则（plan 预设）：`|ICIR|≥0.3 且 IC 正比率显著偏离 0.5` → 有方向性预测力。

### 1.1 overnight_momentum —— 有方向性预测力 ✅

- ICIR **0.36** > 0.3 阈值；RankICIR 0.28 接近阈值。
- IC 正比率 **64%**、RankIC 正比率 60.5%——明显偏离 50%（不是硬币翻面）。
- 高分位组隔夜收益跑赢低分位组（spread 0.27，正）。
- **这是被 `min_score` bug 整列 NaN 掉、0.3 权重静默失效的因子。** 它恰恰是两个里更有预测力的那个。

### 1.2 tail_session —— 预测力不足 ⚠️

- ICIR 0.17、RankICIR 0.0755——均低于 0.3。
- IC 正比率 54.7%、RankIC 正比率 51.5%——**基本是硬币翻面**，没有稳定方向。
- spread 虽正（0.31），但 IC 指标说横截面排名近乎随机——组合层面"高分位>低分位"更多是少数极端日拉动的，不是稳定信号。

---

## 2. ⚠️ 两个量化伪影（不能当真）

这两个数字看着漂亮，但是工具/方法的已知伪影，**不可作为"因子很强"的证据**：

1. **monotonicity = 1.0（两个因子都是）**：`QuantileAnalyzer` 用 `pd.qcut` 分 5 档。`tail_session` 只有 4 个离散值（0/0.4/0.7/1.0），qcut 必然退化为少数几个 bin；`overnight` 虽连续但日度样本有限。`monotonicity` 是"分位序号 vs 平均收益"的 Spearman 相关，退化 bin 下极易取到 1.0。**这个 1.0 是伪影，不读。**
2. **top_quantile_ann_return = 169%（tail）/ 15%（overnight）**：`(1 + 日均spread)^252 - 1` 年化。日均 spread 0.3 年化会爆炸（0.3%→169% 是复利幻觉）。**这是相对量级参考，不是真实年化收益**——真实策略还含成本、换手、容量限制。

判读以 **ICIR / IC 正比率** 为准，不看这两个伪影值。

---

## 3. 对照 S01 一夜持股法：因子翻译缺什么

S01 七步 vs 现有因子：

| S01 条件 | 现有因子覆盖 | 状态 |
|---|---|---|
| 涨幅 3-5% | breakout（close 破 20 日高） | 🟠 有但无量级、且阈值不对应 3-5% |
| 30 天内有涨停（涨停基因） | — | 🔴 缺 |
| 市值 < 200 亿 | quality 门 `min_turnover_value` 间接 | 🟠 缺直接市值过滤 |
| 量比 > 1 | `volume > MA×1.2` | ✅ 有 |
| 换手率 5-10% | — | 🔴 缺 |
| 分时图（均价线上方、2:30 后新高回踩不破均线） | 实盘 scanner 有，研究因子无 | 🔴 研究路径缺 |
| 板块龙头 | — | 🔴 缺 |

诊断只覆盖了 breakout/trend/volume 那一档（tail_session）和隔夜（overnight_momentum）。**涨停基因 / 换手率 / 板块龙头 / 分时形态** 四项在研究路径里完全没有——而其中涨停基因、换手率是 S01 最核心的"股性活跃"量化条件。这是因子翻译不全的硬伤，但**先不补**：在不知道现有因子有没有用之前补，可能白补。诊断回答了"现有有没有用"，下一步再决定补哪个。

---

## 4. 「疑」——这个结论必须打的折扣（XQuant 方法论）

漂亮 IC 也可能是假象，主动复查：

1. **隔夜 IC 可能是机械自相关**：`overnight_momentum` = 滞后隔夜跳空，forward return = 下一日隔夜跳空。用"昨天的隔夜"预测"明天的隔夜"，部分是隔夜序列的自相关，**不等于扣除成本后的可交易 edge**。ICIR 0.36 是上界，实盘会缩水。
2. **样本内、未做 walk-forward**：全窗 2025-2026 一次性算 IC，没有时序切分验证。XQuant 第 1 章核心警告——"回测里看着赚钱，换段时间就不行"——这里同理，IC 也可能换段失效。
3. **未扣成本**：隔夜策略日频换仓，佣金 0.025%×2 + 印花税 0.05%（卖）+ 滑点，单边约 0.1%+。spread 0.27% 的毛 edge 扣完成本可能所剩无几——这与磁盘上策略实跑 −15% ~ −40% 亏钱一致。
4. **无换手率指标**：`ICAnalyzer`/`QuantileAnalyzer` 不提供 turnover（工具缺口），无法看因子排名稳定性。列为后续可选。
5. **IC 正比率的统计意义**：64% 正是基于 ~365 个交易日，n 够大、偏离 50% 显著；但 IC 单日均值 0.112 量级不大，不要夸大成"强因子"。

---

## 5. 对 min_score 修复（Task 5）的优先级依据

诊断直接给 Task 5 提供了依据，**优先级 = 高**：

- overnight_momentum 有方向性预测力（ICIR 0.36），却被 `min_score` bug 整列 NaN、0.3 权重静默失效。**修这个 bug = 恢复一个真的有用的因子**，不是白修。
- 反过来，tail_session 预测力弱——这印证了上次 review 的怀疑："4 档离散、无量级、非真正尾盘形态"。它不该是扛分的主体。
- 修法仍按 plan Task 5 的 (b) per-factor 字典：`min_score={"tail_session": 0.7}` 只门控离散 tail 因子，隔夜不传 → 不被误杀。

---

## 6. 下一步建议（待用户拍板，不在本 plan 范围）

1. **Task 5-6 修 bug + 复跑**（本 plan 内）：修完后复跑历史选股，确认 `selection_count>0` 且隔夜权重生效、分数有区分度。
2. **walk-forward IC 验证**（后续可选）：把 2025-2026 切成滚动窗，看 overnight ICIR 是否稳定 >0.3，排除样本内过拟合。
3. **扣成本版 spread**（后续可选）：把 spread 0.27% 减去单边 ~0.1% 成本，看净 edge 是否还正。若净 edge 为负，说明"因子有预测力但策略不赚钱"——那是组合/执行问题，不是因子问题。
4. **补 S01 缺失因子**（后续可选，优先级低）：涨停基因、换手率是 S01 核心，但补之前先用上面的 walk-forward 确认 overnight edge 是否真实。

---

## 7. 复现命令

```bash
python scripts/diagnose_tail_factors.py --offline-cache \
  --start 2025-01-01 --end 2026-06-01 --n-quantiles 5 \
  --out reports/tail_session/factor_diagnosis.json
```

输出含 `tail_session` / `overnight_momentum` 两因子的 IC/RankIC/ICIR/IC 正比率/spread/monotonicity。运行时有 6 条 `RuntimeWarning`/`ConstantInputWarning`（tail_session warmup 期常量数组导致 corr=NaN，已在 `ic_summary` 内 dropna）——属预期，非异常。

---

## 8. 附录：min_score 修复复跑验证（Task 6）

Task 5 修了 `min_score` 逐因子过滤 bug 后，复跑之前**全空**的历史选股窗口验证（`--min-score 0.7`，无 breadth 门，以隔离 min_score 这一独立根因）：

| 指标 | 修复前（bug） | 修复后 |
|---|---|---|
| `selection_count` | **0**（全空） | **110**（22 天 × 5/天） |
| 代表性分数 | 全是 `0.42`（=0.7×0.6，隔夜贡献 0，无区分度） | `0.276 / 0.282 / 0.288 / 0.294 / 0.30`（隔夜贡献生效，有区分度） |

结论：bug 修复**恢复了隔夜因子的贡献**——选股不再打空、分数不再退化到单一值。退化分数 `0.42` 的消失直接印证了第 5 节的判断（隔夜是有预测力的因子，却被 bug 丢掉了）。

> 注意：原全空报告的另一根因——市场宽度门默认偏严（root cause #2）——**不在本 plan 范围**。本复跑用无 breadth 门隔离了 min_score 根因；breadth 门仍需单独处理（见原 review `2026-06-29-tail-selection-current-state.md` §5.1 原因二）。

回归测试：`pytest tests/test_strategy tests/test_research tests/test_data/test_clickhouse_research_dataset.py tests/test_web/test_backtests_api.py` → **155 passed**（6 条 warmup warning 属预期）。
