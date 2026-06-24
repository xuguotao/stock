# Tail Live Fast Data Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 今日尾盘选股 avoid blocking on full-market single-symbol 5m K-line downloads by defaulting to snapshot-first data refresh.

**Architecture:** Add an explicit `data_refresh_mode` to the tail live request. The API job will run a fast quote snapshot sync for `auto`/`snapshot` modes and only run full `minute5_kline` sync for `standard_minute5`. The scanner already reads ClickHouse intraday bars with `stock_quote_snapshots_5m FINAL` fallback, so fresh snapshot rollups become the real-time path.

**Tech Stack:** FastAPI/Pydantic, ClickHouse, Vue/Element Plus, pytest, vue-tsc.

---

### Task 1: Backend Request Mode

**Files:**
- Modify: `src/web/backend/tail_live.py`
- Modify: `src/web/backend/app.py`
- Test: `tests/test_web/test_tail_live_api.py`

- [x] Add `data_refresh_mode: Literal["auto", "snapshot", "standard_minute5", "none"] = "auto"` to `TailLiveSelectionRequest`.
- [x] Keep `auto_sync_minute5` for compatibility, but treat it as legacy.
- [x] In `_run_tail_live_selection_job`, run `quote_snapshot_runner(limit=0, include_st=False)` for `auto` and `snapshot` modes.
- [x] Run `minute5_runner(...)` only when mode is `standard_minute5`.
- [x] Add diagnostics `quote_snapshot_sync`, `data_refresh_mode`, and `effective_data_refresh_mode`.

### Task 2: Frontend Mode Selector

**Files:**
- Modify: `frontend/src/pages/TailLiveSelection.vue`
- Modify: `frontend/src/api/client.ts`
- Test: frontend static tests if present.

- [x] Replace the binary “运行前补数据” switch with a selector: 自动快速、快照优先、标准5m、关闭刷新.
- [x] Default to `auto`.
- [x] Update helper text so users know standard 5m is slower.

### Task 3: Verification

**Files:**
- Test: `tests/test_web/test_tail_live_api.py`
- Test: `tests/test_frontend/test_tail_live_selection_page.py` or existing frontend test files.

- [x] Verify snapshot mode does not call `minute5_runner`.
- [x] Verify standard mode still calls `minute5_runner`.
- [x] Run targeted pytest and `npm run build`.
