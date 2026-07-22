# mootdx catalog 与日线自治运行实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `stock_catalog` 与 `stock_kline_daily` 可由现有 `data_ops` 独立调度、在可恢复异常后自动补偿，并产生可判定的运行审计结果。

**Architecture:** `stock_catalog` 始终以 mootdx 全量列表为源端权威快照；日线只消费经 catalog 过滤后的股票池。`data_ops` 管理调度、心跳和任务结果，`mootdx_sync_runs` 记录源端参数与明细，日线状态表保留跨运行的失败历史及有界复查策略。

**Tech Stack:** Python 3.13、pytest、ClickHouse、现有 `src.data_ops` runner。

---

### Task 1: 修正 catalog 权威源与审计

**Files:**
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] **Step 1: 写入失败测试**：已有 catalog 时，`stock_catalog` 仍应保留源端新股票；结果应包含目录总数、新增数、移除数和 ST 变化数。
- [x] **Step 2: 运行单测并确认失败。**
- [x] **Step 3: 实现**：catalog 任务绕过旧 catalog 的 `symbols` 限制，全量抓取源端；比较上一快照并将审计写入 diagnostics。
- [x] **Step 4: 运行单测并确认通过。**

### Task 2: 完整日线状态机和缺口核对

**Files:**
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] **Step 1: 写入失败测试**：连续临时失败递增计数并保留首次发现时间；过期 `no_data` 自动复查；核对任务仅请求当日缺失标的。
- [x] **Step 2: 运行单测并确认失败。**
- [x] **Step 3: 实现**：读取完整最新状态，计算状态转移；新增日线缺口查询和仅补缺口的同步模式。
- [x] **Step 4: 运行单测并确认通过。**

### Task 3: 接入 data_ops

**Files:**
- Modify: `src/data_ops/models.py`
- Modify: `src/data_ops/handlers.py`
- Modify: `src/data_ops/runner.py`
- Test: `tests/test_data_ops/test_models.py`
- Test: `tests/test_data_ops/test_handlers.py`

- [x] **Step 1: 写入失败测试**：默认任务配置含 catalog、日线主同步和日线核对；handler 将调度参数映射为单一 mootdx 任务并返回其审计结果。
- [x] **Step 2: 运行单测并确认失败。**
- [x] **Step 3: 实现**：注册三项任务，配置 08:30、15:35、16:05 的交易日调度；handler 复用 `sync_mootdx_offline_data`。
- [x] **Step 4: 运行单测并确认通过。**

### Task 4: 验证与文档

**Files:**
- Modify: `docs/notes/mootdx-data-source.md`

- [x] **Step 1: 运行 mootdx、data_ops 相关完整测试集。**
- [x] **Step 2: 查询 ClickHouse，核验目录池、日线覆盖、重复与质量异常。**
- [x] **Step 3: 更新运行说明，记录自动调度、修复边界和审计字段。**
