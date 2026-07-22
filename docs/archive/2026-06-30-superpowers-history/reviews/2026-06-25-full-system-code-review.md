# 2026-06-25 全系统代码与架构复查

> 范围：`src/`、`frontend/src/`、`scripts/`、`tests/`、`docs/ARCHITECTURE.md`，并对照 `docs/superpowers/reviews/2026-06-25-data-and-code-review.md` 的前序结论。
> 方法：按 `using-superpowers`、`codex-architecture-review`、`writing-plans` 做一次结构化复查；静态扫描大文件/重复口径/硬编码配置/任务边界，抽读关键模块，并复核最近一次测试与构建结果。
> 本轮不改业务逻辑，只输出问题、证据和整改计划。

## 结论摘要

系统已经从早期的本地 parquet/CSV 研究工具，演进成 ClickHouse-first 的后台量化控制台：包含行情快照、1m/5m 分钟线、日线、基金尾盘、今日尾盘选股、策略复盘、任务中心、数据中心和 ML 样本构建。当前主要风险不是功能缺失，而是职责边界和数据口径还没跟上演进速度。

优先级最高的三类问题：

1. 数据口径没有完全中心化。策略可交易池、ST 过滤、bars 数阈值、尾盘时间窗在多个模块重复实现，容易出现“页面显示健康，但策略实际使用另一套口径”的情况。
2. Web 后台和数据任务边界过重。`app.py`、`data_status.py`、`DataCenter.vue`、`TailLiveSelection.vue`、`FundTail.vue` 都承担了过多职责，导致性能、容错、测试和后续迭代成本升高。
3. ClickHouse 配置、任务调度和 API 契约仍偏工程早期形态。连接参数散落、任务依赖进程内线程、前后端接口手写同步，短期能跑，长期会拖慢稳定化。

## 已验证事实

- Python 测试：最近一次全量 `pytest -q` 通过，结果为 `492 passed`。
- 前端构建：最近一次 `npm --prefix frontend run build` 通过，只有 chunk size 与 Rollup 注释类 warning。
- 后端编译：关键文件 `tail_live.py`、`data_status.py`、`app.py`、`clickhouse_minute5_sync.py`、`clickhouse_quote_snapshot_sync.py` 已通过 `py_compile`。
- 当前未提交状态：`docs/superpowers/reviews/` 是 untracked 目录，里面包含外部 AI review 文档；本轮需避免误删或全量加入无关文件。

## 代码规模信号

| 文件 | 行数 | 风险信号 |
|---|---:|---|
| `src/web/backend/data_status.py` | 1663 | 数据中心查询、质量检查、健康度、展示结构混在一起 |
| `frontend/src/pages/DataCenter.vue` | 1690 | 页面、数据映射、健康逻辑、状态展示过重 |
| `src/web/backend/app.py` | 1546 | FastAPI 工厂、路由、后台任务、状态注入、任务执行器集中 |
| `frontend/src/pages/TailLiveSelection.vue` | 1238 | 选股表、健康检查、任务提交、结果解释集中 |
| `frontend/src/pages/FundTail.vue` | 1098 | 基金池、数据刷新、建议生成、可信度展示集中 |
| `src/web/backend/tail_live.py` | 976 | 今日尾盘选股编排、诊断、写报告、可信度、下一日计划集中 |
| `frontend/src/api/client.ts` | 1023 | 手写接口类型与请求函数，缺少生成式契约 |

这些不是单纯“行数大”的问题，而是多个变化频繁的职责被放在同一文件，导致任何功能变动都会扩大回归面。

## 主要发现

### P1：策略可交易池口径仍未完全统一

证据：

- `src/web/backend/backtests.py` 使用 `bars >= 30`。
- `src/ml/tail_dataset_audit.py` 使用 `bars >= 120`。
- `src/web/backend/data_status.py` 的策略可交易统计使用最新日有成交、volume/amount 条件。
- `src/data/clickhouse_source.py` 已经有参数化 `tradable_symbols` 类能力，但调用侧仍有重复 SQL。

影响：

- 数据中心、回测、ML 审计、今日尾盘选股可能展示不同的“可交易池”规模。
- 用户看到的数据完整性未必就是策略实际使用的池子完整性。
- 后续做策略训练时，样本池和实盘池可能不一致，导致回测收益和实盘预选不匹配。

建议：

- 建立单一 `StrategyUniverseService` 或 `src/data/strategy_universe.py`。
- 明确三个层级：`all_active`、`strategy_tradable`、`tail_live_eligible`。
- 所有模块只传入 `trade_date`、`min_daily_bars`、`require_minute5`、`include_st` 等参数，不再手写股票池 SQL。

### P1：ST 过滤与股票名称判断仍存在重复实现

证据：

- `src/core/constants.py` 已有 `is_st(name)`。
- `src/data/clickhouse_minute5_sync.py`、`src/data/clickhouse_minute1_sync.py`、`src/data/clickhouse_quote_snapshot_sync.py` 有使用 `is_st` 的路径。
- `src/web/backend/backtests.py`、`src/ml/tail_dataset_audit.py` 仍出现 `positionUTF8(coalesce(s.name, ''), 'ST') = 0`，大小写和语义与 `is_st` 不完全一致。

影响：

- ST、退市、特殊名称股票的排除规则容易漂移。
- 数据中心“策略可交易池”与回测/训练池可能差几只到几十只股票，用户会反复看到“缺一只”“异常不关心”的问题。

建议：

- 数据库层面可以保留 SQL 预过滤，但最终口径应统一落到 Python 的 `is_st` 或 ClickHouse UDF/物化字段。
- 在 `stocks` 表或派生视图中沉淀 `is_st`、`is_active`、`is_strategy_tradable` 字段，减少查询侧字符串判断。

### P1：ClickHouse 连接配置和凭据散落

证据：

- 当时的 `src/data/clickhouse_source.py` 曾含有硬编码的内网 host/password；现已去除，凭据仅允许由环境变量提供。
- `src/data/clickhouse_minute5_sync.py`、`clickhouse_minute1_sync.py`、`clickhouse_daily_sync.py`、`clickhouse_table_maintenance.py`、`src/web/backend/data_status.py`、多个 `scripts/` 仍有同类默认值。
- `ClickHouseStockDataSource.from_env()` 已存在，但不是唯一入口。
- `.env.example` 尚未形成完整 ClickHouse 配置样例。

影响：

- 换环境、换库、临时测试库时容易漏改。
- 密码进入源码，不利于后续共享、开源或多机部署。
- 单元测试很容易绑定到当前个人局域网假设。

建议：

- 新增 `config/settings.py` 的 ClickHouse 配置模型，统一读取 `STOCK_CLICKHOUSE_HOST/USER/PASSWORD/DATABASE`。
- `ClickHouseStockDataSource()` 默认改为从 settings/env 获取；脚本 argparse 默认值读取 settings，不再硬编码。
- `.env.example` 补齐配置，但不放真实密码。

### P1：Web 后台应用工厂承担过多职责

证据：

- `src/web/backend/app.py` 的 `create_app` 函数约 671 行。
- 该文件同时做依赖注入、状态挂载、路由声明、后台任务提交、任务执行函数、自动维护调度。
- `_run_tail_live_selection_job`、`_run_data_health_repair_job`、`_run_daily_maintenance_job` 等执行器在同一模块内。

影响：

- 任一页面/任务改动都可能触及 app 工厂，回归面大。
- 后台任务无法独立测试和独立部署。
- 未来引入 worker、队列、认证、权限、OpenAPI 客户端生成时会更难拆。

建议：

- 拆成 `routers/`、`services/`、`tasks/` 三层：
  - `routers`: 只做 request/response 和错误映射。
  - `services`: 编排数据源、策略、任务状态。
  - `tasks`: 可被 API、scheduler、CLI 共同调用的任务函数。
- `create_app` 只负责 wiring，不包含长业务流程。

### P1：任务系统仍是进程内后台任务，缺少耐久执行语义

证据：

- `src/web/backend/jobs.py` 使用 legacy local DB 保存元数据。
- `app.py` 用 FastAPI `BackgroundTasks` 启动耗时任务。
- `DataOpsScheduler`、`Minute5UpdateMonitor`、`QuoteSnapshotMonitor` 都是进程内 daemon thread。
- 启动时会把 running job 标记为 interrupted，但无法恢复执行。

影响：

- Web 进程重启、浏览器触发、手动脚本和自动调度之间仍可能存在并发/中断问题。
- 用户看到“running”或“完成 0 次”时，很难判断任务是否真的在工作。
- 数据采集这种核心链路不宜依赖 Web 进程生命周期。

建议：

- 保留当前 JobStore 做展示，但执行层迁移到独立 worker 或轻量队列。
- 每个任务写入结构化 heartbeat、lease、attempt、last_success_at、last_error_at。
- 自动任务和手动任务统一通过同一个调度入口提交，避免并发写同一数据表。

### P1：今日尾盘选股可信度仍偏“解释分”，不是历史校准概率

证据：

- `src/web/backend/tail_live.py` 中 `_credibility()` 返回 `score/grade/components/risks`。
- `history` 字段仍显示“样本不足”，测试也断言该状态。
- 当前可信度由强度、量能、涨幅质量等规则分构成，尚未与历史命中率、分位、次日收益分布做校准。

影响：

- 页面上的“可信度 87”容易被理解成胜率或概率，但实际更像规则质量分。
- 用户会继续追问“为什么最终选股不在策略池前列”“可信度怎么算”。

建议：

- 将字段拆成 `rule_score`、`historical_hit_rate`、`calibrated_probability`、`sample_size`。
- 历史不足时不展示“概率型可信度”，只展示规则评分和风险标签。
- 策略复盘沉淀每个打分分桶的后验表现，用于今日尾盘选股解释。

### P2：分钟线和快照同步实现重复，接口形状不一致

证据：

- `src/data/clickhouse_minute5_sync.py` 约 565 行，`clickhouse_minute1_sync.py` 约 321 行，目标符号解析、目标时间、fetch/insert/progress 结构相似。
- `db_path` 等兼容参数在 ClickHouse 同步中基本不再承担实际作用。
- 快照同步和分钟线同步都有 chunk/progress/coverage 概念，但返回结构不统一。

影响：

- 1m/5m/快照的健康展示、补漏重试、性能优化会重复做。
- 一处优化了 chunk 或进度，另一处可能遗漏。

建议：

- 抽象 `IntradaySyncJob` 基类或函数模板，封装：resolve universe、fetch batch、normalize bars、insert、coverage、progress。
- 1m、5m、snapshot 只提供 source adapter 和 table schema。
- 统一返回 `target_count`、`fetched_count`、`inserted_count`、`latest_time`、`coverage_after`、`timings`、`warnings`。

### P2：数据中心页面功能强，但信息架构仍偏堆叠

证据：

- `frontend/src/pages/DataCenter.vue` 1690 行。
- 页面同时显示连接、表覆盖、健康检查、自动任务、质量问题、操作按钮、数据集、维护入口。
- 数据源状态、更新机制、质量检查和手动操作混在一个页面组件中。

影响：

- 用户频繁问“这个按钮是什么”“这个 missing 是什么”“为什么完成 0 次”。
- 组件越改越大，UI 问题和数据问题难以分离。

建议：

- 拆为四个子视图：
  - `DataSourceOverview`: 数据类型、来源、最新时间、用途。
  - `DataPipelineHealth`: 自动任务、心跳、最近成功/失败、下一次执行。
  - `DataQualityIssues`: 完整性、异常值、新鲜度、影响模块。
  - `ManualOperations`: 只保留明确需要人工触发的操作。

### P2：前端 API 契约手写，缺少生成和契约测试

证据：

- `frontend/src/api/client.ts` 约 1023 行。
- 多数接口类型手写维护。
- `tests/test_frontend/*` 大量是读取 Vue/TS 源码做字符串断言，能防止漏写某些关键文案，但不能验证真实交互、渲染和长列表性能。

影响：

- 后端 response shape 变化时，前端类型不一定同步。
- 页面卡死、表格展开、异步刷新、按钮 disabled 等问题很难靠现有测试发现。

建议：

- 从 FastAPI OpenAPI 生成 TypeScript client 或至少生成 schema 类型。
- 引入最小 Playwright/Vitest 覆盖关键流程：数据中心加载降级、今日尾盘选股运行结果、基金尾盘刷新失败提示、最终选股表展开。

### P2：架构文档已经过期

证据：

- `docs/ARCHITECTURE.md` 仍描述“数据中心只读取本地 `data/research/*.parquet`”、“基金尾盘页面通过本地 CSV 输入”等早期设计。
- 当前实现已经有 ClickHouse 数据源、基金 ClickHouse repository、快照 rollup、自动任务和质量检查。

影响：

- 后续协作时，新 AI 或人类开发者会按旧架构理解系统。
- 容易继续引入本地 parquet/CSV 旁路，削弱 ClickHouse-first 的统一方向。

建议：

- 在完成第一轮结构整改后重写 `docs/ARCHITECTURE.md`。
- 新增 `docs/DATA_CENTER.md` 或 `docs/DATA_PIPELINES.md`，明确每类数据的来源、用途、更新频率、质量规则、保留策略。

## 架构候选边界

建议逐步收敛到以下边界：

```text
frontend pages
  -> generated api client
  -> FastAPI routers
  -> application services
  -> repositories / data services
  -> ClickHouse / external data sources

background scheduler / worker
  -> same application tasks
  -> JobStore heartbeat/result
  -> DataQuality snapshots
```

关键新模块候选：

- `src/config/clickhouse.py`: ClickHouse settings。
- `src/data/strategy_universe.py`: 策略可交易池唯一口径。
- `src/data/intraday_sync.py`: 1m/5m/快照同步公共骨架。
- `src/web/backend/routers/*`: API 路由拆分。
- `src/web/backend/services/*`: 页面服务和业务编排。
- `src/web/backend/tasks/*`: 可由 API/调度/CLI 共用的任务。
- `src/strategy/tail_session/credibility.py`: 今日尾盘评分解释、历史校准、风险标签。

## 验证缺口

当前测试数量不少，但缺口集中在三处：

1. 缺少端到端 UI 测试。前端源码字符串测试不能证明页面不会卡死、不会全量渲染过多行、不会因为一个接口失败而全页空白。
2. 缺少跨模块口径测试。应断言数据中心、回测、ML 审计、今日尾盘选股对同一日期的可交易池一致。
3. 缺少调度/并发测试。数据同步、日常维护、手动触发之间的互斥、重试和 heartbeat 需要可重复验证。

## 建议优先级

第一优先级不是继续加新策略，而是把“数据口径、任务执行、页面可信展示”三条主线收紧。否则后续做 ML 训练、因子挖掘、策略复盘时，结果会持续被数据口径和运行状态噪声污染。
