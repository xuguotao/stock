# 2026-06-25 数据与代码复查

> **范围**：① ClickHouse 运行时数据质量复查；② `daee015..HEAD`（5 个提交：tail ML 样本构建/审计、tail signal 待审日期修复、ClickHouse 默认回测源）的代码审查。
> **方法**：① 实连 ClickHouse 两轮 SQL drill-down + 对照 `data_status.py` 监控代码；② 7 finder 角度（行扫/删行审计/跨文件追踪/复用/简化/效率/海拔）并行 + 直接读真实源码验证。全程只读，未改代码。
> **前序**：`docs/superpowers/plans/2026-06-23-data-quality-hardening.md`（Task 1-4 已完成、Task 5 部分、Task 6 推迟）。
> **数据为 06-25 快照**，后续可能已变动，复核以库内实测为准。

---

## 第一部分：数据质量复查（运行时状态）

### 修复已达成（实测确认）

| 项 | 验证结果 |
|---|---|
| daily 重复清理 | ✅ 25,965 组 / 46,736 额外行 → **0 / 0**，每天倍数恢复 ×1.0（6-20 起稳定 1.0） |
| daily 重复检测 | ✅ 接入 `_clickhouse_quality`，issue key `daily_kline_duplicate_{n}_extra_rows`（`data_status.py:674`） |
| daily 去重工具 | ✅ `deduplicate_daily_kline` 建表+rename，安全可回滚（`clickhouse_table_maintenance.py:126`） |
| 历史无效价检查 | ✅ `_daily_historical_invalid_price_check` 检测 OHLC≤0，带样本（`data_status.py:~1010`） |
| quote_5m 读 FINAL | ✅ raw 额外行读时去重（FINAL 计数 826157 vs raw 915736） |
| 30d 完整性降级 | ✅ `completeness_30d` 对退市股（退市太和/退市沪科/退市创兴）降为 `ignored`，SQL 改为只统计最新日有成交的股票，合理非掩盖 |
| 数据更新正常 | ✅ daily→6-24、minute5→6-25 11:30、quote→6-25 11:29、health 521 行最新 6-24 22:55 |

### 待修复问题

#### 🔴 P0 — daily 并发锁是假修复（回归风险最高）

`sync_clickhouse_daily_from_minute5` 的跨进程锁 `_acquire_daily_repair_marker`（`clickhouse_daily_sync.py:118`）有 bug：

```python
rows = client.execute("insert into daily_kline_repair_locks select ... where not exists (...)")
if rows and len(rows[0]) == 1:   # 永远 False
    return int(rows[0][0] or 0) > 0
return True                         # ← 永远走这里
```

**根因（已实连库坐实）**：`clickhouse-driver` 对 `INSERT...SELECT` 返回 `[]`（无论插 0 行还是 N 行），只有 `INSERT...VALUES` 返回行数：

```
insert...select 0 rows -> []
insert...select 1 row  -> []
insert values          -> 1
```

所以 `rows=[]` → `if rows and ...` 永远 False → **永远返回 True**，跨进程互斥完全失效。

- 进程内 `threading.Lock` 有效（挡同进程并发），但 P0 真正的并发源是**跨进程**（web scheduler 线程 + 手动 `run_daily_maintenance.py`），那个没被挡住。
- daily_kline 是 `MergeTree`（不自动去重），所以一旦再并发，重复会重新累积，只能靠手动 `deduplicate_daily_kline` 兜底。
- **当前重复为 0 是因为没并发，不是因为锁有效。**
- **测试盲区**：`FakeClickHouseClient` 把该 INSERT 返回值硬编码成 `[(1,)]`（`test_clickhouse_daily_sync.py:24`），模拟的是"期望行为"而非真实 driver 行为 → 测试绿但实际不防并发。

**修法建议（三选一）**：
1. 改用 `SELECT count() WHERE trade_date=X` 判 marker 是否已存在再 insert（仍有竞态窗口，但比 always-True 强）；
2. 用 OS 文件锁 `fcntl.flock`（同机进程互斥，进程崩溃自动释放，最可靠）；
3. 落实 plan Task 6「web/system scheduler 二选一不并发」——从源头消除并发。

同步把 fake 测试改成返回 `[]` 以反映真实 driver，否则修了也测不出。

#### 🟠 P1 — flaky 测试持续失败（已跨 2 次复查）

`tests/test_web/test_data_status_api.py::test_daily_maintenance_prefers_latest_minute5_date_when_daily_is_stale` 硬编码 `2026-06-22`，但测试解析出的最新日期已飘到 6-24 → **持续失败**（pytest 永红，CI 信号失真）。非逻辑 bug，应改成相对当前交易日断言。

#### 🟡 P2 — 残留项（低风险但占空间/欠债）

| 项 | 现状 |
|---|---|
| 3 个 backup 表 | `daily_kline_backup_20260623_fix`（729 万）+ `minute5_kline_backup_20260617_manual`（2480 万）+ `minute5_kline_backup_20260621_fix`（2503 万）≈ **5700 万行未清** |
| close≤0 脏数据 | 1203 行 / 14 符号（2020-01-02 ~ 2022-04-27）未重导入；ML 已用 SQL 过滤规避，但长周期回测仍受影响 |
| quote_5m raw 重复 | 靠读时 `FINAL` 兜底；**rollup 重复统计仍未加**（plan Task 5 未勾）→ 监控看不到未合并版本 |
| 调度系统兜底 | 仍依赖 web 进程内线程；web/手动脚本并发是 P0 根因（plan Task 6 推迟未做） |
| 密码硬编码 | `host/password` 仍 4+ 处硬编码，`.env.example` 仍未补 `STOCK_CLICKHOUSE_*`，`from_env()` 支持却未默认使用 |

---

## 第二部分：代码复查（`daee015..HEAD`）

### 审查方法

对 2070 行 diff 跑了 7 个独立 finder 角度（行扫 / 删行审计 / 跨文件追踪 / 复用 / 简化 / 效率 / 海拔），每个产出 ≤6 候选；去重后对关键候选**直接读真实源码逐条验证**（非仅凭 finder 输出）。以下 10 条均经源码确认。审查全程只读。

### 发现（按严重度排序）

#### 1. 🔴 `joinable_label_days` 自连接语义错误 + 性能（`tail_dataset_audit.py:207`）

`_tail_outcome_summary` 的 `joinable_label_days` 查询：

```sql
select count() from (
    select d1.date signal_date, count() c
    from daily_kline d1
    inner join daily_kline d2 on d1.symbol = d2.symbol and d2.date > d1.date
    where d1.date >= '2026-01-08' and d1.date <= today() - 1
    group by d1.date having c > 100000
)
```

统计的是「该 signal_date 的未来 bar 对数」，而非「是否有下一交易日可建标签」。每个交易日的未来对数 ≈ 5000 符号 × ~140 天 ≈ 70 万，**全部 >10 万** → 返回 ~全部交易日数，不是真实可建标签日数。

- **后果**：`labels["status"]`（`ready` if `joinable_days >= 120` else `limited`）据此判定 ML 训练就绪状态，会误报。
- **性能**：7M 行 `daily_kline` 自连接，耗时长，且经 audit 端点跑在请求线程（见 #2）。
- 另 `d1.date >= '2026-01-08'` 硬编码，未从 `minute5_kline` 实际 `min(datetime)` 推导，历史扩展后会失真。

#### 2. 🔴 audit 端点无 try/except + DataCenter 用 Promise.all（`app.py:774` / `DataCenter.vue:943`）

`get_tail_ml_audit` 端点直接 `return app.state.tail_ml_audit_runner()`，无 try/except，跑 ~9 条 ClickHouse 查询（含 #1 的重自连接）。`DataCenter.vue:943` 用 `Promise.all`（非 `allSettled`）：

```js
const [...] = await Promise.all([..., api.getTailMlAudit()])
```

- **后果**：audit 任一查询失败（ClickHouse 不可达、`stock_quote_snapshots` 表在新环境缺失、或自连接超时）→ 端点 500 → `Promise.all` reject → `catch` 只 `ElMessage.error`，**5 个 ref 全部不赋值 → 整个数据中心页面空白**，连本应成功的可靠性/监控数据都不显示。
- 应将 audit 调用独立 try/catch，或前端用 `Promise.allSettled`。

#### 3. 🔴 `_load_clickhouse_bars` 无 OHLC 校验（`backtests.py:131`）

从 `daily_kline` 取 OHLC 时**无 `open>0...volume>0` 过滤**，随后 `fillna(0.0)`：

```python
select symbol, date, open, high, low, close, volume, amount from daily_kline
where symbol in %(symbols)s and date >= %(start)s and date <= %(end)s
...
for column in [...]: df[column] = pd.to_numeric(..., errors="coerce").fillna(0.0)
```

对比：ML loader（`tail_dataset.py:106`）同表却过滤了 `open>0 and high>0 and low>0 and close>0 and volume>0`。

- **后果**：回测默认走 ClickHouse 路径，加载 `close<=0` 的脏行（实测仍有 1203 行无效 OHLC）→ fillna 为 0 → 污染 `TailSessionFactor` 的 `rolling(20)` 突破阈值/MA20，以及 `OvernightMomentumFactor` 的 gap（`prev_close=0` → NaN 静默丢该符号）。
- 另 `drop_duplicates(["date","symbol"])` 因 SQL 只 `order by date, symbol`，重复时保留行不确定 → 不可复现。

#### 4. 🟠 标签 `_return` falsy-value bug（`tail_labels.py:62`）

```python
# tail_labels.py:62 — `if base and value`：value=0 时返回 0.0
def _return(value, base): return float(value)/float(base) - 1.0 if base and value else 0.0
# tail_features.py:117 — `if base`：仅 base 为假时返回 0.0
def _return(value, base): return value / base - 1.0 if base else 0.0
```

两份同名 helper 语义不一致。且 `tail_dataset.py:51` 的 `null_label_rows` 只检查 `outcome_date.isna()`。

- **后果**：若下一交易日 OHLC 为 0（脏数据/停牌填充）滑过过滤，标签收益被记为 0.0、`hit_next_high_1pct=False`，而 `outcome_date` 非空 → 不被 null 检查拦截 → 写入 parquet 当作有效训练样本，污染模型。
- 当前 ML loader 过滤了 0 故为潜在风险，但两份 `_return` 语义分歧是确定隐患。应统一并只校验 `base`。

#### 5. 🟠 ST 过滤大小写不一致 + 未复用 `is_st`（`backtests.py:176`）

`_clickhouse_symbols` 用 `positionUTF8(coalesce(s.name,''),'ST')=0`（未大写、子串匹配）；audit 的 `tradable_pool`（`tail_dataset_audit.py:37`）同样未大写；但 audit 的 `_stock_summary`（`:100`）用 `upper(name)`。**同一文件内部口径就不一致**。canonical 的 `src/core/constants.py:73 is_st()` 存在却未被复用。

- **后果**：名字含小写 `st` 的股票被误判 ST 排除；若 ST 标记以非大写存储则漏排除进入回测宇宙（ST 股 5% 涨跌停，回测口径失真）。回测宇宙、审计计数、实盘 `is_st` 三者不同步。

#### 6. 🟠 tradable-pool SQL 三处重复 + 阈值不一（`backtests.py:160`）

策略可交易池 SQL 在 `backtests._clickhouse_symbols`、`tail_dataset_audit.tradable_pool`、`tail_live` 各写一份，且阈值不同：**backtest `bars>=30` vs audit `bars>=120`**。

- **后果**：审计页报告「策略可交易池 4936」（120-bar 定义），同时段回测实际用 30-bar 宇宙——回测交易的票比审计承诺的更宽。ML 就绪门槛按 120-bar 池判，但训练样本来自 30-bar 池，口径分裂。应抽单一 `strategy_tradable_symbols(start, end, min_bars)` helper。

#### 7. 🟠 ML 特征构造 O(n·m) 全帧 mask（`tail_features.py:28`）

`build_tail_feature_frame` 在 `groupby(symbol, trade_date)` 循环内对每组做 `daily[(daily.symbol==symbol)&(daily.date<trade_date)].sort_values("date")` 全帧布尔 mask + 重排，且 `_daily_features` 每组重算 `rolling-20`。

- **后果**：7.2M daily 行 × ~45 万组 → 每组重扫全表，O(n·m)。全市场 5 个月重建耗时分钟级 + 大量临时对象，阻碍迭代训练。
- 应按 symbol `groupby` 一次 + `searchsorted`/`asof` 取窗口 + `rolling(20)` 预算一次。

#### 8. 🟡 ML 标签逐行 `apply` ×4（`tail_labels.py:36`）

4 列收益用 `labels.apply(lambda row: _return(row["next_X"], row["entry_price"]), axis=1)` 逐行 Python 计算，跑 4 遍。

- **后果**：45 万特征行 → ~180 万次 Python lambda 调用 + 4 次全帧遍历。向量化（`next_X/entry_price - 1`，零值用 `where` 守卫）一次 numpy 完成同 4 列，差几个数量级。

#### 9. 🟡 `_load_clickhouse_bars` 重写已有 loader（`backtests.py:126`）

近乎逐行重写了 `clickhouse_research_dataset._dataset_frame`/`_daily_rows`（同查询、同 `format_symbol`、同 numeric 强制、同 `adjusted_close=close`）；`tail_dataset._code`/`_bars_dataframe` 也重复 `clickhouse_source._code`。

- **后果**：ClickHouse daily-bar 归一化逻辑现在 2~4 份各自漂移。修一处（如 `volume` 强制 int、加复权）不会同步到其他，回测与持久化 research dataset 口径静默不一致。应复用 `build_clickhouse_research_dataset` / `load_research_dataset`。

#### 10. 🟡 尾盘时段硬编码三处（`tail_dataset.py:127`）

`_load_minute5_bars` SQL 硬编码 `toHour(datetime)=14 and toMinute(datetime)>=30`；`tail_features.py` 又硬编码 `"14:30"` 字符串作 `first_tail_close` 基准，且 `DEFAULT_DECISION_TIMES=[14:30..14:55]`。

- **后果**：尾盘时段是第三处独立编码（另两处：`config/trading_rules.yaml` `afternoon.close`、`scheduler.is_tail_session`）。尾盘开始时间若变动需改三处易漏。且 `"14:30"` 基准假定 `tail_bars.iloc[0]` 恰为 14:30 bar，SQL 放宽后基准错位、`tail_return_from_1430` 静默偏移，下游模型继承错特征。应从 `trading_rules`/scheduler 统一推导。

---

## 第三部分：优先级汇总

| 优先级 | 项 | 来源 |
|---|---|---|
| 🔴 P0 | 修 daily 并发锁（marker 判定或 `fcntl.flock`）+ 同步修 fake 测试 | 数据复查 |
| 🔴 P0 | `joinable_label_days` 自连接语义错（#1） | 代码复查 |
| 🔴 P0 | audit 端点 try/except + DataCenter 改 `allSettled`（#2） | 代码复查 |
| 🔴 P0 | `_load_clickhouse_bars` 加 OHLC 校验 + 确定性去重（#3） | 代码复查 |
| 🟠 P1 | 修 flaky 测试（相对交易日断言） | 数据复查 |
| 🟠 P1 | 统一 `_return` 语义 + null 校验扩到全部标签列（#4） | 代码复查 |
| 🟠 P1 | ST 过滤复用 `is_st`（#5）；tradable-pool 抽单一 helper（#6） | 代码复查 |
| 🟡 P2 | 清 3 个 backup 表（5700 万行） | 数据复查 |
| 🟡 P2 | ML 特征 O(n·m) 与标签向量化（#7 #8） | 代码复查 |
| 🟡 P2 | 复用已有 loader（#9）；尾盘时段统一编码（#10） | 代码复查 |
| 🟡 P2 | 重导入 14 符号历史脏数据；补 rollup 重复统计；密码收敛 `from_env()` | 数据复查 |

## 总结

数据底座在 `daee015` 这一轮巩固后已相当健康（重复归零、检测齐全、新增 ML 防泄漏设计专业）。两个层面的风险尚未闭合：

1. **数据层面**：P0 并发锁是假修复——测试通过但实际不防跨进程并发，daily 重复会随 web/手动脚本并发卷土重来。
2. **代码层面**：`daee015..HEAD` 这批新增里，audit 端点的脆弱查询被挂进 DataCenter 的 `Promise.all`（#2）、回测默认路径不过滤脏 OHLC（#3）、`joinable_label_days` 指标语义错（#1）三处会让结果静默失真或拖垮页面，应优先处理。

两类问题不重叠：数据复查看运行时状态与历史欠债，代码复查看这批 diff 的静态缺陷。

---

## 第四部分：第一轮修复复核（`ecfe492` 等，2026-06-25）

> 程序维护 AI 按本 review 做了一轮修复（`ecfe492 Harden data quality review findings` + `17473bb`/`2ee2a88`/`877f535`/`3601546` 韧性相关）。复核方法：读 `ecfe492` 全 diff + 跑全套测试（492 passed）+ 实连 ClickHouse 验证。全程只读。本节给维护 AI 快速定位：哪些已修、哪些仍欠、新引入了什么。

### 已修复（确认正确，测试全绿）

| 发现 | 复核结果 |
|---|---|
| **P0 daily 并发锁** | ✅ 加 `fcntl.flock` 文件锁（`clickhouse_daily_sync.py:127`）——正是本 review 建议方案。`LOCK_NB` 非阻塞 + `BlockingIOError` 返回 None 跳过，finally 正确释放。实连库确认 marker 表为空、daily 重复仍 0、daily 更新到 6-25 |
| **#1 joinable_label_days 语义** | ✅ 改用 `leadInFrame` 窗口函数取下一交易日 bar + `having c>=4500`，语义正确；硬编码 `'2026-01-08'` 换成 `(select toDate(min(datetime)) from minute5_kline)`；顺带过滤脏 OHLC |
| **#2 audit 端点 + DataCenter** | ✅ 端点加 try/except 返回 degraded payload（`status=blocked` + `tail_ml_audit_failed`）；DataCenter 改 `Promise.allSettled`，audit 失败只置 `tailMlAudit.value=null`，不再全页空白 |
| **#3 _load_clickhouse_bars 脏数据** | ✅ SQL 加 `open>0...volume>0` + 二次 DataFrame 过滤 + `.copy()`，双重保险 |
| **P1 flaky 测试** | ✅ 492 passed，不再红 |

### 仍未修复（待下一轮处理）

#### 🟠 #1 修复引入副作用：`joinable_label_days` 永远 `limited`

修复 #1 时引入的新问题。实连库实测：
- `joinable_days = 109`，而 `MIN_JOINABLE_LABEL_DAYS = 120` → `labels["status"] = "limited"`，issue `joinable_label_days_limited_109`。
- 但这 109 天**就是该窗口内全部有效交易日数**（`total=109`）。即"可建标签日"受限于历史数据本身长度（minute5 从 1-8 起，到今天 ~109 个交易日），不是数据质量问题。
- 每交易日的 joinable 符号数都 ≥4965，阈值 4500 过得轻松——真正卡的是总天数 < 120，而非符号覆盖不足。
- 报成 `limited` + issue 会让"ML 训练就绪"判断失真（实为"历史还不够长"）。

**建议**：区分两种"不足"——符号覆盖不足（数据质量，报 `limited`）vs 历史天数不足（数据积累，报 `pending_history` 或不算 issue）。

#### 🟠 #4 — `_return` 两处语义仍不一致

```python
tail_features.py:118  if base              # value=0 -> -1.0
tail_labels.py:63     if base and value    # value=0 -> 0.0
```

仍是分歧状态，`null_label_rows`（`tail_dataset.py:51`）仍只检查 `outcome_date.isna()`，未扩到全部标签列。当前 ML loader 过滤了 0 故为潜在风险，但两份语义分歧的根因未动。应统一为 `if base` 并把 null 校验扩到所有标签列。

#### 🟠 #5 — ST 过滤仍大小写不一致 + 未复用 `is_st`

```
backtests.py:184      positionUTF8(coalesce(s.name,''),'ST')=0     # 未大写
audit:37              positionUTF8(coalesce(s.name,''),'ST')=0     # 未大写
audit:100             positionUTF8(upper(name),'ST')               # 大写 ← 同文件内矛盾
```

`src/core/constants.py:73 is_st()` 仍未被复用。三处口径仍不同步；子串匹配还会误判名字含小写 `st` 的正常股。应统一复用 `is_st` 语义。

#### 🟠 #6 — tradable pool SQL 仍三处重复 + 阈值不一

```
backtests.py:186          having bars >= 30
audit:39                  having bars >= 120
clickhouse_source.py:281  having bars >= %(min_bars)s   # 参数化，正确
```

backtest（30）与 audit（120）阈值不一致未动——回测交易的宇宙仍比 audit 承诺的宽。应抽单一 `strategy_tradable_symbols(start, end, min_bars)` helper 统一三处。

#### 🟡 #7 #8 #9 #10 + P2 残留 — 均未动

- **#7** ML 特征 `tail_features.py:28` 仍 O(n·m) 全帧 mask + 每组重算 rolling-20；
- **#8** `tail_labels.py:36` 仍逐行 `apply(lambda)` ×4；
- **#9** `_load_clickhouse_bars`（`backtests.py:126`）仍重写 `clickhouse_research_dataset._dataset_frame`，未复用；
- **#10** `tail_dataset.py:127` 尾盘时段仍 SQL/字符串/常量三处硬编码，未从 `trading_rules`/`scheduler` 统一推导；
- **3 个 backup 表** 仍 5700 万行未清（`daily_kline_backup_20260623_fix` + 2 个 minute5 backup）；
- **close≤0 脏数据** 1159 行/13 符号未重导入（#3 过滤让回测规避，但库内仍在，长周期回测受影响）。

### 复核后优先级（给维护 AI）

| 优先级 | 待办 | 位置 |
|---|---|---|
| 🟠 P1 | `joinable_label_days` 区分"符号不足"vs"历史天数不足"，避免永远 `limited`（#1 副作用） | `tail_dataset_audit.py:203-217` |
| 🟠 P1 | 统一 `_return` 语义为 `if base` + null 校验扩到全部标签列（#4） | `tail_labels.py:62`、`tail_features.py:117`、`tail_dataset.py:51` |
| 🟠 P1 | ST 过滤复用 `is_st`，消除大小写/子串匹配分歧（#5） | `backtests.py:184`、`tail_dataset_audit.py:37/100` |
| 🟠 P1 | tradable pool 抽单一 helper，统一 backtest/audit 阈值（#6） | `backtests.py:160`、`tail_dataset_audit.py:30-41` |
| 🟡 P2 | 清 3 个 backup 表（5700 万行）；重导入 1159 行历史脏数据 | ClickHouse 库 |
| 🟡 P2 | ML 特征/标签向量化（#7 #8）；复用已有 loader（#9）；尾盘时段统一编码（#10） | `src/ml/`、`backtests.py` |

### 复核结论

这轮修复**质量很高**——4 条 🔴（并发锁、joinable 语义、audit 韧性、回测脏数据）+ P1 flaky 测试全修对，测试 492 全绿。`fcntl.flock` 实现教科书式正确。遗漏集中在 4 条 🟠（#4 #5 #6 + #1 副作用），均为"多份拷贝语义分歧/不同步"同构问题——恰是当初 daily 重复事故的同类根因，建议下一轮一并收敛。
