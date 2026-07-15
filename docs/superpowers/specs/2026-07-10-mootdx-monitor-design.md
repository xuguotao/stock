# mootdx 任务监控设计

## 目标

为 `stock_catalog` 和 `stock_kline_daily` 提供可手工执行的说明文档，以及可在 Web 后台配置、触发、审计和查看健康状态的管理模块。

## 模块边界

- `src/data_ops/mootdx_tasks.py`：mootdx 任务定义的唯一来源，包含 task key、名称、说明、默认调度与运行参数。
- `src/web/backend/mootdx_monitor.py`：只读聚合 data_ops 配置、运行记录、mootdx 源端运行诊断和 ClickHouse 表健康指标。
- `src/web/backend/app.py`：暴露 mootdx 监控 API，仍复用通用 data_ops 配置更新和手动触发 API。
- `frontend/src/pages/MootdxMonitor.vue`：任务配置、运行审计、健康状态三个 tab；不内置任务参数或固定状态。

## 数据流

```text
data_ops_task_config / heartbeats / runs
                 +
mootdx_sync_runs / symbol_data_status / catalog / stock_kline
                 |
                 v
        GET /api/data/mootdx/monitor
                 |
                 v
         MootdxMonitor.vue
```

配置更新仍调用 `PUT /api/data/ops-tasks/{task_key}/config`，手工触发仍调用 `POST /api/data/ops-tasks/{task_key}/run-once`。监控页面只展示 `mootdx_tasks.py` 定义的 task key，避免将通用任务中心中的无关任务混入。

## 健康判定

- 配置和 runner 状态来自 data_ops 持久化状态。
- 运行审计展示最近 mootdx 原始同步，读取任务、耗时、写入数、审计状态和错误。
- 健康汇总展示 catalog 最新时间与数量、日线最新交易日和覆盖数、日线状态分布、最近失败和 degraded 审计数。
- 读取监控表失败时，单项返回 `unavailable` 和错误，不阻断整个后台页面。

## 验收

1. 后端 API 能返回三个 mootdx 任务、其可修改配置、运行记录及健康汇总。
2. 任务中心之外存在独立 mootdx 页面，支持刷新、更新配置和请求手工运行。
3. 页面显示审计健康、失败原因和数据覆盖，而非仅显示运行成功/失败。
4. 文档包含参数说明、日常命令、回补、缺口核对和无数据复查样例。
