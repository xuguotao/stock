# Tail Session V2 Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade tail-session selection from a single hard threshold into a multi-factor, layered signal system that increases observable opportunities while keeping final trade signals strict.

**Architecture:** Add a focused V2 scorer under `src/strategy/tail_session/` that wraps existing intraday signals with component scores and tiers. Keep `IntradayScanner` responsible for extracting tail-window price-volume facts, while the backend API serializes V2 tiers for the dashboard.

**Tech Stack:** Python, FastAPI backend helpers, pandas test fixtures, Vue 3 + Element Plus frontend.

---

### Task 1: V2 Scorer Model

**Files:**
- Create: `src/strategy/tail_session/v2_scorer.py`
- Test: `tests/test_strategy/test_tail_v2_scorer.py`

- [ ] Write tests for tier assignment from existing `TailSessionSignal` values:
  - strong confirmation for high volume, positive tail return, strong close location
  - observation for moderate volume or modest strength
  - weak signal for scoreable but low-quality entries
- [ ] Run `pytest tests/test_strategy/test_tail_v2_scorer.py -v` and confirm it fails because the module does not exist.
- [ ] Implement dataclasses `SignalScoreBreakdown`, `LayeredSignal`, and `score_tail_signals`.
- [ ] Run `pytest tests/test_strategy/test_tail_v2_scorer.py -v` and confirm it passes.

### Task 2: Backend Result Integration

**Files:**
- Modify: `src/web/backend/tail_live.py`
- Test: `tests/test_web/test_tail_live_api.py`

- [ ] Add a failing API test that moderate signals appear in `watchlist_signals` even when they are not final selections.
- [ ] Run the targeted test and confirm it fails because V2 fields are absent.
- [ ] Integrate `score_tail_signals` into `_write_live_selection_result`.
- [ ] Return `signal_layers`, `watchlist_signals`, `weak_signals`, and component scores on ranked rows.
- [ ] Run `pytest tests/test_web/test_tail_live_api.py -v` and confirm it passes.

### Task 3: Dashboard Display

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/TailLiveSelection.vue`

- [ ] Add TypeScript fields for V2 signal layer output.
- [ ] Show layer tags, factor scores, and summary counts in the strategy table.
- [ ] Add separate counts for final, observation, and weak signals.
- [ ] Run `npm run build` from `frontend/` and confirm it passes.

### Task 4: Verification

**Files:**
- No new files.

- [ ] Run `pytest tests/test_strategy/test_tail_v2_scorer.py tests/test_web/test_tail_live_api.py -v`.
- [ ] Run `npm run build` in `frontend/`.
- [ ] Start or reuse local backend/frontend servers and manually verify the tail selection page opens.
