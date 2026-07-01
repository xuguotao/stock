# Investment Channel Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-version REITs and options strategy modules to the existing Vue admin dashboard.

**Architecture:** Keep the first version frontend-only. Add two focused Vue pages under `frontend/src/pages/`, register them in `frontend/src/App.vue`, and cover the behavior with source-level frontend tests matching the existing test style.

**Tech Stack:** Vue 3, TypeScript, Element Plus, pytest, Vite.

---

### Task 1: Frontend Source Tests

**Files:**
- Create: `tests/test_frontend/test_investment_channel_pages.py`

- [ ] **Step 1: Write the failing tests**

Add tests that read `frontend/src/App.vue`, `frontend/src/pages/ReitsChannel.vue`, and `frontend/src/pages/OptionsStrategy.vue`.

Expected assertions:

```python
assert 'index="reits-channel"' in app
assert "REITs 配置" in app
assert "ReitsChannel" in app
assert 'index="options-strategy"' in app
assert "期权策略" in app
assert "OptionsStrategy" in app
assert "资产类型" in reits_page
assert "分红率" in reits_page
assert "候选池" in reits_page
assert "cash-secured put" in options_page
assert "covered call" in options_page
assert "naked call" in options_page
```

- [ ] **Step 2: Run the tests and verify red**

Run: `pytest tests/test_frontend/test_investment_channel_pages.py -q`

Expected: FAIL because the test file or target pages are not implemented yet.

### Task 2: Pages and Navigation

**Files:**
- Create: `frontend/src/pages/ReitsChannel.vue`
- Create: `frontend/src/pages/OptionsStrategy.vue`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Implement the REITs page**

Create a static Element Plus page with metric cards, checklist content, screening dimensions, and candidate table placeholders.

- [ ] **Step 2: Implement the options page**

Create a static Element Plus page with metric cards, eligibility checks, strategy table, and execution checklist.

- [ ] **Step 3: Register navigation**

Import both pages in `App.vue`, add two menu items, and render them by `activePage`.

- [ ] **Step 4: Run tests and build**

Run:

```bash
pytest tests/test_frontend/test_investment_channel_pages.py -q
cd frontend && npm run build
```

Expected: PASS.
