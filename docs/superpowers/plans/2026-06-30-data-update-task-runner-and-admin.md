# 数据获取任务脚本与后台管理配置实施计划

> **状态：待审核。** 本计划只用于讨论和确认范围，审核通过前不执行代码改动。
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可独立部署、可迁移到其他服务器运行的数据获取任务 runner，并让 Web 后台只负责配置、管理、查看状态和触发一次性任务。

**Architecture:** 新增 `src/data_ops` 作为独立任务系统：ClickHouse 保存任务配置、运行记录和心跳，`python -m src.data_ops.runner` 作为常驻进程执行任务。runner 必须能在没有 Web、没有前端、没有本仓库完整开发环境的服务器上运行；Web 后台只是控制面，只读写持久化任务状态。

**Tech Stack:** Python 3.12、ClickHouse、FastAPI、Vue 3、Element Plus、pytest、现有 ClickHouse 数据同步模块、macOS launchd。

---

## 0. 范围确认

### 本轮做

- 建立统一的数据任务配置和运行状态模型。
- 把数据获取任务从 Web 生命周期中拆出来。
- 把 runner 做成可独立部署单元，支持迁移到其他服务器运行。
- 支持独立 runner 自动运行：
  - 日终维护。
  - 5m 分钟线同步。
  - 行情快照采集。
  - 快照聚合刷新。
  - 数据质量快照。
- 后台数据中心增加“更新任务状态”模块。
- 后台支持启停配置、查看最近运行、查看错误、触发单次运行。
- 提供本机 launchd 安装脚本，让 runner 不依赖打开后台。
- 提供独立部署说明，明确依赖、配置、启动命令、日志路径和迁移步骤。

### 本轮不做

- 不接券商交易。
- 不做分布式任务队列。
- 不引入 Celery、Redis、Airflow 等新基础设施。
- 不重写已有数据同步逻辑，只封装现有同步函数。
- 不在本计划内修复日线 amount 单位漂移。该问题单独立项。
- 不在本计划内重做数据中心整体 UI，只补“更新任务状态”和必要交互。
- 不要求目标服务器部署 Web 前端或 FastAPI 后台。

## 0.1 独立部署标准

runner 必须达到以下标准，才算本计划完成：

- 可以在另一台服务器上通过命令行启动：

```bash
python -m src.data_ops.runner
```

- 启动时只依赖：
  - Python 运行环境。
  - 项目中数据同步所需的最小 Python 包。
  - ClickHouse 连接配置。
  - 必要的数据源网络访问能力。
- 不依赖：
  - Web 后台进程。
  - 前端构建产物。
  - SQLite `data/web/jobs.sqlite3`。
  - 浏览器页面是否打开。
  - 本机绝对路径。
- 配置通过环境变量或配置文件提供，不能把开发机路径写死。
- 日志写入可配置目录，默认 `logs/data_ops_runner.log`。
- 单轮验证命令 `python -m src.data_ops.runner --once` 可用于迁移后冒烟测试。
- 迁移到新服务器后，Web 后台只要连接同一个 ClickHouse，就能看到 runner 写入的任务状态。
- 第一版 runner 和 Web 后台连接同一个 ClickHouse，不做多 ClickHouse 切换。
- Linux 服务器部署第一版只在文档中提供 systemd 示例，不生成自动安装 systemd 服务脚本。

## 1. 当前代码边界

当前相关代码：

- `src/web/backend/data_ops_scheduler.py`：Web 进程内日终维护调度器，需要被独立 runner 取代。
- `src/web/backend/app.py`：当前会在 FastAPI lifespan 中自动启动分钟线 monitor、快照 monitor 和 data ops scheduler。
- `src/web/backend/data_status.py`：数据健康矩阵和质量快照逻辑。
- `src/web/backend/data_health_repair.py`：把健康告警翻译为修复动作。
- `scripts/run_daily_maintenance.py`：已有命令行维护入口，但仍复用 Web 后台 job 逻辑。
- `scripts/sync_clickhouse_minute5_kline.py`：5m 分钟线同步脚本。
- `src.data.clickhouse_quote_snapshot_sync.sync_clickhouse_quote_snapshots`：行情快照同步函数。
- `src.data.clickhouse_table_maintenance.optimize_quote_snapshot_rollups`：快照聚合维护函数。
- `frontend/src/pages/DataCenter.vue`：数据中心页面。
- `frontend/src/api/client.ts`：数据中心相关 API client。

## 2. 目标任务模型

第一版任务清单：

| task_key | 名称 | 默认触发 | 主要职责 |
|---|---|---|---|
| `post_close_maintenance` | 日终维护 | 交易日 15:10 后 | 日线聚合、指数日线、质量快照、可选尾盘策略复核 |
| `minute5_intraday_sync` | 5m 分钟线同步 | 交易时段每 60 秒 | 同步当日 5m K 线 |
| `quote_snapshot_capture` | 行情快照采集 | 交易时段每 10 秒 | 采集实时行情快照 |
| `quote_rollup_refresh` | 快照聚合刷新 | 交易时段每 60 秒 | 刷新 1m/5m 快照聚合 |
| `quality_snapshot` | 数据质量快照 | 每 5 分钟或手动 | 写入数据质量检查结果 |

任务状态枚举：

- `disabled`：未启用。
- `idle`：启用但未到执行时间。
- `running`：正在执行。
- `success`：最近一次成功。
- `failed`：最近一次失败。
- `stale`：runner 心跳或任务运行超时。
- `skipped`：按规则跳过，例如非交易日或非交易时段。

## 3. 文件结构

新增：

- `src/data_ops/__init__.py`：包入口。
- `src/data_ops/config.py`：独立 runner 配置加载，隔离项目路径和环境变量。
- `src/data_ops/models.py`：任务配置、运行记录、状态数据模型。
- `src/data_ops/repository.py`：ClickHouse 持久化读写。
- `src/data_ops/scheduler.py`：调度判断纯函数。
- `src/data_ops/handlers.py`：把现有同步函数封装为任务 handler。
- `src/data_ops/runner.py`：独立 runner 入口，支持 `python -m src.data_ops.runner`。
- `scripts/install_data_ops_launchd.sh`：安装本机 launchd 服务。
- `docs/data_ops_runner_deployment.md`：独立部署和迁移说明。
- `tests/test_data_ops/test_models.py`
- `tests/test_data_ops/test_config.py`
- `tests/test_data_ops/test_repository.py`
- `tests/test_data_ops/test_scheduler.py`
- `tests/test_data_ops/test_handlers.py`
- `tests/test_data_ops/test_runner.py`
- `tests/test_web/test_data_ops_tasks_api.py`

修改：

- `src/web/backend/app.py`：新增任务管理 API；关闭默认 Web 内置常驻数据任务。
- `src/web/backend/data_reliability.py`：数据可靠性报告改读持久化任务状态。
- `frontend/src/api/client.ts`：新增任务配置和状态接口类型。
- `frontend/src/pages/DataCenter.vue`：在健康矩阵之后增加“更新任务状态”模块。
- `tests/test_frontend/test_data_center_page.py`：覆盖数据中心任务模块。
- `docs/ARCHITECTURE.md`：补充独立 runner 与 Web 控制面的边界。

## 4. 数据表设计

后台管理配置以 ClickHouse 为唯一事实来源：

- Web 后台修改任务启停、调度参数、手动触发标记时，写入 `data_ops_task_config`。
- 独立 runner 读取 `data_ops_task_config` 决定是否运行任务。
- runner 执行结果写入 `data_ops_task_runs`。
- runner 存活状态和当前任务心跳写入 `data_ops_task_heartbeats`。
- Web 后台展示状态时，从这三类表合成当前状态，不读取 runner 本地文件。
- runner 本地配置只用于“如何连接 ClickHouse、日志写到哪里、runner id 是什么”，不用于保存业务任务启停状态。

### `data_ops_task_config`

字段：

- `task_key String`
- `enabled UInt8`
- `schedule_kind LowCardinality(String)`
- `schedule_config String`
- `max_runtime_seconds UInt32`
- `stale_after_seconds UInt32`
- `manual_trigger UInt8`
- `manual_triggered_at Nullable(DateTime)`
- `updated_at DateTime`

引擎：

```sql
ReplacingMergeTree(updated_at)
order by task_key
```

### `data_ops_task_runs`

字段：

- `run_id String`
- `task_key String`
- `status LowCardinality(String)`
- `started_at DateTime`
- `finished_at Nullable(DateTime)`
- `duration_seconds Float64`
- `result String`
- `error String`

引擎：

```sql
MergeTree
partition by toYYYYMM(started_at)
order by (task_key, started_at, run_id)
```

### `data_ops_task_heartbeats`

字段：

- `runner_id String`
- `task_key String`
- `heartbeat_at DateTime`
- `status LowCardinality(String)`
- `message String`

引擎：

```sql
ReplacingMergeTree(heartbeat_at)
order by (runner_id, task_key)
```

## 5. 实施任务

### Task 1: 建立任务模型

**Files:**

- Create: `src/data_ops/__init__.py`
- Create: `src/data_ops/models.py`
- Test: `tests/test_data_ops/test_models.py`

- [ ] **Step 1: 写模型测试**

测试点：

- 默认任务配置能生成 `post_close_maintenance`、`minute5_intraday_sync`、`quote_snapshot_capture`、`quote_rollup_refresh`、`quality_snapshot`。
- `schedule_config` 能稳定序列化为 JSON。
- 非法状态会被拒绝。

运行：

```bash
pytest tests/test_data_ops/test_models.py -q
```

预期：失败，原因是 `src.data_ops.models` 尚不存在。

- [ ] **Step 2: 实现模型**

实现：

- `DataOpsTaskConfig`
- `DataOpsTaskRun`
- `DataOpsTaskStatus`
- `default_task_configs()`
- `serialize_schedule_config()`
- `parse_schedule_config()`

- [ ] **Step 3: 验证模型测试通过**

```bash
pytest tests/test_data_ops/test_models.py -q
```

预期：通过。

### Task 2: 建立独立 runner 配置加载

**Files:**

- Create: `src/data_ops/config.py`
- Test: `tests/test_data_ops/test_config.py`

- [ ] **Step 1: 写配置测试**

测试点：

- 默认配置不包含开发机绝对路径。
- 可以通过环境变量设置 ClickHouse host、user、password、database。
- 可以通过环境变量设置日志目录。
- `--config` 指向的 JSON 文件能覆盖环境变量。
- 缺少 Web 后台配置时仍能生成 runner 配置。

运行：

```bash
pytest tests/test_data_ops/test_config.py -q
```

预期：失败，原因是 `src.data_ops.config` 尚不存在。

- [ ] **Step 2: 实现配置加载**

实现：

- `DataOpsRuntimeConfig`
- `load_data_ops_config(config_path=None, environ=None)`

配置来源优先级：

1. CLI 指定的配置文件。
2. 环境变量。
3. 项目默认配置。

必须支持的环境变量：

- `DATA_OPS_CLICKHOUSE_HOST`
- `DATA_OPS_CLICKHOUSE_USER`
- `DATA_OPS_CLICKHOUSE_PASSWORD`
- `DATA_OPS_CLICKHOUSE_DATABASE`
- `DATA_OPS_LOG_DIR`
- `DATA_OPS_RUNNER_ID`

- [ ] **Step 3: 验证配置测试通过**

```bash
pytest tests/test_data_ops/test_config.py -q
```

预期：通过。

### Task 3: 建立 ClickHouse repository

**Files:**

- Create: `src/data_ops/repository.py`
- Test: `tests/test_data_ops/test_repository.py`

- [ ] **Step 1: 写 repository 测试**

测试点：

- `ensure_tables()` 会创建三张表。
- `upsert_task_config()` 后能通过 `list_task_configs()` 读取。
- `start_run()`、`finish_run()` 会写入运行记录。
- `write_heartbeat()` 会更新 runner 心跳。
- `list_task_statuses()` 能合并配置、最近运行和心跳。

运行：

```bash
pytest tests/test_data_ops/test_repository.py -q
```

预期：失败，原因是 repository 尚不存在。

- [ ] **Step 2: 实现 repository**

实现类：

- `ClickHouseDataOpsRepository`

核心方法：

- `ensure_tables()`
- `seed_default_configs()`
- `list_task_configs()`
- `upsert_task_config(config)`
- `request_manual_run(task_key)`
- `consume_manual_trigger(task_key)`
- `start_run(task_key, runner_id)`
- `finish_run(run_id, status, result, error)`
- `write_heartbeat(runner_id, task_key, status, message)`
- `list_task_statuses(now=None)`

- [ ] **Step 3: 验证 repository 测试通过**

```bash
pytest tests/test_data_ops/test_repository.py -q
```

预期：通过。

### Task 4: 实现调度判断

**Files:**

- Create: `src/data_ops/scheduler.py`
- Test: `tests/test_data_ops/test_scheduler.py`

- [ ] **Step 1: 写调度测试**

测试点：

- 非交易日跳过交易时段任务。
- 交易日上午/下午允许 `minute5_intraday_sync` 和 `quote_snapshot_capture`。
- 15:10 后允许 `post_close_maintenance`。
- `manual_trigger=1` 时忽略时间窗口执行一次。
- 最近运行未超过 interval 时跳过。

运行：

```bash
pytest tests/test_data_ops/test_scheduler.py -q
```

预期：失败，原因是 scheduler 尚不存在。

- [ ] **Step 2: 实现纯函数**

实现：

- `DataOpsDecision`
- `should_run_task(config, status, now, is_trading_day)`
- `next_run_at(config, now, is_trading_day)`

规则：

- 调度函数不访问 ClickHouse。
- 调度函数不启动线程。
- 调度函数只返回 `run`、`skip_reason`、`next_run_at`。

- [ ] **Step 3: 验证调度测试通过**

```bash
pytest tests/test_data_ops/test_scheduler.py -q
```

预期：通过。

### Task 5: 封装任务 handler

**Files:**

- Create: `src/data_ops/handlers.py`
- Test: `tests/test_data_ops/test_handlers.py`

- [ ] **Step 1: 写 handler 测试**

测试点：

- 每个 handler 调用传入的底层 runner。
- handler 返回统一 JSON 结果。
- 底层异常会向上抛出，由 runner 统一记录失败。
- `post_close_maintenance` 不直接依赖 FastAPI app。

运行：

```bash
pytest tests/test_data_ops/test_handlers.py -q
```

预期：失败，原因是 handlers 尚不存在。

- [ ] **Step 2: 实现 handler 注册表**

实现：

- `build_default_handlers()`
- `run_post_close_maintenance()`
- `run_minute5_intraday_sync()`
- `run_quote_snapshot_capture()`
- `run_quote_rollup_refresh()`
- `run_quality_snapshot()`

约束：

- handler 复用现有同步函数。
- handler 不 import `FastAPI`。
- handler 不写 Web `JobStore`。
- handler 不读取前端、Web jobs SQLite 或开发机绝对路径。

- [ ] **Step 3: 验证 handler 测试通过**

```bash
pytest tests/test_data_ops/test_handlers.py -q
```

预期：通过。

### Task 6: 实现独立 runner

**Files:**

- Create: `src/data_ops/runner.py`
- Test: `tests/test_data_ops/test_runner.py`

- [ ] **Step 1: 写 runner 测试**

测试点：

- runner 启动时确保表存在并 seed 默认配置。
- 到期任务会执行 handler。
- 成功写 `success` 运行记录。
- 异常写 `failed` 运行记录。
- `manual_trigger` 执行后会被消费。
- 单轮模式 `--once` 能执行一轮后退出，方便测试和手动验证。

运行：

```bash
pytest tests/test_data_ops/test_runner.py -q
```

预期：失败，原因是 runner 尚不存在。

- [ ] **Step 2: 实现 runner**

实现：

- `DataOpsRunner`
- `DataOpsRunnerConfig`
- `run_once()`
- `run_forever()`
- CLI 参数：
  - `--once`
  - `--interval-seconds`
  - `--runner-id`
  - `--task-key`
  - `--config`
  - `--log-dir`

运行入口：

```bash
python -m src.data_ops.runner --once
```

- 独立部署要求：
  - runner 从 `src.data_ops.config` 加载配置。
  - runner 不 import `src.web.backend.app`。
  - runner 不创建或读取 `data/web/jobs.sqlite3`。
  - runner 启动日志写入 stdout 和 `DATA_OPS_LOG_DIR`。
  - 退出码能反映启动失败。

- [ ] **Step 3: 验证 runner 测试通过**

```bash
pytest tests/test_data_ops/test_runner.py -q
```

预期：通过。

### Task 7: 新增后台任务管理 API

**Files:**

- Modify: `src/web/backend/app.py`
- Test: `tests/test_web/test_data_ops_tasks_api.py`

- [ ] **Step 1: 写 API 测试**

测试点：

- `GET /api/data/ops-tasks` 返回任务列表。
- `PUT /api/data/ops-tasks/{task_key}/config` 能启停任务和更新 schedule。
- `POST /api/data/ops-tasks/{task_key}/run-once` 只写 manual trigger，不直接执行重任务。
- 未知 task 返回 404。

运行：

```bash
pytest tests/test_web/test_data_ops_tasks_api.py -q
```

预期：失败，原因是 API 尚不存在。

- [ ] **Step 2: 修改 app factory**

修改点：

- `create_app()` 增加 `data_ops_repository=None` 参数。
- 默认构建 `ClickHouseDataOpsRepository`。
- 新增三个 API。
- 保留旧 `/api/data/ops-scheduler` 一段兼容期，但返回 deprecated 字段。

- [ ] **Step 3: 验证 API 测试通过**

```bash
pytest tests/test_web/test_data_ops_tasks_api.py -q
```

预期：通过。

### Task 8: 关闭 Web 默认常驻数据任务

**Files:**

- Modify: `src/web/backend/app.py`
- Modify: `tests/test_web/test_minute5_monitor_api.py`
- Modify: `tests/test_web/test_quote_snapshot_monitor_api.py`
- Modify: `tests/test_web/test_data_status_api.py`

- [ ] **Step 1: 写行为测试**

测试点：

- 默认创建 app 时不自动启动 `minute5_monitor`。
- 默认创建 app 时不自动启动 `quote_snapshot_monitor`。
- 默认创建 app 时不自动启动 `data_ops_scheduler`。
- 旧手动 start/stop 接口仍可用，但标记为兼容接口。

运行：

```bash
pytest tests/test_web/test_minute5_monitor_api.py tests/test_web/test_quote_snapshot_monitor_api.py tests/test_web/test_data_status_api.py -q
```

预期：部分失败，原因是当前默认自动启动。

- [ ] **Step 2: 调整默认参数**

调整：

- `auto_start_minute5_monitor=False`
- `auto_start_quote_snapshot_monitor=False`
- `auto_start_data_ops_scheduler=False`

保留手动接口，避免一次性破坏现有页面。

- [ ] **Step 3: 验证行为测试通过**

```bash
pytest tests/test_web/test_minute5_monitor_api.py tests/test_web/test_quote_snapshot_monitor_api.py tests/test_web/test_data_status_api.py -q
```

预期：通过。

### Task 9: 数据中心增加“更新任务状态”

**Files:**

- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/DataCenter.vue`
- Test: `tests/test_frontend/test_data_center_page.py`

- [ ] **Step 1: 写前端源码测试**

测试点：

- `client.ts` 包含 `getDataOpsTasks()`。
- `DataCenter.vue` 包含“更新任务状态”。
- 任务状态模块位于健康矩阵之后、高级诊断之前。
- 健康度 100% 且没有 repair action 时，数据修复按钮不可点击。

运行：

```bash
pytest tests/test_frontend/test_data_center_page.py -q
```

预期：失败，原因是新 API 和模块尚未接入。

- [ ] **Step 2: 增加 API 类型**

新增类型：

- `DataOpsTaskConfig`
- `DataOpsTaskStatus`
- `DataOpsTasksResponse`

新增方法：

- `getDataOpsTasks()`
- `updateDataOpsTaskConfig(taskKey, payload)`
- `runDataOpsTaskOnce(taskKey)`

- [ ] **Step 3: 改造 DataCenter 页面**

新增模块展示：

- 任务名称。
- 启用状态。
- 当前状态。
- 最近开始/结束时间。
- 下一次计划时间。
- 最近错误。
- 启停开关。
- 单次运行按钮。

按钮规则：

- 任务禁用时，“单次运行”仍可用，但文案显示“手动运行一次”。
- 当前 `running` 时禁用重复触发。
- `stale` 和 `failed` 使用 warning/danger 样式。

- [ ] **Step 4: 验证前端测试和构建**

```bash
pytest tests/test_frontend/test_data_center_page.py -q
cd frontend && npm run build
```

预期：通过。

### Task 10: 安装脚本、部署说明与迁移验证

**Files:**

- Create: `scripts/install_data_ops_launchd.sh`
- Create: `docs/data_ops_runner_deployment.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: 写脚本静态测试**

在 `tests/test_scripts/test_data_ops_launchd_script.py` 中检查：

- 脚本包含 `python -m src.data_ops.runner`。
- plist 使用项目绝对路径。
- 日志写入 `logs/data_ops_runner.log`。
- 支持 `install`、`uninstall`、`status`。
- 脚本允许通过环境变量覆盖 ClickHouse 和日志配置。

运行：

```bash
pytest tests/test_scripts/test_data_ops_launchd_script.py -q
```

预期：失败，原因是脚本尚不存在。

- [ ] **Step 2: 实现 launchd 脚本**

脚本命令：

```bash
scripts/install_data_ops_launchd.sh install
scripts/install_data_ops_launchd.sh status
scripts/install_data_ops_launchd.sh uninstall
```

- [ ] **Step 3: 更新架构文档**

补充：

- Web 是控制面。
- `src.data_ops.runner` 是数据任务执行面。
- ClickHouse 保存任务配置、运行记录和心跳。
- launchd 只是本机守护方式，不是业务逻辑。

- [ ] **Step 4: 编写独立部署说明**

`docs/data_ops_runner_deployment.md` 必须包含：

- 最小部署文件清单。
- Python 依赖安装方式。
- ClickHouse 连接配置方式。
- 环境变量示例。
- 单轮冒烟测试命令。
- 常驻运行方式：
  - macOS launchd。
  - Linux systemd 的命令示例，不生成自动安装脚本。
- 迁移后如何在 Web 后台确认状态。

- [ ] **Step 5: 验证脚本测试通过**

```bash
pytest tests/test_scripts/test_data_ops_launchd_script.py -q
```

预期：通过。

### Task 11: 集成验证

**Files:**

- No new files.

- [ ] **Step 1: 跑后端相关测试**

```bash
pytest tests/test_data_ops tests/test_web/test_data_ops_tasks_api.py tests/test_web/test_data_status_api.py -q
```

预期：通过。

- [ ] **Step 2: 跑前端构建**

```bash
cd frontend && npm run build
```

预期：通过。

- [ ] **Step 3: 手动单轮 runner 验证**

```bash
python -m src.data_ops.runner --once
```

预期：

- 命令正常退出。
- ClickHouse 中出现默认任务配置。
- 未到运行窗口的任务显示 `skipped` 或 `idle`，不会误跑重任务。

- [ ] **Step 4: 独立部署冒烟验证**

在不启动 Web 后台的情况下运行：

```bash
DATA_OPS_LOG_DIR=logs python -m src.data_ops.runner --once
```

预期：

- 不需要启动 FastAPI。
- 不需要存在 `data/web/jobs.sqlite3`。
- 日志写入 `logs/data_ops_runner.log`。
- ClickHouse 中能看到任务配置或运行记录。

- [ ] **Step 5: 后台 API 验证**

```bash
curl http://127.0.0.1:8000/api/data/ops-tasks
```

预期：

- 返回 5 个默认任务。
- 每个任务都有 `task_key`、`enabled`、`status`、`last_started_at`、`last_finished_at`、`next_run_at`、`last_error`。

## 6. 审核重点

执行前需要确认：

1. 第一版任务清单是否只保留这 5 个任务。
2. `post_close_maintenance` 是否继续包含尾盘策略复核。
3. Web 默认关闭常驻 monitor 是否接受。
4. `run-once` 是否只写 manual trigger，而不是 Web 直接执行。
5. launchd 作为 macOS 本机守护方式；Linux 第一版只给 systemd 示例，不生成安装脚本。
6. 目标服务器与 Web 后台连接同一个 ClickHouse，第一版不支持多 ClickHouse 切换。

## 7. 风险与控制

- 风险：runner 和 Web 同时跑同一个任务。
  - 控制：任务领取和 manual trigger 消费必须在 repository 层保证单次语义。
- 风险：任务失败后后台只显示失败，但不知道原因。
  - 控制：`data_ops_task_runs.error` 保存异常文本，DataCenter 展示最近错误。
- 风险：迁移后原有自动 monitor 行为消失。
  - 控制：计划中保留旧手动接口一段兼容期，并在数据中心展示新任务状态。
- 风险：ClickHouse 不可用时 runner 无法记录状态。
  - 控制：runner 启动失败直接退出并写本地日志，交给 launchd 重启；Web 显示任务状态不可用。
- 风险：迁移到其他服务器后路径、环境变量或依赖不完整。
  - 控制：配置加载与部署文档单独成任务，`--once` 冒烟测试作为验收标准。
- 风险：独立 runner 不小心 import Web app，导致迁移时需要 FastAPI/Web 依赖。
  - 控制：handler 和 runner 测试中明确断言不依赖 `src.web.backend.app`、不使用 Web `JobStore`。

## 8. 暂不执行

本计划建立后先进入人工审核。审核通过前不执行 Task 1-10。
