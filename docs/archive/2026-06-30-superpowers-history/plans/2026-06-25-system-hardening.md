# 2026-06-25 系统稳固化优化计划

> 目标：把当前后台量化系统从“功能快速迭代态”推进到“数据口径统一、自动任务可靠、页面可解释、策略训练可复现”的状态。
> 输入：`docs/superpowers/reviews/2026-06-25-full-system-code-review.md` 与 `docs/superpowers/reviews/2026-06-25-data-and-code-review.md`。

## Phase 1：统一数据口径

### Task 1.1 建立策略可交易池唯一入口

目标：所有策略、回测、ML 审计、数据中心都使用同一股票池定义。

实施：

1. 新增 `src/data/strategy_universe.py`。
2. 提供 `StrategyUniverseOptions`：
   - `trade_date`
   - `min_daily_bars`
   - `require_latest_daily`
   - `require_minute5`
   - `include_st`
   - `min_amount`
   - `markets`
3. 提供 `resolve_strategy_universe(client, options)`。
4. 替换以下调用点：
   - `src/web/backend/backtests.py`
   - `src/ml/tail_dataset_audit.py`
   - `src/web/backend/data_status.py`
   - `src/web/backend/tail_live.py`
5. 增加契约测试：同一 fixture 下四个模块返回相同 universe。

验收：

- 数据中心“策略可交易池”与今日尾盘选股扫描池一致。
- 回测页面、策略复盘、ML audit 不再各写一份股票池 SQL。

### Task 1.2 统一 ST/退市/异常股票判断

目标：消除 `positionUTF8(..., 'ST')` 与 `is_st()` 并存问题。

实施：

1. 所有 Python 侧最终过滤统一调用 `src.core.constants.is_st`。
2. ClickHouse SQL 只做粗过滤或读取候选，最终由 Python helper 判定。
3. 在数据中心展示“剔除原因”时区分：
   - ST
   - 退市/停牌长期无成交
   - 日线不足
   - 分钟线不足

验收：

- `rg "positionUTF8\\(coalesce\\(.*ST"` 不再命中业务股票池代码。
- 测试覆盖大小写 ST、退市名称、正常名称包含 `st` 子串等边界。

## Phase 2：ClickHouse 配置收敛

### Task 2.1 配置中心化

目标：源码不再散落真实 ClickHouse host/password。

实施：

1. 在 `config/settings.py` 增加 `ClickHouseSettings`。
2. `ClickHouseStockDataSource` 默认从 settings/env 初始化。
3. 各同步脚本 argparse 默认值读取 settings。
4. 更新 `.env.example`。

验收：

- `rg "10\\.211\\.49\\.42|stock123" src scripts config` 只允许在测试 fixture 或文档示例中出现。
- 单元测试通过 monkeypatch env 覆盖连接配置。

## Phase 3：数据同步任务骨架统一

### Task 3.1 统一 1m/5m/快照同步返回结构

目标：让数据中心可以用同一套 UI 展示任务健康度。

实施：

1. 定义同步结果 schema：
   - `status`
   - `target_count`
   - `fetched_count`
   - `inserted_count`
   - `skipped_count`
   - `latest_time`
   - `coverage_after`
   - `timings`
   - `warnings`
2. 适配：
   - `sync_clickhouse_minute5_kline`
   - `sync_clickhouse_minute1_kline`
   - `sync_clickhouse_quote_snapshots`
3. DataCenter 只依赖统一 schema 渲染。

验收：

- 三类任务在任务中心和数据中心展示字段一致。
- 任务失败时能显示阶段、失败批次、耗时、最近成功时间。

### Task 3.2 抽取 intraday 同步公共流程

目标：减少 1m/5m 代码重复。

实施：

1. 抽取公共流程：
   - resolve symbols
   - resolve target date/time
   - fetch batch
   - normalize frame
   - insert rows
   - compute coverage
2. 1m/5m 只保留 endpoint/source/table 差异。

验收：

- 1m/5m 同步测试共享同一组行为测试。
- 后续调整 chunk、重试、超时只改一处。

## Phase 4：后台任务可靠性

### Task 4.1 JobStore 增加 heartbeat 与 attempt

目标：用户能判断任务是正常执行、卡住还是失败重试。

实施：

1. jobs 表增加或兼容字段：
   - `attempt`
   - `heartbeat_at`
   - `started_at`
   - `finished_at`
   - `lease_owner`
2. 所有长任务定期写 heartbeat。
3. `/api/jobs` 返回健康状态：`running`、`stale`、`failed`、`completed`。

验收：

- 页面不再只显示 running；超过阈值无 heartbeat 时显示 stale。
- 服务重启后可准确标记上次中断原因。

### Task 4.2 自动任务和手动任务走同一入口

目标：避免 web 自动线程、手动按钮、脚本并发操作同一数据。

实施：

1. 将 `DataOpsScheduler`、`Minute5UpdateMonitor`、`QuoteSnapshotMonitor` 的执行动作改为提交标准 Job。
2. 对同类任务加互斥 key，例如 `minute5_sync:trade_date`。
3. 手动按钮如果已有同类任务运行，返回已有 job id。

验收：

- 同一时间不会启动两个全市场 5m 同步。
- 数据中心能看到自动触发和手动触发的统一任务记录。

## Phase 5：今日尾盘选股可信度重构

### Task 5.1 拆分规则分与历史校准

目标：避免把规则评分误解为胜率概率。

实施：

1. 新增 `src/strategy/tail_session/credibility.py`。
2. 输出字段：
   - `rule_score`
   - `rule_grade`
   - `historical_hit_rate`
   - `historical_avg_return`
   - `sample_size`
   - `calibrated_probability`
   - `risk_flags`
3. 样本不足时明确显示 `sample_size` 和 `history_status=pending`。

验收：

- 页面不再只显示一个“可信度 87”。
- 用户能看到该分数来自规则质量还是历史复盘。

### Task 5.2 将策略复盘结果反哺今日选股

目标：今日建议能引用历史相似样本表现。

实施：

1. 复盘时按 `rule_score_bucket`、`market_regime`、`volume_ratio_bucket`、`tail_gain_bucket` 统计表现。
2. 今日选股匹配最近样本分桶。
3. 页面展示：
   - 相似样本数量
   - 次日开盘胜率
   - 次日最高达到 1%/2% 概率
   - 平均最大回撤

验收：

- 每只最终选股都有“为什么推荐”和“历史类似表现”。
- 没有足够样本时明确提示，不给伪概率。

## Phase 6：前端拆分与契约测试

### Task 6.1 拆分核心大页面

目标：降低单页组件复杂度，避免继续堆逻辑。

实施：

1. `DataCenter.vue` 拆为：
   - `DataSourceOverview.vue`
   - `PipelineHealthPanel.vue`
   - `DataQualityPanel.vue`
   - `ManualOpsPanel.vue`
2. `TailLiveSelection.vue` 拆为：
   - `TailRunForm.vue`
   - `TailDataHealth.vue`
   - `TailRankedTable.vue`
   - `TailSelectionTable.vue`
   - `TailRunHistory.vue`
3. `FundTail.vue` 拆为：
   - `FundPoolTable.vue`
   - `FundDataHealth.vue`
   - `FundAdvicePanel.vue`

验收：

- 单个 Vue 文件尽量低于 500 行。
- 页面功能不回退，build 通过。

### Task 6.2 引入最小 UI 测试

目标：覆盖之前频繁出现的页面卡死、刷新无反馈、接口失败全页空白问题。

实施：

1. 增加 Playwright 或 Vitest 测试环境。
2. 覆盖：
   - 数据中心一个接口失败时其他卡片仍展示。
   - 今日尾盘选股大结果集展开不会卡死。
   - 基金尾盘无基金池时展示明确错误。
   - 任务中心点击结果链接能打开结果页。

验收：

- 前端测试不再只依赖字符串断言。
- 至少 4 条关键用户路径有自动化验证。

## Phase 7：文档更新

### Task 7.1 重写架构说明

目标：让文档反映当前 ClickHouse-first 后台系统。

实施：

1. 更新 `docs/ARCHITECTURE.md`。
2. 新增 `docs/DATA_PIPELINES.md`：
   - 数据种类
   - 来源
   - 更新机制
   - 质量检查
   - 保留策略
   - 使用模块
3. 新增 `docs/TAIL_STRATEGY.md`：
   - 今日尾盘选股链路
   - 数据健康依赖
   - 规则分与历史校准
   - 回测/复盘口径

验收：

- 新人只读文档即可理解数据中心每个状态的来源和用途。
- 后续 AI 不再按旧 parquet/CSV 架构做错误判断。

## 推荐执行顺序

1. Phase 1：统一可交易池和 ST 口径。
2. Phase 2：ClickHouse 配置收敛。
3. Phase 4：任务 heartbeat 与统一任务入口。
4. Phase 3：同步骨架统一。
5. Phase 5：今日尾盘可信度重构。
6. Phase 6：前端拆分和 UI 测试。
7. Phase 7：文档更新。

这个顺序优先解决“数据是否可信、任务是否可靠、结果是否可解释”，再做页面和文档的持续优化。

