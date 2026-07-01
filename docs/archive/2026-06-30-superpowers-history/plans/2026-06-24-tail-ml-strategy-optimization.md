# Tail ML Strategy Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a controlled historical-training pipeline that improves tail-session stock selection win rate and expected return without overfitting or silently drifting away from executable trading rules.

**Architecture:** Keep ClickHouse as the canonical source. Build a reproducible dataset layer first, then baseline the current rule strategy, then train a simple interpretable model with walk-forward validation before wiring inference into 今日尾盘选股. Every model version must record training window, feature set, label definition, validation metrics, and data-quality checks.

**Tech Stack:** ClickHouse, pandas, scikit-learn/LightGBM-compatible tabular pipeline, FastAPI, Vue/ECharts, pytest.

---

## Current Data Readiness Snapshot

Checked on 2026-06-24 against ClickHouse `stock`:

- `daily_kline`: 7,252,052 rows, 5,207 symbols, range `2020-01-02 / 2026-06-24`.
- Recent daily coverage: `2026-06-22` 4,966 symbols, `2026-06-23` 4,966, `2026-06-24` 4,965.
- Historical daily OHLC invalid rows remain: 1,203 rows. These must be filtered out or re-imported before long-horizon training.
- `minute5_kline`: 25,747,349 rows, 4,991 symbols, range `2026-01-08 09:35 / 2026-06-24 15:00`.
- Full-market 5m trading days with usable coverage: about 108 days.
- Tail-window 5m rows by month:
  - 202601: 17 days / 4,947 symbols
  - 202602: 14 days / 4,952 symbols
  - 202603: 22 days / 4,957 symbols
  - 202604: 21 days / 4,982 symbols
  - 202605: 18 days / 4,981 symbols
  - 202606: 17 days / 4,989 symbols
- Joinable 5m signal-day to next-session daily-label days: about 89 days.
- `stock_quote_snapshots`: starts `2026-06-17`; good for real-time inference and short recent replay, not enough for model training history.
- `tail_selection_signals`: 12,091 rows over 6 signal dates only.
- `tail_signal_outcomes`: 33 rows over 6 signal dates only.
- Strategy-tradable daily pool over recent year: about 4,936 symbols.

Conclusion:

- Daily features are ready for multi-year training after filtering invalid OHLC rows.
- Tail 5m intraday features are usable for a first model but only cover about five months, so validation must be conservative.
- Existing selected-signal outcomes are too sparse for supervised training; they are only a baseline/audit source.
- The first ML version should train from reconstructed historical daily + 5m samples, not from current selected-signal rows.

---

## Non-Negotiable Guardrails

- [ ] No random train/test split. Use chronological walk-forward validation only.
- [ ] No model promotion unless it beats the current rule baseline on the same dates and execution assumptions.
- [ ] No feature may use future data relative to the simulated decision time.
- [ ] No label may use same-day close if the decision is supposed to happen before close unless the mode explicitly says `close_decision`.
- [ ] Near-limit-up, ST, suspended, zero-volume, and illiquid names must be excluded before scoring.
- [ ] Every model run must persist model version, feature list, label definition, training window, validation window, and metrics.
- [ ] UI recommendations must show data freshness, model version, expected return, win probability, drawdown risk, and top feature reasons.

---

### Task 1: Dataset Audit API And CLI

**Files:**
- Create: `src/ml/tail_dataset_audit.py`
- Create: `tests/test_ml/test_tail_dataset_audit.py`
- Modify: `src/web/backend/app.py`
- Modify: `frontend/src/pages/DataCenter.vue`

- [x] Add a function `audit_tail_ml_data(client=None, as_of=None)` that returns daily, minute5, snapshot, signal, outcome, and tradable-pool readiness.
- [x] Include `status` values: `ready`, `limited`, `blocked`.
- [x] Mark ML training as `limited` when 5m coverage is less than 180 trading days.
- [x] Add tests with a fake ClickHouse client for current observed shape.
- [x] Expose `GET /api/ml/tail/audit`.
- [x] Show the audit in 数据中心 under a new “尾盘模型训练数据” section.

### Task 2: Historical Sample Builder

**Files:**
- Create: `src/ml/tail_features.py`
- Create: `src/ml/tail_labels.py`
- Create: `src/ml/tail_dataset.py`
- Create: `tests/test_ml/test_tail_dataset.py`

- [x] Build one sample per `(trade_date, symbol, decision_time)` using only data available at or before the decision time.
- [x] First supported decision times: `14:30`, `14:35`, `14:40`, `14:45`, `14:50`, `14:55`.
- [ ] Feature groups:
  - Daily trend: 5d/10d/20d return, volatility, moving-average distance.
  - Tail intraday: 14:30+ return, last 3/6 bar slope, volume expansion, pullback from high.
  - Liquidity/executability: amount, volume, near-limit-up distance, zero-volume flags.
  - Market context: market breadth, index return if available.
- [ ] Labels:
  - `next_open_return`
  - `next_high_return`
  - `next_close_return`
  - `next_low_return`
  - `hit_next_high_1pct`
  - `drawdown_breach_2pct`
- [x] Write the dataset to ClickHouse table `tail_ml_samples` or parquet cache only after row count and null-rate checks pass.

### Task 3: Current Rule Baseline

**Files:**
- Create: `src/ml/tail_rule_baseline.py`
- Create: `tests/test_ml/test_tail_rule_baseline.py`
- Modify: `src/web/backend/tail_replay_backtest.py` if existing logic can be reused safely.

- [ ] Run the current rule strategy over the reconstructed historical sample dates.
- [ ] Produce metrics for Top1/Top2/Top3:
  - selected days
  - empty days
  - next-open win rate
  - next-high > 1% hit rate
  - avg next-open return
  - avg next-high return
  - avg next-low drawdown
  - max consecutive losing selections
- [ ] Persist the baseline report as `tail_ml_baseline_runs`.
- [ ] This baseline becomes the minimum bar for model promotion.

### Task 4: First Model Training

**Files:**
- Create: `src/ml/tail_model.py`
- Create: `src/ml/tail_walk_forward.py`
- Create: `tests/test_ml/test_tail_model.py`

- [ ] Start with `HistGradientBoostingClassifier/Regressor` from scikit-learn to avoid external dependency risk.
- [ ] If LightGBM is installed, allow optional LightGBM backend behind a config flag.
- [ ] Train separate outputs:
  - probability of `hit_next_high_1pct`
  - expected `next_high_return`
  - risk probability of `drawdown_breach_2pct`
- [ ] Combine into score:
  - `score = 0.45 * hit_prob + 0.35 * expected_high_return_z - 0.20 * risk_prob`
- [ ] Use walk-forward splits only.
- [ ] Persist model artifacts under `models/tail_session/<version>/`.
- [ ] Persist validation metrics to ClickHouse table `tail_ml_model_runs`.

### Task 5: Model Evaluation Page

**Files:**
- Create: `frontend/src/pages/TailModelLab.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/api/client.ts`
- Modify: `src/web/backend/app.py`
- Create: `tests/test_frontend/test_tail_model_lab_page.py`

- [ ] Show model run list with version, training window, validation window, sample count, selected days, and metrics.
- [ ] Show comparison table: model vs current rule baseline.
- [ ] Show feature importance.
- [ ] Show walk-forward monthly performance.
- [ ] Show failure cases: high score but loss, low score but missed winner.

### Task 6: Live Inference Integration

**Files:**
- Create: `src/ml/tail_inference.py`
- Modify: `src/web/backend/tail_live.py`
- Modify: `frontend/src/pages/TailLiveSelection.vue`
- Create: `tests/test_ml/test_tail_inference.py`
- Modify: `tests/test_web/test_tail_live_api.py`

- [ ] Add request option `strategy_mode: rule | model | hybrid`.
- [ ] Default initially stays `rule` until model beats baseline.
- [ ] In `model` mode, score current candidates with the latest promoted model.
- [ ] In `hybrid` mode, require rule eligibility first, then model ranking.
- [ ] Add per-symbol explanation:
  - model score
  - hit probability
  - expected high return
  - risk probability
  - top feature contributions or nearest feature deltas
- [ ] Show model version and data freshness on 今日尾盘选股.

### Task 7: Promotion Gate

**Files:**
- Create: `src/ml/tail_model_registry.py`
- Create: `tests/test_ml/test_tail_model_registry.py`

- [ ] Add model status: `candidate`, `promoted`, `rejected`.
- [ ] Promotion requires:
  - validation selected days >= 30
  - model Top2 next-high > 1% hit rate above rule baseline
  - model avg next-high return above rule baseline
  - model avg next-low drawdown no worse than rule baseline by more than 0.5 percentage points
  - no unhandled data-quality blocker in the audit
- [ ] Only one model can be `promoted` at a time.

### Task 8: Verification And Git Discipline

- [ ] Run focused tests after every task.
- [ ] Run `pytest tests/test_ml tests/test_web/test_tail_live_api.py tests/test_web/test_backtests_api.py -q` before model integration commits.
- [ ] Run `npm run build` in `frontend` after page changes.
- [ ] Commit each vertical slice separately:
  - data audit
  - sample builder
  - baseline
  - training
  - evaluation UI
  - live inference
  - promotion gate
