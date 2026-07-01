# Data Center Health Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a data health operations console to the existing Data Center page showing each dataset's update mechanism, status, completeness, and impact.

**Architecture:** Extend the existing `/api/data/status` response with a derived `datasets_health` list from current ClickHouse table stats, quality checks, and monitor-facing metadata. Render that list in the Vue Data Center using the existing Element Plus panel/table patterns without changing ingestion jobs.

**Tech Stack:** FastAPI backend, ClickHouse status inspection, Vue 3 Composition API, Element Plus, pytest/static frontend tests.

---

### Task 1: Backend Dataset Health Model

**Files:**
- Modify: `src/web/backend/data_status.py`
- Test: `tests/test_web/test_clickhouse_data_status.py`

- [ ] Add `datasets_health` to `inspect_clickhouse_database()`.
- [ ] Each item includes `key`, `name`, `category`, `source`, `update_mechanism`, `consumer`, `latest`, `range`, `rows`, `symbols`, `expected_symbols`, `coverage_ratio`, `status`, `issues`.
- [ ] Cover daily, minute1, minute5, raw quote snapshots, quote 1m/5m rollups, index, financials, data_source_health, fund NAV, fund proxy, benchmark if tables exist.
- [ ] Add tests asserting representative rows and status mapping.

### Task 2: Frontend Health Matrix

**Files:**
- Modify: `frontend/src/pages/DataCenter.vue`
- Modify: `frontend/src/api/client.ts`
- Test: `tests/test_frontend/test_data_center_page.py`

- [ ] Add TypeScript types for `datasets_health`.
- [ ] Add a Data Health Matrix panel with columns: data, purpose, update mechanism, latest/range, completeness, status.
- [ ] Add expandable details for source, consumer, issue text, and row/symbol counts.
- [ ] Keep current overview, task monitor, quality center, and manual maintenance controls.

### Task 3: Verify End-to-End

**Files:**
- No new files.

- [ ] Run targeted backend/frontend tests.
- [ ] Run full `pytest -q`.
- [ ] Run frontend build if TypeScript changed.
- [ ] Query real `/api/data/status`-equivalent function once to confirm dataset rows are populated.
