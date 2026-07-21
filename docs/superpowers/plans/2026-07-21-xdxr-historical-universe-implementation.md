# XDXR 历史全股票池修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 XDXR 同步覆盖含 ST 与停用股票的历史目录，而不改变日线或策略股票池。

**Architecture:** 同步入口继续先解析默认策略池；仅在执行 `xdxr` 任务、且用户没有显式股票列表时，单独解析历史 XDXR 池。之后用旧表与投影的差异股票做一次小范围补抓并重新核验。

**Tech Stack:** Python、ClickHouse、pytest、Mootdx。

---

### Task 1: 分离 XDXR 历史目标池

**Files:**

- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [ ] **Step 1: 写失败测试**

```python
def test_xdxr_uses_catalog_pool_including_st_and_inactive_without_widening_daily_pool() -> None:
    result = sync_mootdx_offline_data(tasks=["stock_kline_daily", "xdxr"], symbols=None, ...)
    assert source.daily_symbols == ["000001.SZ"]
    assert source.xdxr_symbols == ["000001.SZ", "002598.SZ", "000004.SZ"]
```

- [ ] **Step 2: 验证红灯**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k xdxr_uses_catalog_pool`

Expected: FAIL，因为 XDXR 仍使用非 ST、活跃的默认池。

- [ ] **Step 3: 实现最小分离**

为 `_latest_catalog_symbols` 增加 `include_st` 与 `include_inactive` 选项，默认值保持 `False`。在同步任务循环中，仅为无显式 `symbols` 的 `xdxr` 任务调用该函数的全包含模式；其他任务继续传原始默认池。

- [ ] **Step 4: 绿灯与回归**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr or stock_kline_daily_uses_latest_catalog_pool'`

### Task 2: 差异股票补抓与核验

**Files:**

- Modify: `scripts/migrate_xdxr_three_layer.py`
- Test: `tests/test_scripts/test_migrate_xdxr_three_layer.py`

- [ ] **Step 1: 增加只读差异股票提取函数与测试**

```python
def legacy_only_symbols(client) -> list[str]:
    return ["000004.SZ", "002598.SZ"]
```

- [ ] **Step 2: 使用该列表进行一次显式 XDXR 同步**

Run against the configured production ClickHouse and Mootdx source. Record the new `run_id`; do not execute table rename.

- [ ] **Step 3: dry-run 复核**

Run: `python scripts/migrate_xdxr_three_layer.py --dry-run --baseline-run-id <run_id>`

Expected: zero business-key and content differences before any cutover is considered.
