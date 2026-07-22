# Mootdx 运维可信度改进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让日线缺口核验、Mootdx 任务失败和手动触发等待状态在页面与审计中准确一致。

**Architecture:** 日线质量页从单日请求改为提交缺口对象的完整日期块，复用后端现有区间核验与逐日 verdict 写入。data-ops 状态层把待消费的 `manual_trigger` 投影为 `queued`，并通过 runner 集成测试保证内层 `failed` 不会被记录为成功。

**Tech Stack:** Python/FastAPI/ClickHouse data-ops runner，Vue 3/TypeScript/Element Plus，pytest。

---

### Task 1: 块级 Baostock 核验请求

**Files:**
- Modify: `frontend/src/pages/DailyKlineQuality.vue`
- Test: `tests/test_frontend/test_daily_quality_page.py` (create if absent)

- [ ] **Step 1: Write the failing page-contract test**

```python
def test_daily_quality_verify_submits_complete_missing_block() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text()
    assert "start_date: item.missing_dates[0]" in source
    assert "end_date: item.missing_dates.at(-1)" in source
```

- [ ] **Step 2: Run it to verify failure**

Run: `pytest -q tests/test_frontend/test_daily_quality_page.py -k complete_missing_block`

Expected: FAIL because the payload currently uses `selectedTradeDate` for both bounds.

- [ ] **Step 3: Implement the minimal block-range payload**

Replace the payload builder so each selected item sends its own `missing_dates[0]` and final missing date. Keep `evidence` unchanged and do not change repair payload selection behavior.

- [ ] **Step 4: Run page-contract test**

Run: `pytest -q tests/test_frontend/test_daily_quality_page.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DailyKlineQuality.vue tests/test_frontend/test_daily_quality_page.py
git commit -m "fix: verify complete Mootdx daily gap blocks"
```

### Task 2: 内层同步失败的 runner 审计

**Files:**
- Modify: `src/data_ops/handlers.py` only if the failing test exposes a missing propagation path
- Modify: `src/data_ops/runner.py` only if the failing test exposes a status-recording path
- Test: `tests/test_data_ops/test_handlers.py`
- Test: `tests/test_data_ops/test_runner.py`

- [ ] **Step 1: Write a failing handler test for a returned `failed` map**

```python
def test_mootdx_handler_raises_when_inner_sync_returns_failed() -> None:
    handler = build_default_handlers(
        mootdx_sync_runner=lambda **_: {"tasks": ["stock_catalog"], "failed": {"stock_catalog": "AttributeError: bad code"}},
    )["mootdx_stock_catalog_sync"]
    with pytest.raises(RuntimeError, match="stock_catalog.*AttributeError"):
        handler({"trade_date": "2026-07-16"})
```

- [ ] **Step 2: Write a runner integration test**

Use an in-memory repository and the real `DataOpsRunner`; make the handler raise the same error and assert the latest run has `status == "failed"` and an error containing `AttributeError`.

- [ ] **Step 3: Run tests to verify the failure path**

Run: `pytest -q tests/test_data_ops/test_handlers.py -k inner_sync_returns_failed tests/test_data_ops/test_runner.py -k mootdx`

Expected: failure if current behavior can record a success for an inner failure.

- [ ] **Step 4: Implement the narrowest propagation fix**

Make `run_mootdx_sync()` raise whenever `result.get("failed")` is non-empty, preserving the selected task reason; do not convert the result into a success payload. Ensure `DataOpsRunner.run_once()` records that exception through its existing failed-run path.

- [ ] **Step 5: Run focused and full data-ops tests**

Run: `pytest -q tests/test_data_ops/test_handlers.py tests/test_data_ops/test_runner.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/data_ops/handlers.py src/data_ops/runner.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_runner.py
git commit -m "fix: record failed Mootdx inner syncs"
```

### Task 3: 显示手动任务排队状态

**Files:**
- Modify: `src/data_ops/models.py`
- Modify: `src/data_ops/repository.py`
- Modify: `src/web/backend/data_reliability.py` if status mappings require `queued`
- Modify: `frontend/src/features/mootdx/formatters.ts`
- Modify: `frontend/src/pages/MootdxMonitor.vue`
- Test: `tests/test_data_ops/test_repository.py`
- Test: `tests/test_frontend/test_mootdx_monitor.py` (create if absent)

- [ ] **Step 1: Write a failing repository status test**

Create an enabled `DataOpsTaskConfig` with `manual_trigger=True`, no run and no running heartbeat. Assert `list_task_statuses()` returns `status == "queued"`. Add a companion assertion that a running heartbeat wins and returns `running`.

- [ ] **Step 2: Run it to verify failure**

Run: `pytest -q tests/test_data_ops/test_repository.py -k queued`

Expected: FAIL because the current status is `idle`.

- [ ] **Step 3: Add `queued` to the model and status projection**

Add `queued` to `VALID_TASK_STATUSES`. In `list_task_statuses()`, after applying heartbeat status but before stale detection, use `queued` when `config.manual_trigger` is true and the task is not running. Preserve `running` for a running heartbeat.

- [ ] **Step 4: Add frontend presentation test and implementation**

Assert the formatter maps `queued` to `等待 runner 接管` and `MootdxMonitor.vue` renders that status through the existing formatter. Add the mapping without altering existing status labels.

- [ ] **Step 5: Run focused tests**

Run: `pytest -q tests/test_data_ops/test_repository.py -k queued tests/test_frontend/test_mootdx_monitor.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/data_ops/models.py src/data_ops/repository.py src/web/backend/data_reliability.py frontend/src/features/mootdx/formatters.ts frontend/src/pages/MootdxMonitor.vue tests/test_data_ops/test_repository.py tests/test_frontend/test_mootdx_monitor.py
git commit -m "feat: expose queued Mootdx manual tasks"
```

### Task 4: 完整验证与真实 API 检查

**Files:**
- No production changes expected

- [ ] **Step 1: Run all directly affected tests**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_runner.py tests/test_data_ops/test_repository.py tests/test_web/test_mootdx_quality.py tests/test_web/test_data_ops_tasks_api.py tests/test_frontend/test_daily_quality_page.py tests/test_frontend/test_mootdx_monitor.py`

Expected: PASS.

- [ ] **Step 2: Build frontend**

Run: `npm run build` in `frontend/`

Expected: successful Vite build; existing Rollup chunk warnings may remain.

- [ ] **Step 3: Inspect diff and commit verification note if source changes remain**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and clean worktree after commits.
