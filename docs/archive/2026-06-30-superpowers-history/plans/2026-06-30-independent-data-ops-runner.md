# 2026-06-30 独立数据更新 Runner 实施计划

## 目标

把数据更新任务从 Web 后台生命周期中拆出来。系统应在不打开后台页面的情况下自动运行数据更新脚本；后台只负责管理配置、查看状态、触发单次修复和展示日志。

## 当前判断

- 可行，而且是数据中心有效性的前置条件。
- Web 继续承担控制面职责，不再承担长期 worker 职责。
- 第一版采用一个独立 runner 进程管理多个任务；只有当负载或故障隔离需要时，再拆成多个 worker。
- 任务状态必须落 ClickHouse，避免进程重启后丢失上下文。

## 数据模型

新增 `src/data_ops` 包，使用 ClickHouse 保存任务配置、运行记录和心跳。

建议表：

- `data_ops_task_config`：任务配置。
- `data_ops_task_runs`：每次运行记录。
- `data_ops_task_heartbeats`：runner 心跳。

任务配置字段至少包括：

- `task_key`：任务标识。
- `enabled`：是否启用。
- `schedule_kind`：调度类型，例如 `interval`、`daily_time`、`manual`。
- `schedule_config`：调度参数 JSON。
- `max_runtime_seconds`：最大允许运行时间。
- `stale_after_seconds`：超过多久没心跳视为异常。
- `updated_at`：配置更新时间。

任务状态字段至少包括：

- `status`：`idle`、`running`、`success`、`failed`、`stale`、`disabled`、`skipped`。
- `last_started_at`
- `last_finished_at`
- `next_run_at`
- `last_result`
- `last_error`
- `heartbeat_at`

## 第一批任务

- `post_close_maintenance`：收盘后日线同步、质量检查、派生数据维护。
- `minute5_intraday_sync`：盘中 5 分钟线同步。
- `quote_snapshot_capture`：行情快照采集。
- `quote_rollup_refresh`：快照聚合到分钟线。
- `quality_snapshot`：数据质量快照。

## 后端改造

新增模块：

- `src/data_ops/models.py`：任务配置、运行记录、状态模型。
- `src/data_ops/repository.py`：ClickHouse 读写封装。
- `src/data_ops/scheduler.py`：纯函数调度判断。
- `src/data_ops/runner.py`：独立 runner 入口。

`runner` 只做三件事：

1. 读取启用的任务配置。
2. 判断哪些任务到期。
3. 执行任务 handler，并写入运行记录、状态和心跳。

任务 handler 第一版可以复用现有数据同步函数，但必须通过清晰边界封装，不能把 Web app 依赖带进 runner。

## Web 控制面

新增 API：

- `GET /api/data/ops-tasks`：读取任务状态列表。
- `PUT /api/data/ops-tasks/{task_key}/config`：更新任务配置。
- `POST /api/data/ops-tasks/{task_key}/run-once`：触发单次运行。

Web API 只写配置和读取状态。`run-once` 可以写入一次性触发标记，由 runner 领取执行；不要在 Web 请求线程里直接跑重任务。

## 数据中心前端

数据中心保留三个层级：

1. 健康矩阵：数据源当前是否可用。
2. 更新任务状态：任务是否启用、是否按计划运行、最近错误是什么。
3. 高级诊断：需要时展开查看质量规则、来源、用途和修复细节。

修复按钮规则：

- 数据源健康且没有待修复项时禁用。
- 存在明确修复动作时才启用。
- 按钮文案必须表达具体动作，例如“回填日线成交额”“重跑质量快照”，不能只写泛化的“修复”。

## 系统启动

提供脚本：

- `scripts/install_data_ops_launchd.sh`

该脚本在本机安装 launchd 配置，用于自动启动：

```bash
python -m src.data_ops.runner
```

第一版只支持本机开发环境。生产化部署以后再补 systemd、Docker 或其他 supervisor。

## 测试计划

- `tests/test_data_ops/test_repository.py`：验证任务配置、运行记录、心跳读写。
- `tests/test_data_ops/test_scheduler.py`：验证调度判断纯函数。
- `tests/test_data_ops/test_runner.py`：验证 runner 能领取到期任务、写运行结果、处理失败。
- `tests/test_web/test_data_ops_api.py`：验证 Web API 读取状态和修改配置。
- `tests/test_frontend/test_data_center_page.py`：验证数据中心展示更新任务状态，并按健康度控制修复按钮。

## 验收标准

- 不打开 Web 后台，runner 也能按配置自动执行任务。
- Web 能展示每个任务的启用状态、最近运行结果、最近错误、心跳和下一次计划时间。
- Web 修改任务配置后，runner 能读取并生效。
- 健康矩阵和更新任务状态是数据中心前两个主模块。
- 日线数据健康度 100% 且没有待修复项时，修复按钮不可点击。
- 测试覆盖 repository、scheduler、runner、Web API 和数据中心页面。

## 实施顺序

1. 建立 `src/data_ops` 模型和 ClickHouse repository。
2. 实现调度判断纯函数。
3. 实现独立 runner 和第一批任务 handler。
4. 增加 Web API 控制面。
5. 改造数据中心页面，加入“更新任务状态”模块。
6. 增加 launchd 安装脚本。
7. 跑完整验证并更新文档。
