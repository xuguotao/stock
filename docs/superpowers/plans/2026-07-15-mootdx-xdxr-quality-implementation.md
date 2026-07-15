# Mootdx XDXR Quality Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only, operations-first XDXR quality page that exposes Mootdx XDXR run health, 30-run history, per-symbol audit detail, and a compact fact-table summary.

**Architecture:** Extend `MootdxQualityService` with isolated `mootdx_*` queries and expose two GET endpoints. Add typed API client methods and a standalone Vue route/page; the page loads a 30-run snapshot, supports status/date filtering, and opens a run-detail drawer. Reuse existing Mootdx monitor formatting and do not create write or legacy-source paths.

**Tech Stack:** Python 3, FastAPI, ClickHouse, Vue 3, TypeScript, Element Plus, pytest.

---

## File structure

- Modify `src/web/backend/mootdx_quality.py`: XDXR run/history/detail aggregation and stable empty payloads.
- Modify `src/web/backend/app.py`: read-only XDXR quality routes.
- Modify `frontend/src/api/client.ts`: response types and GET methods.
- Modify `frontend/src/router.ts`: independent XDXR quality route and navigation entry.
- Modify `frontend/src/pages/MootdxMonitor.vue`: link to the quality page.
- Create `frontend/src/pages/XdxrQuality.vue`: operations-first dashboard, filters, table, and audit drawer.
- Modify `tests/test_web/test_mootdx_quality.py`: service aggregation and empty/filter tests.
- Modify `tests/test_web/test_data_ops_tasks_api.py` or create `tests/test_web/test_mootdx_xdxr_quality_api.py`: endpoint contract tests.
- Create `tests/test_frontend/test_xdxr_quality_page.py`: route, monitor link, and page-state assertions.

### Task 1: Build read-only XDXR quality service contracts

**Files:**
- Modify `tests/test_web/test_mootdx_quality.py`
- Modify `src/web/backend/mootdx_quality.py`

- [ ] **Step 1: Write failing service tests for a populated XDXR snapshot**

Add a fake client that returns one `mootdx_sync_runs` row with `task_key='xdxr'`, JSON diagnostics, one `mootdx_xdxr_symbol_runs` status aggregate, and one fact-table summary. Assert the public payload keeps run and data facts separate:

```python
snapshot = service.xdxr_quality(limit=30)
assert snapshot["latest_run"]["status"] == "success"
assert snapshot["latest_run"]["success_symbols"] == 300
assert snapshot["runs"][0]["circuit_breaker_triggered"] is False
assert snapshot["data_summary"] == {
    "symbols": 4997, "events": 170822,
    "latest_ingested_at": "2026-07-15T12:30:23", "null_suogu": 170814,
}
```

Add a detail test:

```python
detail = service.xdxr_run_detail("run-1", status="error", limit=500)
assert detail["run_id"] == "run-1"
assert detail["items"] == [{"symbol": "000001.SZ", "status": "error", ...}]
assert "status = %(status)s" in "\n".join(client.queries)
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `pytest -q tests/test_web/test_mootdx_quality.py -k xdxr`

Expected: FAIL because `MootdxQualityService` has no XDXR quality methods.

- [ ] **Step 3: Implement stable service payloads**

Add `xdxr_quality()` and `xdxr_run_detail()` to `MootdxQualityService`. Use only:

```sql
select run_id, started_at, finished_at, status, result_json, error
from mootdx_sync_runs
where task_key = 'xdxr'
order by started_at desc
limit %(limit)s
```

and `mootdx_xdxr_symbol_runs final` for per-run rows. Decode `result_json.diagnostics.xdxr` with the existing `_json_object` helper. Normalize numeric diagnostics with `int(value or 0)` and timing with `float(value or 0)`. For no rows, return:

```python
{"latest_run": None, "runs": [], "data_summary": _empty_xdxr_data_summary()}
```

Use `max(1, min(limit, 100))` for history and `max(1, min(limit, 1000))` for detail. Apply `start_date`, `end_date`, and `status` with query parameters, never string interpolation.

- [ ] **Step 4: Run focused service tests**

Run: `pytest -q tests/test_web/test_mootdx_quality.py -k xdxr`

Expected: PASS, including populated, empty, filter, and detail cases.

- [ ] **Step 5: Commit the service slice**

```bash
git add src/web/backend/mootdx_quality.py tests/test_web/test_mootdx_quality.py
git commit -m "feat: add mootdx xdxr quality service"
```

### Task 2: Expose the XDXR quality HTTP contract

**Files:**
- Modify `src/web/backend/app.py`
- Create `tests/test_web/test_mootdx_xdxr_quality_api.py`

- [ ] **Step 1: Write failing endpoint tests**

Use `create_app` with a fake quality service. Assert parameter forwarding and detail 404 behavior:

```python
response = client.get("/api/data/mootdx/xdxr-quality?limit=30&status=failed&start_date=2026-07-01")
assert response.status_code == 200
assert service.calls[-1] == ("quality", {"limit": 30, "status": "failed", ...})

missing = client.get("/api/data/mootdx/xdxr-quality/runs/missing")
assert missing.status_code == 404
```

- [ ] **Step 2: Run the endpoint tests and confirm they fail**

Run: `pytest -q tests/test_web/test_mootdx_xdxr_quality_api.py`

Expected: FAIL with 404 because the routes do not exist.

- [ ] **Step 3: Add read-only GET routes**

Add routes next to the existing Mootdx quality endpoints:

```python
@app.get("/api/data/mootdx/xdxr-quality")
def get_mootdx_xdxr_quality(limit: int = 30, start_date: date | None = None, end_date: date | None = None, status: str | None = None):
    return app.state.mootdx_quality_service.xdxr_quality(
        limit=limit, start_date=start_date, end_date=end_date, status=status,
    )

@app.get("/api/data/mootdx/xdxr-quality/runs/{run_id}")
def get_mootdx_xdxr_run_detail(run_id: str, status: str | None = None, limit: int = 500):
    item = app.state.mootdx_quality_service.xdxr_run_detail(run_id, status=status, limit=limit)
    if item is None:
        raise HTTPException(status_code=404, detail="Mootdx XDXR run not found")
    return {"item": item}
```

- [ ] **Step 4: Run endpoint and related quality tests**

Run: `pytest -q tests/test_web/test_mootdx_xdxr_quality_api.py tests/test_web/test_mootdx_quality.py`

Expected: PASS.

- [ ] **Step 5: Commit the HTTP slice**

```bash
git add src/web/backend/app.py tests/test_web/test_mootdx_xdxr_quality_api.py
git commit -m "feat: expose mootdx xdxr quality api"
```

### Task 3: Add typed client access, route, and monitor entry

**Files:**
- Modify `frontend/src/api/client.ts`
- Modify `frontend/src/router.ts`
- Modify `frontend/src/pages/MootdxMonitor.vue`
- Create `tests/test_frontend/test_xdxr_quality_page.py`

- [ ] **Step 1: Write failing frontend architecture tests**

Assert that the new route, page import, API methods, and monitor link exist:

```python
assert "mootdx-xdxr-quality" in router_text
assert "/mootdx/xdxr-quality" in router_text
assert "getMootdxXdxrQuality" in client_text
assert "getMootdxXdxrRunDetail" in client_text
assert "XDXR 质量" in monitor_text
```

- [ ] **Step 2: Run the frontend test and confirm it fails**

Run: `pytest -q tests/test_frontend/test_xdxr_quality_page.py`

Expected: FAIL because no route or API client contract exists.

- [ ] **Step 3: Add frontend contracts and route**

Define `MootdxXdxrQualityResponse` and `MootdxXdxrRunDetail` with nullable `latest_run`, stable arrays, and numeric fields. Add:

```ts
getMootdxXdxrQuality(params: { limit?: number; startDate?: string; endDate?: string; status?: string } = {})
getMootdxXdxrRunDetail(runId: string, params: { status?: string; limit?: number } = {})
```

Add a `XdxrQuality` import, navigation item `mootdx-xdxr-quality`, and route `/mootdx/xdxr-quality`. Add a button in `MootdxMonitor.vue`:

```vue
<el-button @click="router.push({ name: 'mootdx-xdxr-quality' })">XDXR 质量</el-button>
```

- [ ] **Step 4: Run the frontend architecture test**

Run: `pytest -q tests/test_frontend/test_xdxr_quality_page.py`

Expected: PASS.

- [ ] **Step 5: Commit the frontend wiring slice**

```bash
git add frontend/src/api/client.ts frontend/src/router.ts frontend/src/pages/MootdxMonitor.vue tests/test_frontend/test_xdxr_quality_page.py
git commit -m "feat: add xdxr quality route"
```

### Task 4: Implement the operations-first XDXR quality page

**Files:**
- Create `frontend/src/pages/XdxrQuality.vue`
- Modify `tests/test_frontend/test_xdxr_quality_page.py`

- [ ] **Step 1: Write failing page-content tests**

Assert semantic page features rather than CSS details:

```python
assert "最近运行状态" in page_text
assert "近30次运行" in page_text
assert "逐标的审计" in page_text
assert "尚无 XDXR 运行记录" in page_text
assert "api.getMootdxXdxrQuality" in page_text
assert "api.getMootdxXdxrRunDetail" in page_text
```

- [ ] **Step 2: Run the page test and confirm it fails**

Run: `pytest -q tests/test_frontend/test_xdxr_quality_page.py`

Expected: FAIL because `XdxrQuality.vue` does not exist.

- [ ] **Step 3: Implement the page**

Build the approved operations-first layout:

- Header with refresh action and date/status controls.
- Four summary cards: latest run state, success/empty/error, circuit-breaker state, and timing/event count.
- A compact 30-run status/duration trend using Element Plus progress/tag primitives; do not introduce a chart dependency.
- Filterable table with started time, status, counts, event rows, total duration, and circuit-breaker tag.
- `el-drawer` detail view loading `getMootdxXdxrRunDetail`; render symbol audit rows and provide status filter.
- A data summary block for symbols, events, latest ingestion, and null `suogu` values.
- Explicit empty state when `latest_run === null`; API errors use `ElMessage.error` and retain no stale success state.

Use `onMounted(load)`, `ref` for filters and selected detail, and `Promise.allSettled` only if independent requests are added. Keep the page read-only.

- [ ] **Step 4: Run frontend tests and production build**

Run:

```bash
pytest -q tests/test_frontend/test_xdxr_quality_page.py tests/test_frontend/test_mootdx_quality_pages.py
npm --prefix frontend run build
```

Expected: all tests pass and the Vite build exits 0.

- [ ] **Step 5: Commit the page slice**

```bash
git add frontend/src/pages/XdxrQuality.vue tests/test_frontend/test_xdxr_quality_page.py
git commit -m "feat: add mootdx xdxr quality page"
```

### Task 5: Final integration verification

**Files:**
- Test: `tests/test_web/test_mootdx_quality.py`
- Test: `tests/test_web/test_mootdx_xdxr_quality_api.py`
- Test: `tests/test_frontend/test_xdxr_quality_page.py`

- [ ] **Step 1: Run focused backend and frontend verification**

Run:

```bash
pytest -q tests/test_web/test_mootdx_quality.py tests/test_web/test_mootdx_xdxr_quality_api.py tests/test_frontend/test_xdxr_quality_page.py
npm --prefix frontend run build
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Run the full regression suite**

Run: `pytest -q`

Expected: all tests pass; record existing numerical research warnings separately from failures.

- [ ] **Step 3: Verify the live read-only endpoint against local development data**

Run the backend using the project’s existing local start command, then request:

```bash
curl -s 'http://127.0.0.1:8000/api/data/mootdx/xdxr-quality?limit=30'
```

Expected: `latest_run` identifies the 300-symbol write benchmark, `runs` contains no more than 30 items, and no legacy table name appears in the response.

- [ ] **Step 4: Commit final test-only adjustments if needed**

```bash
git add tests
git commit -m "test: verify mootdx xdxr quality integration"
```
