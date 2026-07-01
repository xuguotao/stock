# Zijin Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an on-demand local Markdown monitor for Zijin Mining's price trend, gold/copper trend inputs, and production delivery progress.

**Architecture:** Add a focused `src/monitoring` package with pure evaluation and rendering functions. Keep network/data loading in the CLI script so the core monitor remains easy to test.

**Tech Stack:** Python 3.12, pandas, PyYAML, pytest, existing `DataAggregator`.

---

### Task 1: Core Monitor Tests

**Files:**
- Create: `tests/test_monitoring.py`

- [x] **Step 1: Write failing tests for trend, production, and rendering**

Expected behaviors:
- A price series above 20/60 day averages is `strong`.
- A price series below the 60 day average is `weak`.
- Production delivery below 75% of expected elapsed progress is `behind`.
- Rendered Markdown includes the three monitor sections.

### Task 2: Monitoring Package

**Files:**
- Create: `src/monitoring/__init__.py`
- Create: `src/monitoring/zijin.py`

- [x] **Step 1: Implement dataclasses and pure functions**

Functions:
- `evaluate_trend(name, bars, short_window=20, long_window=60)`
- `evaluate_production(items, elapsed_ratio)`
- `render_markdown_report(snapshot)`

### Task 3: Config and CLI

**Files:**
- Create: `config/zijin_monitor.yaml`
- Create: `scripts/monitor_zijin.py`

- [x] **Step 1: Add default production targets and manual commodity CSV paths**

- [x] **Step 2: Add CLI that writes `reports/zijin_monitor/YYYY-MM-DD.md`**

### Task 4: Verification

**Files:**
- Modify only if verification exposes defects.

- [x] **Step 1: Run targeted tests**

Command: `pytest tests/test_monitoring.py -q`

- [x] **Step 2: Run full test suite**

Command: `pytest -q`

- [x] **Step 3: Run CLI once with existing data paths**

Command: `python scripts/monitor_zijin.py --output-dir reports/zijin_monitor`
