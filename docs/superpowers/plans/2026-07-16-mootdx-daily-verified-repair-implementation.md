# Mootdx 日线核验后精准回补 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 核验后一次回补 Baostock 已确认存在的缺失交易日，自动排除无数据日期。

**Architecture:** 后端质量服务在每个缺口块返回逐日 verdict；前端以纯 payload helper 从 `available` 日期构造多个单日 repair item，复用已有回补 API。

**Tech Stack:** Python/FastAPI/ClickHouse，Vue 3/TypeScript，pytest。

---

### Task 1: 暴露缺口块逐日核验 verdict

**Files:**
- Modify: `src/web/backend/mootdx_quality.py`
- Test: `tests/test_web/test_mootdx_quality.py`

- [ ] Write a failing service test where one block has `available` and `no_data` verdicts; assert returned detail contains a date-to-verdict mapping restricted to block dates.
- [ ] Run `pytest -q tests/test_web/test_mootdx_quality.py -k verification` and verify RED.
- [ ] Add the minimal serializable field (for example `verification_by_date`) to each missing detail using existing `verification_by_symbol` data.
- [ ] Re-run focused service tests and commit `feat: expose daily gap verification verdicts`.

### Task 2: 一键精准回补 payload 与页面

**Files:**
- Modify: `frontend/src/features/mootdx/dailyGapPayloads.ts`
- Modify: `frontend/src/pages/DailyKlineQuality.vue`
- Test: `tests/test_frontend/test_mootdx_quality_pages.py`

- [ ] Write a failing behavior test with a 28-day block containing 27 `available` and one `no_data`; assert precise repair payload has 27 one-day items and excludes the no-data date.
- [ ] Run focused test to verify RED.
- [ ] Add typed pure helper to create precise repair items from `verification_by_date`, preserving existing repair and verify helpers.
- [ ] Render available/no-data counts and a `创建精准回补（N 日）` action; hide/disable it without available dates. Call existing repair job endpoint with precise items.
- [ ] Re-run focused test and commit `feat: add verified daily gap repair action`.

### Task 3: 验证与集成

**Files:**
- No production changes expected

- [ ] Run `pytest -q tests/test_web/test_mootdx_quality.py tests/test_web/test_data_ops_tasks_api.py tests/test_frontend/test_mootdx_quality_pages.py`.
- [ ] Run `npm run build` in the main worktree after merge if the isolated worktree lacks node modules.
- [ ] Run `git diff --check`, complete spec and code reviews, merge only after all checks pass.
