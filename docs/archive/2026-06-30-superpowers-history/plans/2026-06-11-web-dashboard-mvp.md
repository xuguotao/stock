# Web Dashboard MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI + Vue + ECharts dashboard MVP that can submit tail-session backtest jobs, view job status, and visualize backtest metrics.

**Architecture:** FastAPI exposes job and backtest APIs backed by a lightweight legacy local DB metadata store and an in-process background runner. Services wrap existing `src.strategy.tail_session` and `BacktestEngine` modules instead of reimplementing strategy logic. Vue 3 + Vite + ECharts provides a work-focused admin UI with dashboard, jobs, and backtest pages.

**Tech Stack:** Python 3.12+, FastAPI, legacy local DB standard library, pytest, Vue 3, TypeScript, Vite, ECharts, Element Plus.

---

### Task 1: Backend Job Store And API

**Files:**
- Create: `src/web/__init__.py`
- Create: `src/web/backend/__init__.py`
- Create: `src/web/backend/jobs.py`
- Create: `src/web/backend/app.py`
- Test: `tests/test_web/test_jobs_api.py`

- [ ] **Step 1: Write failing tests**

```python
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_jobs_api_creates_and_lists_jobs(tmp_path):
    app = create_app(db_path=tmp_path / "jobs.legacy_local_db3")
    client = TestClient(app)

    created = client.post("/api/jobs", json={"kind": "noop", "params": {"x": 1}}).json()
    listed = client.get("/api/jobs").json()

    assert created["kind"] == "noop"
    assert created["status"] == "pending"
    assert listed["items"][0]["id"] == created["id"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_web/test_jobs_api.py -q`
Expected: FAIL because `src.web.backend.app` does not exist.

- [ ] **Step 3: Implement job store and API**

Create a legacy local DB-backed `JobStore` with `create_job`, `list_jobs`, `get_job`, and `update_job`. Create FastAPI routes `POST /api/jobs`, `GET /api/jobs`, and `GET /api/jobs/{job_id}`.

- [ ] **Step 4: Verify**

Run: `pytest tests/test_web/test_jobs_api.py -q`
Expected: PASS.

### Task 2: Tail Backtest Job Runner

**Files:**
- Create: `src/web/backend/backtests.py`
- Modify: `src/web/backend/app.py`
- Test: `tests/test_web/test_backtests_api.py`

- [ ] **Step 1: Write failing tests**

```python
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_backtest_api_runs_with_inline_sample_dataset(tmp_path):
    app = create_app(db_path=tmp_path / "jobs.legacy_local_db3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post("/api/backtests/tail-session", json={
        "start": "2025-01-01",
        "end": "2025-02-28",
        "capital": 100000,
        "top_n": 2,
        "sample": True,
    })

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert "metrics" in job["result"]
    assert "equity_curve" in job["result"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_web/test_backtests_api.py -q`
Expected: FAIL because backtest route does not exist.

- [ ] **Step 3: Implement service**

Add `TailBacktestRequest`, route `POST /api/backtests/tail-session`, and a runner that can use either a provided dataset path or a deterministic sample dataset for UI smoke tests.

- [ ] **Step 4: Verify**

Run: `pytest tests/test_web/test_backtests_api.py -q`
Expected: PASS.

### Task 3: Vue Dashboard MVP

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/Dashboard.vue`
- Create: `frontend/src/pages/Jobs.vue`
- Create: `frontend/src/pages/TailBacktest.vue`

- [ ] **Step 1: Create Vite Vue app structure**

Use Vue 3, TypeScript, Element Plus, ECharts, and a proxy from `/api` to `http://127.0.0.1:8000`.

- [ ] **Step 2: Implement pages**

Dashboard shows system cards and latest jobs. TailBacktest submits a job and renders metrics plus equity/drawdown charts. Jobs lists job statuses and errors.

- [ ] **Step 3: Verify frontend**

Run: `npm install` then `npm run build` in `frontend/`.
Expected: build succeeds.

### Task 4: Documentation And Run Commands

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Document commands**

Backend: `uvicorn src.web.backend.app:app --reload`.
Frontend: `cd frontend && npm install && npm run dev`.

- [ ] **Step 2: Full verification**

Run: `pytest -q` and `cd frontend && npm run build`.
Expected: all tests pass and frontend builds.
