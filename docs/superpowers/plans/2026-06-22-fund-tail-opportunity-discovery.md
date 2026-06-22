# Fund Tail Opportunity Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-version fund tail opportunity discovery workflow that ranks a broader configured candidate pool and lets the dashboard add selected opportunities to the existing watchlist.

**Architecture:** Add a pure research module that reads candidate definitions, reuses the existing fund-tail signal engine, applies opportunity-specific category and risk labels, and writes Chinese CSV/Markdown reports. Expose the workflow through the existing FastAPI fund-tail backend and add a dashboard panel with sortable opportunity rows and an add-to-watchlist action.

**Tech Stack:** Python, pandas, FastAPI, pytest, Vue 3, Element Plus, TypeScript.

---

### Task 1: Research Core

**Files:**
- Create: `src/research/fund_tail_opportunities.py`
- Create: `config/fund_tail_candidates.csv`
- Test: `tests/test_research/test_fund_tail_opportunities.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research/test_fund_tail_opportunities.py` with tests for candidate loading, exclusion filtering, action grouping, and adding watchlist status.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_research/test_fund_tail_opportunities.py`
Expected: FAIL because `src.research.fund_tail_opportunities` does not exist.

- [ ] **Step 3: Implement minimal research core**

Implement:
- `FundCandidate` dataclass.
- `load_candidates(path)`.
- `filter_eligible_candidates(candidates)`.
- `classify_opportunity(row, candidate, watchlist_codes)`.
- `build_opportunity_rows(chinese_report, candidates, watchlist_codes)`.

The output must include Chinese fields: `机会类型`, `机会等级`, `机会建议`, `机会原因`, `是否已在观察池`, `费率标签`, `最短观察周期`, `候选层级`.

- [ ] **Step 4: Run tests**

Run: `pytest -q tests/test_research/test_fund_tail_opportunities.py`
Expected: PASS.

### Task 2: Script and API

**Files:**
- Create: `scripts/discover_fund_tail_opportunities.py`
- Modify: `src/web/backend/fund_tail.py`
- Modify: `src/web/backend/app.py`
- Modify: `frontend/src/api/client.ts`
- Test: `tests/test_scripts/test_fund_tail_opportunities.py`
- Test: `tests/test_web/test_fund_tail_api.py`

- [ ] **Step 1: Write failing tests**

Add tests that:
- The script writes `reports/fund_tail_opportunities.csv`.
- The API returns opportunity rows.
- The API can add an opportunity to the existing watchlist through the existing watchlist endpoint shape.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_scripts/test_fund_tail_opportunities.py tests/test_web/test_fund_tail_api.py`
Expected: FAIL because the script and API route do not exist.

- [ ] **Step 3: Implement script and backend route**

Implement:
- `scripts/discover_fund_tail_opportunities.py` for CSV/local data mode.
- `FundTailOpportunityRequest`.
- `run_local_fund_tail_opportunities`.
- `GET /api/fund-tail/opportunities/latest`.
- `POST /api/fund-tail/opportunities`.

The backend should reuse existing report generation functions and persist files under `reports/fund_tail_opportunities.csv` and `reports/fund_tail_opportunities/latest.md`.

- [ ] **Step 4: Run tests**

Run: `pytest -q tests/test_scripts/test_fund_tail_opportunities.py tests/test_web/test_fund_tail_api.py`
Expected: PASS.

### Task 3: Dashboard Panel

**Files:**
- Modify: `frontend/src/pages/FundTail.vue`
- Modify: `frontend/src/api/client.ts`
- Test: `tests/test_frontend/test_fund_tail_page.py`

- [ ] **Step 1: Write failing frontend test**

Update `tests/test_frontend/test_fund_tail_page.py` to assert the page includes `机会发现`, `机会类型`, `机会等级`, and `加入观察池`.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest -q tests/test_frontend/test_fund_tail_page.py`
Expected: FAIL because the page does not show opportunity discovery yet.

- [ ] **Step 3: Implement dashboard panel**

Add:
- Opportunity API types and client functions.
- New panel under the existing advice table.
- Generate opportunities button.
- Table columns for opportunity type, grade, suggestion, score, 5-day win rate, 5-day median return, 5-day down >2% probability, proxy fit, and action.
- Add-to-watchlist action that pre-fills `candidate` status and submits through the existing watchlist API.

- [ ] **Step 4: Run tests**

Run: `pytest -q tests/test_frontend/test_fund_tail_page.py`
Expected: PASS.

### Task 4: Verification and Commit

**Files:**
- Verify all files touched by Tasks 1-3.

- [ ] **Step 1: Run focused backend tests**

Run: `pytest -q tests/test_research/test_fund_tail_opportunities.py tests/test_scripts/test_fund_tail_opportunities.py tests/test_web/test_fund_tail_api.py tests/test_frontend/test_fund_tail_page.py`
Expected: PASS.

- [ ] **Step 2: Run script smoke test**

Run: `python scripts/discover_fund_tail_opportunities.py --trade-date 2026-06-22 --data-dir data/fund_tail --candidate-file config/fund_tail_candidates.csv --report reports/fund_tail_opportunities.csv --markdown reports/fund_tail_opportunities/latest.md`
Expected: exit 0 and a Chinese report file.

- [ ] **Step 3: Inspect git diff**

Run: `git diff --stat`
Expected: only files related to fund opportunity discovery changed.

- [ ] **Step 4: Commit**

Run:
```bash
git add config/fund_tail_candidates.csv scripts/discover_fund_tail_opportunities.py src/research/fund_tail_opportunities.py src/web/backend/fund_tail.py src/web/backend/app.py frontend/src/api/client.ts frontend/src/pages/FundTail.vue tests/test_research/test_fund_tail_opportunities.py tests/test_scripts/test_fund_tail_opportunities.py tests/test_web/test_fund_tail_api.py tests/test_frontend/test_fund_tail_page.py docs/superpowers/plans/2026-06-22-fund-tail-opportunity-discovery.md
git commit -m "feat: add fund tail opportunity discovery"
```
