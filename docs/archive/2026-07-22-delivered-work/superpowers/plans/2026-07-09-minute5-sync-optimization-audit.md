# 5 分钟同步优化任务 — 审计发现

> 对象计划:`docs/superpowers/plans/2026-07-09-minute5-sync-optimization.md`
> 审计对象 commit:`1f329c61`(P0/P1)、`316b7fc0`(P2 增量同步)
> 审计日期:2026-07-09
>
> 用途:逐条确认问题存在后再修复。每条带「位置 / 现象 / 触发条件 / 后果 / 如何确认」。
> 确认无误的在 `[ ]` 打勾,确认为误报的标注「误报」并说明。

---

## 总览

| # | 问题 | 类别 | 严重度 | 位置 | 状态 |
|---|---|---|---|---|---|
| 1 | `_check_tail_coverage` 生成的 SQL 把多标的压成"1 行 N 列同名 symbol" | 正确性 | 🔴 高 | `clickhouse_minute5_sync.py:832` | ✅ 已修复 |
| 2 | 中间桶缺失未 fallback 到全量同步(计划 3.2 要求项) | 完整性 | 🟠 中高 | `clickhouse_minute5_sync.py:93-143` | ✅ 已修复 |
| 3 | 缓存"已完整"判定过宽,把中间缺口/未同步标的也标 complete | 正确性 | 🔴 高 | `clickhouse_minute5_sync.py:107`、`:128` | ✅ 已修复 |
| 4 | tail-sync / cache 逻辑零测试覆盖(计划 Phase 3.1/3.2/3.3 要求项) | 测试覆盖 | 🟠 中 | `tests/test_data/test_clickhouse_minute5_sync.py` | ✅ 已补 |
| 5 | 验收标准(耗时/零值率)无验证记录 | 验证 | 🟡 低中 | 计划文档「验收标准」表 | ✅ 已实跑 |

## Fix #5 验收实跑结果(2026-07-09 16:xx,已收盘)

环境:ClickHouse `<PRIVATE_CLICKHOUSE_HOST>/stock`,Python `.venv`,`sync_clickhouse_minute5_kline`。

| 验收项 | 目标 | 实测 | 结论 |
|---|---|---|---|
| P0 amount 零值率 | < 5% | 今日 0.05%(122/239376);抽样 `amount == close×volume×100` 完全吻合(如 10.52×96740×100=101,770,480) | ✅ 对**新数据**通过 |
| P1 全量同步 | < 35s | 收盘后默认跑 140s(5002 no_data)——但属下方「新发现 A」异常,非代表性全量;从空起的全量无法测(各日已满) | ⚠️ 无法干净测量 |
| P2 二次同步 | < 25s | `target_time=15:00` 跑 5.54s(4987 跳过,15 中间缺口标的 fallback 全量) | ✅ 通过 |
| P2 盘中同步 | < 10s | 已收盘,无法测 | ⏳ 待交易时段 |

**P0 历史数据补充说明**:整体零值率仍 79.6%,旧数据是 P0 修复前回填的 amount=0。`sync_clickhouse_minute5_history_window` 只插**缺失行**,不重估已有行的 amount=0,故**重跑历史回填不会降低历史零值率**。要达标需单独"删旧 amount=0 行 + 重回填"的修复,不在本次审计范围。

**Fix #2 生产验证**:上述 5.54s 的运行里,15 只"需刷新但尾部齐全"的中间缺口标的被正确识别为 `middle_gap_symbols` 并 fallback 到全量同步(`sync_mode` 为 None,而非被误判为 `tail_all_complete`),全量路径的缓存标记也正确排除了这 15 只未完整标的。尾同步路径本次未直接命中(无缺尾标的),其逻辑由单元测试覆盖。

## 新发现 A(已修复)

### `_completed_5m_bar_time` 收盘后不封顶 15:00 🟠 → ✅

- **位置**:`src/data/clickhouse_minute5_sync.py:462`(`_completed_5m_bar_time`)
- **原现象**:`_target_datetime` 在今日取 `datetime.combine(today, _completed_5m_bar_time(now))`,而 `_completed_5m_bar_time` 只做 `minute - minute%5`,**不限 15:00 收盘**。收盘后 `target_dt` 会变成 16:15 之类。
- **原后果**:收盘后所有标的 `latest(15:00) < target_dt(16:15)` -> `_needs_refresh` 全 True -> 触发全量同步,白白拉取 5002 只标的、全 no_data、~140s。
- **修复**:在 `_completed_5m_bar_time` 对超过 `time(15, 0)` 的结果封顶到 15:00。(`tail_live.py` 的同名函数受 `is_tail_session()` 门控,只在尾盘时段调用,不受影响,未改。)
- **验证**:单元测试 `test_completed_5m_bar_time_caps_at_market_close`。收盘后默认同步实测 **140s -> 10.91s**(4987 skipped / 15 中间缺口标的 fallback / 0 写入)。

> 注:`tail_live.py:1213` 的同名函数实现相同,但仅在 `scheduler.is_tail_session()` 为真时调用(尾盘交易时段),不会拿到收盘后的时间,故不在本次修改范围。

---

## 修复结果(2026-07-09)

**代码改动**(`src/data/clickhouse_minute5_sync.py`):

- **#1**:`_check_tail_coverage` 内层 SELECT 改用 `arrayJoin([{codes}]) AS symbol`,真正生成"每个 code 一行";返回值改为带后缀的 symbol(原先返回 code,会导致 `_sync_tail_bars` 拿 code 去调 `fetch_intraday_bars` 出错)。
- **#2**:尾同步路径新增 `middle_gap_symbols` 检测(`symbols_to_fetch` 中"需刷新但尾部齐全"的标的)。存在时不再走尾同步,而是 fall through 到全量同步路径回补中间缺口。
- **#3**:缓存只标记 `set(target_symbols) - set(symbols_to_fetch)`(本轮已确认完整的标的)。新补的尾部标的留待下一轮 `_needs_refresh` 确认完整后再缓存,避免把中间缺口标的误存进缓存。

**测试改动**(`tests/test_data/test_clickhouse_minute5_sync.py`):

- 新增 autouse fixture,每个测试前后清理模块级 `_complete_symbols_cache` / `_cache_timestamps`。这同时修复了 commit `316b7fc0` 引入的**测试间缓存泄漏** -- 此前整文件跑会有 12 个用例因缓存污染失败(单跑通过)。
- FakeClickHouseClient 新增 `arrayJoin` 查询分支,按 `existing_by_symbol` 模拟尾桶缺失。
- 新增 5 个用例:
  - `test_check_tail_coverage_returns_all_missing_tail_symbols` -- 直接验证 SQL 修复(多 code 都被检出)。
  - `test_tail_sync_fills_missing_tail_bucket_and_caches_only_complete` -- 尾同步补尾桶 + 缓存只含已完整标的(缺尾标的置于末位,旧 SQL 会漏掉)。
  - `test_tail_sync_marks_all_complete_when_nothing_needs_refresh` -- 全完整走 `tail_all_complete` 并填缓存。
  - `test_tail_sync_falls_back_to_full_sync_for_middle_gap` -- 中间缺口标的 fallback 到全量同步并回补。
  - `test_completed_5m_bar_time_caps_at_market_close` -- 收盘后 `target_dt` 封顶 15:00(新发现 A)。

**验证**:`tests/test_data/test_clickhouse_minute5_sync.py` 22 passed(17 原有 + 5 新增);`tests/test_data tests/test_scripts tests/test_core` 共 200 passed。

> 注:`tests/test_web/*`、`tests/test_ml/*` 在当前最小 dev venv 下因缺 `sklearn` 等依赖无法收集(`uv sync` 此前被中断),属既存环境问题,与本次改动无关。

---

## 下列为原始审计发现(保留备查)

---

## 问题 1:`_check_tail_coverage` 的 SQL 生成错误 🔴

- [ ] 确认

**位置**:`src/data/clickhouse_minute5_sync.py:832`(函数 `_check_tail_coverage`,起于 `:802`)

**现象**:构造期望标的集合的这行——

```python
FROM (SELECT {', '.join(f'{repr(c)} AS symbol' for c in codes)}) e
```

对 `codes = ['000001','600519','000858']` 实际生成的内层 SQL 是:

```sql
SELECT '000001' AS symbol, '600519' AS symbol, '000858' AS symbol
```

这是 **1 行、3 列,且三列都叫 `symbol`**,不是预期的"3 行、每行一个 symbol"。外层 `SELECT e.symbol FROM (...) e` 引用 `e.symbol` 时列名歧义,ClickHouse 要么报错,要么只取到第一个列。无论哪种,**多标的场景下只有第一只 code 会被真正检查**,其余被当成"不缺尾"。

**触发条件**:尾同步路径触发(`use_tail_sync=True` 且 `symbols_to_fetch < target_symbols * 0.3`),且 `symbols_to_fetch` 里有多于 1 只标的时。

**后果**:P2.2 尾部增量同步在多标的时基本失效——大部分缺尾标的不会被检出、不会被同步,却被当成"尾部齐全"。

**如何确认**(可直接跑,只读、不碰任何表):

```bash
uv run python -c "
codes = ['000001','600519','000858']
print('SELECT ' + ', '.join(repr(c) + ' AS symbol' for c in codes))
"
# 输出: SELECT '000001' AS symbol, '600519' AS symbol, '000858' AS symbol
```

再到 ClickHouse 跑(纯字面量,无表):

```sql
SELECT e.symbol FROM (SELECT '000001' AS symbol, '600519' AS symbol, '000858' AS symbol) e;
-- 预期:报 "Ambiguous column symbol" 或只返回 '000001' 一行
```

正确写法应是 `SELECT arrayJoin([...]) AS symbol` 或 `UNION ALL`。

---

## 问题 2:中间桶缺失未 fallback 到全量同步 🟠

- [ ] 确认

**位置**:`src/data/clickhouse_minute5_sync.py:93-143`(尾同步路径)

**现象**:计划 Phase 3.2 明确要求:

> 处理边界情况 — 中间桶缺失(如 11:20)-> fallback 到全量同步

代码里 `gap_codes`(定义于 `:77` / `:90`)只记录"latest 已到 target_dt 但 bar 数不足"的标的,且**只在全量同步路径 `:206` 被使用**。尾同步路径(`:93-143`)命中后直接 `return`,从不读取 `gap_codes`,也不检测中间桶缺失。

**触发条件**:尾同步触发,某只标的只缺中间一两个桶(如 11:20),但 14:50/14:55/15:00 尾部齐全。

**后果**:这只标的的中间缺口被静默忽略,永远不会被回补(还会被问题 3 进一步"缓存冻结")。计划要求的边界处理缺失。

**如何确认**:`grep -n "gap_codes" src/data/clickhouse_minute5_sync.py` 应只见 `:77`、`:90`、`:206` 三处,均在 `:143` 的 return 之后或之外。

---

## 问题 3:缓存"已完整"判定过宽 🔴

- [ ] 确认

**位置**:`src/data/clickhouse_minute5_sync.py:107` 和 `:128`

**现象**:
- `:107`(`if missing_tail:` 分支内):

  ```python
  newly_complete = set(target_symbols) - set(missing_tail)
  ```

- `:128`(`else`,即无任何缺尾标的时):

  ```python
  _update_complete_symbols_cache(trade_date, set(target_symbols))
  ```

两处都把"有尾部桶"等同于"已完整"。但 `target_symbols` 里包含**进入 `symbols_to_fetch`、需要刷新的标的**(`_needs_refresh` 在 `:469` 判定 `count < expected_bars` 即为 True,中间缺桶的标的正属此类)。

**触发条件**:尾同步触发,且 `symbols_to_fetch` 里存在"尾部齐全但中间有缺口"或"当天尚未同步过"的标的。

**后果**:这些标的被写进 `_complete_symbols_cache`,TTL 24 小时内不再复查——中间缺口被永久固化(到次日才可能重新检查)。和问题 2 叠加,缺口修复彻底失效。

**如何确认**:在 `:106-109` 与 `:126-128` 处,确认 `newly_complete` / cache 写入的集合来源是 `target_symbols`(全量目标)而非 `symbols_to_fetch` 中真正补齐的子集。

---

## 问题 4:tail-sync / cache 零测试覆盖 🟠

- [ ] 确认

**位置**:`tests/test_data/test_clickhouse_minute5_sync.py`

**现象**:计划 Phase 3.1/3.2/3.3 均要求"添加单元测试 / 集成测试"。实测:

```bash
grep -rln "tail_sync\|_check_tail_coverage\|_sync_tail_bars\|complete_symbols_cache\|use_tail_sync" tests/ scripts/
# 0 命中
```

`test_clickhouse_minute5_sync.py` 里没有任何针对新增缓存过滤、尾同步触发条件、`_check_tail_coverage`、`_sync_tail_bars` 的 case。

**后果**:问题 1/2/3 没有任何护栏;后续回归无法被测试捕获。也意味着上面几条问题的"是否影响线上"目前无自动验证。

**如何确认**:上面的 grep 命令在 `tests/`、`scripts/` 下应返回空。

---

## 问题 5:验收标准无验证记录 🟡

- [ ] 确认

**位置**:计划文档「验收标准」表

**现象**:验收表给出 4 条指标,均需实跑确认,但 commit message(`1f329c61`、`316b7fc0`)与工作区均无验证记录:

| 优化项 | 验收指标 | 状态 |
|---|---|---|
| P0 新浪 amount | 历史数据 amount 零值率 < 5% | ❓ 未验证 |
| P1 并发 | 全量同步 < 35s | ❓ 未验证 |
| P2 标的过滤 | 二次同步 < 25s | ❓ 未验证 |
| P2 尾部同步 | 盘中同步 < 10s | ❓ 未验证 |

**后果**:无法确认优化是否真的达标;且因为问题 1,P2.2 的"盘中同步 < 10s"很可能名不副实(尾同步实际没同步到该补的标的)。

**如何确认**:逐条跑计划里给的验证命令,记录耗时与零值率。

---

## 审计结论

- 代码层面 P0/P1/P2/P3 均"已实现",但 P2.2(尾同步)因问题 1/2/3 在多标的 / 中间缺口场景下基本不可用。
- 问题 4 导致上述正确性问题无任何自动护栏。
- 建议修复顺序:1 → 3 → 2 → 4 → 5(先修 SQL 让尾同步可用,再收紧缓存判定,补中间桶 fallback,然后补测试,最后跑验收)。
