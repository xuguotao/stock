# Web Data Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dashboard data center that lets the backend and Vue UI inspect local research datasets.

**Architecture:** Keep dataset inspection behind a focused backend module that scans parquet datasets and nearby manifest JSON files. FastAPI exposes list/detail endpoints; Vue consumes those endpoints through the existing API client and renders a compact operations page.

**Tech Stack:** Python, FastAPI, pandas/pyarrow parquet, pytest, Vue 3, Element Plus, TypeScript.

---

### Task 1: Dataset API

**Files:**
- Create: `src/web/backend/datasets.py`
- Modify: `src/web/backend/app.py`
- Test: `tests/test_web/test_datasets_api.py`

- [x] Write tests for listing parquet datasets and reading one dataset detail.
- [x] Run `pytest tests/test_web/test_datasets_api.py -q` and verify it fails because `/api/datasets` does not exist.
- [x] Implement `DatasetService` with manifest-aware summaries and symbol sampling.
- [x] Register `GET /api/datasets` and `GET /api/datasets/{dataset_id}` in the app factory.
- [x] Run `pytest tests/test_web/test_datasets_api.py -q` and verify it passes.

### Task 2: Data Center UI

**Files:**
- Create: `frontend/src/pages/DataCenter.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/styles.css`

- [x] Add typed API client methods for dataset list/detail responses.
- [x] Add a sidebar entry and render the data center page.
- [x] Show dataset cards/table, selected dataset detail, manifest metadata, and symbol tags.
- [x] Run `cd frontend && npm run build` and verify it passes.

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

- [x] Document the new data center page and dataset endpoints.
- [x] Run `pytest -q`.
- [x] Run `cd frontend && npm run build`.
- [x] Run `git diff --check`.
- [x] Commit the data center change.
