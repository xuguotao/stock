# 2026-06-26 Superpowers 系统复查

> 范围：`src/`、`frontend/src/`、`tests/`、`docs/ARCHITECTURE.md`，并对照 2026-06-25 两份 review 与当前代码。
> 方法：按 `using-superpowers`、`codex-architecture-review`、`test-driven-development`、`verification-before-completion` 执行；先读文档，再用 `rg`/关键文件抽读验证旧问题是否仍存在。

## 当前结论

系统已经明显从“本地研究工具”收敛为 ClickHouse-first 的后台量化系统。2026-06-25 review 中最危险的几项已经闭合或部分闭合：

- 策略可交易池已建立 `src/data/strategy_universe.py`，并接入 `backtests.py`、`tail_live.py`、`tail_dataset_audit.py`、`data_status.py`。
- ML 标签收益已向量化，并对无效 0 价返回 `NA`，不再把异常 OHLC 静默当成 0 收益。
- Tail ML audit 已区分 `pending_history` 与真正的数据质量不足。
- ClickHouse settings 已进入 `config/settings.py`，`.env.example` 已提供 `STOCK_CLICKHOUSE_*`。
- 模型评估已经增加风险调整收益，并把 promotion gate 从“只看冲高收益”推进到“收益/回撤共同约束”。

## 本轮已修

### 1. 数据中心 ST 统计口径统一

文件：

- `src/web/backend/data_status.py`
- `tests/test_web/test_clickhouse_data_status.py`
- `tests/test_web/test_data_status_api.py`

问题：数据中心的股票总览仍用 SQL `upper(name) like '%ST%'` 判断 ST。这个口径会把 `best科技` 这类包含 `st` 字符但不是 ST 前缀的股票误计为 ST，与 `src.core.constants.is_st()` 不一致。

处理：本地 SQLite 与 ClickHouse 的 stock summary 都改为读取 `symbol, name` 后用 `is_st()` 统计。测试覆盖 `*ST测试` 与 `best科技` 边界。

影响：数据中心“非 ST 股票”展示与策略可交易池的最终 Python 判断更一致，减少“页面健康度与策略扫描池对不上”的误差来源。

### 2. 今日尾盘选股模板结构防回归

文件：

- `tests/test_frontend/test_tail_live_selection_page.py`

处理：补充预检数据状态列的 slot 模板结构约束，防止后续改页面时重新引入嵌套 slot 渲染风险。

## 仍建议继续推进

### P1：前端大页面仍需组件化

文件：

- `frontend/src/pages/DataCenter.vue`：1690 行
- `frontend/src/pages/TailLiveSelection.vue`：1352 行
- `frontend/src/pages/FundTail.vue`：1098 行

问题：页面同时承担接口调用、状态聚合、展示映射、表格渲染和异常解释。现在已经有字符串测试兜底，但还没有真正的渲染/交互测试覆盖“点击最终选股卡死”“接口失败局部降级”等用户路径。

建议下一步：

- 先拆 `TailLiveSelection.vue`：`TailRunForm`、`TailDataHealth`、`TailRunHistory`、`TailRankedTable`、`TailSelectionTable`。
- 再给今日尾盘选股加最小 Vitest/Playwright 交互测试：大结果集加载、展开最终选股、打开个股趋势。

### P1：JobStore 与自动任务还缺耐久执行语义

文件：

- `src/web/backend/jobs.py`
- `src/web/backend/app.py`
- `src/web/backend/data_ops_scheduler.py`
- `src/web/backend/minute5_monitor.py`
- `src/web/backend/quote_snapshot_monitor.py`

问题：任务展示已经比早期清楚，但执行仍主要依赖 Web 进程内线程。数据采集这种核心任务需要 heartbeat、lease、attempt 和互斥 key，否则用户仍会遇到 running/stale 判断困难。

建议下一步：

- Job 记录增加 `heartbeat_at`、`attempt`、`lease_key`。
- 自动任务和手动按钮统一走同一任务提交入口。
- 同类任务运行中时返回已有 job id，不再重复启动。

### P2：数据中心质量 SQL 仍有部分 SQL ST 粗过滤

文件：

- `src/web/backend/data_status.py`

说明：本轮已把头部 stock summary 统一为 `is_st()`。但缺失样本查询、latest symbol count 等内部质量 SQL 仍用 `upper(s.name) not like '%ST%'` 做粗过滤。它们主要用于样本和覆盖率估算，风险低于策略可交易池，但长期仍建议迁到 `StrategyUniverse` 或派生字段。

### P2：架构文档仍偏旧

文件：

- `docs/ARCHITECTURE.md`

问题：文档仍有“数据中心读取 research parquet”“基金尾盘本地 CSV”等早期表述，和当前 ClickHouse-first 架构不完全一致。

建议：在完成任务系统和前端拆分后，重写 `docs/ARCHITECTURE.md`，并新增 `docs/DATA_PIPELINES.md`。

## 下一轮建议顺序

1. 完成任务系统 heartbeat/lease，先解决“后台是否卡住”的可信度问题。
2. 拆分 `TailLiveSelection.vue` 并加交互测试，解决最终选股点击和大表渲染风险。
3. 继续把数据中心内部质量 SQL 的股票池判断收敛到 `StrategyUniverse` 或物化字段。
4. 更新架构文档和数据管线文档。
