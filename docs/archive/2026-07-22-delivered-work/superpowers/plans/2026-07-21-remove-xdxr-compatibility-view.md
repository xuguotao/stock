# 移除 XDXR 兼容视图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 `mootdx_xdxr` 兼容 View，而不降低同步、日线事件或研究复权能力。

**Architecture:** 版本日志是唯一写入层，当前投影是运营读取层，研究构建直接查询版本日志。所有 SQL 明确指向对应层，最终删除兼容名称。

**Tech Stack:** Python、ClickHouse、pytest。

---

### Task 1: 停止兼容写入与维护

**Files:** `src/data/mootdx_clickhouse_sync.py`, `tests/test_data/test_mootdx_clickhouse_sync.py`

- [ ] 写失败测试：XDXR 同步插入版本与观察表，但不插入 `mootdx_xdxr`。
- [ ] 实现：删除旧表写入分支、`ingest_seq`/nullable 列迁移及旧表 DDL；保留版本日志与观察表。
- [ ] 验证：XDXR 同步回归和一次远端显式股票同步成功。

### Task 2: 迁移运营读取

**Files:** `src/data/mootdx_clickhouse_sync.py`, `src/web/backend/mootdx_quality.py`, corresponding tests.

- [ ] 将日线事件 View 和质量查询从 `mootdx_xdxr` 改为 `mootdx_xdxr_current`。
- [ ] 验证相关 SQL 测试与远端日线事件读取。

### Task 3: 迁移研究读取并删除兼容 View

**Files:** `scripts/build_research_adjustment_data.py`, migration script and tests.

- [ ] 研究构建按成功 `ingest_seq` 从 `mootdx_xdxr_event_versions` 选择最新整行版本。
- [ ] 删除迁移器的兼容 View 创建逻辑。
- [ ] 全部回归、远端预检后执行 `DROP VIEW mootdx_xdxr`。
