# Mootdx 运维可信度改进设计

## 目标

使日线缺口核验、任务失败状态和手动任务等待状态与实际数据处理结果一致，避免运维页面产生误导。

## 1. 日线缺口按连续块核验

质量页仍按日期显示缺失，但用户选中某个 `needs_review` 项并点击 Baostock 核验时，客户端提交该标的的完整连续缺口块（`missing_dates` 的最小与最大日期），而不是只提交当前选中的交易日。后端对这个日期范围逐日写入 `mootdx_daily_gap_verifications`。

核验完成且整个块均为 `no_data` 时，现有分类规则将该块显示为“已知无数据 / 无需回补”；任一日期为 `available` 时显示“建议回补”；任一核验错误时保持“待核验”。物理缺失数不因核验改变。

## 2. 内层同步失败必须失败

`sync_mootdx_offline_data()` 将单个任务异常记录在 `result.failed` 后，data-ops handler 必须将其转换为异常，runner 必须写入 `data_ops_task_runs.status = failed` 和失败心跳。监控页不能仅因外层调用正常返回而显示成功。

为防止运行中的旧进程或返回格式变化造成漏判，失败判定以非空 `result.failed` 为准，并保留任务键和原始失败原因。

## 3. 手动任务排队状态

点击“运行一次”仅创建 `manual_trigger`，直到 maintenance runner 接管前不应显示 `idle`。任务状态 API 新增/暴露 `queued`：任务配置 `manual_trigger=true` 且没有正在运行的心跳时显示该状态，并提供“等待 runner 接管”的说明。runner 开始后照常切换为 `running`，完成后为 `success` 或 `failed`。

`queued` 只表示一次待消费的手动触发，不改变自动计划和任务启用状态。

## 验收

- 对 `002005.SZ` 这类跨多日缺口，单次页面核验请求提交完整块范围。
- Baostock 对全块均返回无数据时，所有对应日期归为 `known_no_data`。
- 任意内层 Mootdx 任务在 `failed` 中返回错误时，data-ops 运行记录为 `failed`。
- 手动触发写入后、runner 接管前，任务 API/UI 显示 `queued`；接管后显示 `running`。
- 既有自动计划、回补和旧数据源体系不受影响。
