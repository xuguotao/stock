# mootdx catalog 与日线质量页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 mootdx catalog 和日线提供可追溯的质量统计、完整度和健康详情页。

**Architecture:** catalog 同步将变化写入 append-only 事件表；监控服务读取事件、catalog、日线、交易日历和上市日期并生成只读快照；前端展示快照并复用 data_ops 手工触发入口。

**Tech Stack:** Python、ClickHouse、FastAPI、Vue 3、Element Plus、pytest。

---

### Task 1: catalog 变更事件

**Files:** `src/data/mootdx_clickhouse_sync.py`, `tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] 写失败测试，断言新增与 ST/名称变化会写入 `mootdx_catalog_change_events`。
- [x] 创建 append-only 表和事件行生成逻辑。
- [x] 运行测试验证写入。

### Task 2: 质量统计服务和 API

**Files:** `src/web/backend/mootdx_monitor.py`, `src/web/backend/app.py`, `tests/test_web/test_mootdx_quality.py`

- [x] 写失败测试，覆盖 catalog 变更统计、日线按上市日期起算的完整度和读取降级。
- [x] 实现 catalog 与日线质量快照。
- [x] 暴露两个 API 并运行测试。

### Task 3: Vue 详情页

**Files:** `frontend/src/api/client.ts`, `frontend/src/router.ts`, `frontend/src/pages/CatalogQuality.vue`, `frontend/src/pages/DailyKlineQuality.vue`, `frontend/src/pages/MootdxMonitor.vue`

- [x] 添加 API 类型和客户端方法。
- [x] 新建质量页、路由和根监控入口。
- [x] 执行 `npm run build`，并用浏览器检查数据加载。
