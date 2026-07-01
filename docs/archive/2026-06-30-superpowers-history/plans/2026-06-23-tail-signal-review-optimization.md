# Tail Signal Review Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the generic strategy review page into a usable tail-session strategy review module that explains completed outcomes, pending reasons, and next-day execution performance.

**Architecture:** Keep `ClickHouseTailSignalRepository` as the review data boundary. Add repository methods for pending selected signal dates and range-based outcome recomputation, expose them through the existing review endpoint, and reshape `SignalReview.vue` around tail-strategy review progress and selected-signal execution metrics. Keep this first pass read-mostly and compatible with existing persisted signal/outcome tables.

**Tech Stack:** ClickHouse SQL, FastAPI/Pydantic, Vue 3, Element Plus, pytest, vue-tsc.

---

### Task 1: Repository Review Plan And Bulk Outcome Recompute

**Files:**
- Modify: `src/data/tail_signal_repository.py`
- Test: `tests/test_data/test_tail_signal_repository.py`

- [x] Add `pending_selected_signal_dates(start=None, end=None)` that returns selected signal dates with selected counts, completed outcome counts, and missing counts.
- [x] Add `compute_pending_selected_outcomes(start=None, end=None)` that loops pending dates and calls `compute_selected_outcomes`.
- [x] Add `review_plan` to `signal_stats()` with pending dates and total pending count.

### Task 2: API Endpoint Supports Date Range And Pending Mode

**Files:**
- Modify: `src/web/backend/app.py`
- Modify: `frontend/src/api/client.ts`
- Test: `tests/test_web/test_tail_live_api.py`

- [x] Extend `TailSignalOutcomeReviewRequest` with optional `signal_date`, `start`, `end`, and `mode`.
- [x] Keep single-date behavior for compatibility.
- [x] Add pending mode that calls `compute_pending_selected_outcomes`.

### Task 3: Page Reframe To Tail Strategy Review

**Files:**
- Modify: `frontend/src/pages/SignalReview.vue`
- Test: `tests/test_frontend/test_signal_review_page.py`

- [x] Rename title to `尾盘策略复盘`.
- [x] Add a progress panel for pending dates and missing outcome count.
- [x] Change the action button to `补算全部待复盘`.
- [x] Make summary labels focus on formal selected signals and next-day execution.

### Task 4: Verification

**Files:**
- Test: repository, API, frontend static tests.

- [x] Run `pytest tests/test_data/test_tail_signal_repository.py tests/test_web/test_tail_live_api.py tests/test_frontend/test_signal_review_page.py -q`.
- [x] Run `npm run build` in `frontend`.

### Task 5: Explainability Pass

**Files:**
- Modify: `src/data/tail_signal_repository.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/SignalReview.vue`
- Test: `tests/test_data/test_tail_signal_repository.py`
- Test: `tests/test_frontend/test_signal_review_page.py`

- [x] Add review groupings by confidence bucket, volume-ratio confirmation, and tail-return shape.
- [x] Add single-symbol explanation fields for confidence bucket, next-day execution label, and drawdown risk.
- [x] Show the new explanatory groupings and single-symbol labels on the tail strategy review page.
- [x] Run `pytest tests/test_data/test_tail_signal_repository.py tests/test_frontend/test_signal_review_page.py -q`.
- [x] Run `pytest tests/test_data/test_tail_signal_repository.py tests/test_web/test_tail_live_api.py tests/test_frontend/test_signal_review_page.py -q`.
- [x] Run `npm run build` in `frontend`.
