# Fund Watchlist Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a ClickHouse-backed fund watchlist management UI and use that watchlist as the default input for daily fund-tail advice.

**Architecture:** Extend the existing `ClickHouseFundTailRepository` with `fund_watchlist` CRUD methods and seed behavior from static `FUNDS`. Add FastAPI endpoints in the existing fund-tail API layer, then update `FundTail.vue` to display and edit the watchlist while preserving current advice/report behavior.

**Tech Stack:** Python, FastAPI, Pydantic, ClickHouse, pandas, Vue 3, TypeScript, Element Plus, pytest, Vite.

---

### Task 1: ClickHouse Repository Watchlist CRUD

**Files:**
- Modify: `src/data/fund_tail_repository.py`
- Test: `tests/test_data/test_fund_tail_repository.py`

- [ ] **Step 1: Write failing repository tests**

Add tests that verify:

```python
def test_watchlist_crud_and_seed_from_static_funds() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseFundTailRepository(client=client)

    seeded = repo.seed_watchlist_from_static_funds({"001632": "天弘中证食品饮料ETF联接C"})
    assert seeded["inserted"] == 1

    repo.upsert_watchlist_item({
        "fund_code": "001632",
        "fund_name": "天弘中证食品饮料ETF联接C",
        "status": "holding",
        "priority": "core",
        "fund_type": "consumer",
        "enabled": True,
        "include_in_advice": True,
        "position_cost": 1.23,
        "position_amount": 5000.0,
        "position_return_pct": -0.12,
        "note": "回踩再补",
    })
    rows = repo.list_watchlist()
    assert rows[0]["fund_code"] == "001632"
    assert rows[0]["status"] == "holding"
    assert rows[0]["include_in_advice"] is True

    repo.delete_watchlist_item("001632")
    assert any("delete from fund_watchlist" in command[0].lower() for command in client.commands)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_fund_tail_repository.py::test_watchlist_crud_and_seed_from_static_funds -q`

Expected: FAIL because watchlist methods do not exist.

- [ ] **Step 3: Implement repository methods**

Add:

```python
def ensure_watchlist_table(self) -> None: ...
def list_watchlist(self) -> list[dict[str, Any]]: ...
def upsert_watchlist_item(self, item: dict[str, Any]) -> dict[str, Any]: ...
def delete_watchlist_item(self, fund_code: str) -> dict[str, Any]: ...
def seed_watchlist_from_static_funds(self, fund_names: dict[str, str], proxy_specs=None) -> dict[str, int]: ...
def advice_fund_codes_from_watchlist(self) -> list[str]: ...
```

Use `ReplacingMergeTree(updated_at)` and keep booleans as `UInt8` in ClickHouse but Python booleans in API rows.

- [ ] **Step 4: Run repository tests**

Run: `pytest tests/test_data/test_fund_tail_repository.py -q`

Expected: PASS.

### Task 2: Backend API and Advice Integration

**Files:**
- Modify: `src/web/backend/fund_tail.py`
- Modify: `src/web/backend/app.py`
- Test: `tests/test_web/test_fund_tail_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

```python
def test_fund_tail_watchlist_api_lists_and_updates_items(tmp_path) -> None:
    repository = FakeFundTailRepository(tmp_path / "fund_tail")
    app = create_app(db_path=tmp_path / "jobs.sqlite3", fund_tail_repository=repository)
    client = TestClient(app)

    response = client.get("/api/fund-tail/watchlist")
    assert response.status_code == 200

    payload = {
        "fund_code": "001632",
        "fund_name": "天弘中证食品饮料ETF联接C",
        "status": "holding",
        "priority": "core",
        "fund_type": "consumer",
        "enabled": True,
        "include_in_advice": True,
        "position_cost": 1.23,
        "position_amount": 5000,
        "position_return_pct": -0.12,
        "note": "回踩再补",
    }
    put_response = client.put("/api/fund-tail/watchlist/001632", json=payload)
    assert put_response.status_code == 200
    assert put_response.json()["item"]["status"] == "holding"
```

Also add an advice test where `fund_codes` is omitted and the fake repository returns only enabled advice codes.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web/test_fund_tail_api.py -q`

Expected: FAIL because watchlist API is missing.

- [ ] **Step 3: Implement API models and routes**

Add `FundWatchlistItemRequest` with validation for six-digit fund codes and enum-like literals. Add routes:

```python
GET /api/fund-tail/watchlist
POST /api/fund-tail/watchlist
PUT /api/fund-tail/watchlist/{code}
DELETE /api/fund-tail/watchlist/{code}
```

Update `run_local_fund_tail_advice` so omitted `fund_codes` uses repository watchlist advice codes when available.

- [ ] **Step 4: Run API tests**

Run: `pytest tests/test_web/test_fund_tail_api.py -q`

Expected: PASS.

### Task 3: Frontend API Types and FundTail Management UI

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/FundTail.vue`
- Test: `tests/test_frontend/test_fund_tail_page.py`

- [ ] **Step 1: Write failing frontend source tests**

Add assertions that `FundTail.vue` contains:

```python
assert "基金池管理" in source
assert "持有中" in source
assert "准备买入" in source
assert "参与建议" in source
assert "持仓成本" in source
assert "watchlistStatusText" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_frontend/test_fund_tail_page.py -q`

Expected: FAIL because management UI is not present.

- [ ] **Step 3: Implement frontend API and UI**

Add TypeScript types:

```ts
export interface FundWatchlistItem { ... }
export interface FundWatchlistPayload { ... }
```

Add client methods:

```ts
listFundTailWatchlist()
upsertFundTailWatchlistItem(code, payload)
deleteFundTailWatchlistItem(code)
```

Add a `FundTail.vue` panel with table, status filter, edit dialog, add dialog, save/delete handlers, and refresh after mutation.

- [ ] **Step 4: Run frontend source tests and build**

Run:

```bash
pytest tests/test_frontend/test_fund_tail_page.py -q
npm run build
```

Expected: PASS.

### Task 4: Full Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run full Python test suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`

Expected: PASS.

- [ ] **Step 3: Summarize behavior**

Confirm:

- Watchlist API can list, upsert, and delete funds.
- Daily advice defaults to enabled watchlist funds.
- Frontend can display and edit fund status, priority, type, advice inclusion, and manual position fields.
