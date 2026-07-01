# Data Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ClickHouse market data safe for strategy use by detecting and repairing daily duplicates, surfacing historical invalid prices, and reducing write/read paths that can silently reintroduce bad data.

**Architecture:** Keep ClickHouse as the canonical data source. Add table-level maintenance helpers under `src/data/clickhouse_table_maintenance.py`, wire read-only duplicate/invalid checks into `src/web/backend/data_status.py`, and make daily repair idempotent under concurrent invocations. Use scripts for explicit destructive maintenance and keep dashboard checks read-only.

**Tech Stack:** Python, ClickHouse SQL, FastAPI status models, pytest, Vue/Vite validation.

---

### Task 1: Detect `daily_kline` Duplicate Keys

**Files:**
- Modify: `src/data/clickhouse_table_maintenance.py`
- Modify: `src/web/backend/data_status.py`
- Test: `tests/test_data/test_clickhouse_table_maintenance.py`
- Test: `tests/test_web/test_clickhouse_data_status.py`

- [x] Add `daily_duplicate_stats()` that counts duplicate `(symbol,date)` groups and extra rows.
- [x] Wire the stats into `_clickhouse_quality()["daily"]`.
- [x] Add issue key `daily_kline_duplicate_{extra_rows}_extra_rows` when extra rows exist.
- [x] Verify with unit tests and fake ClickHouse clients.

### Task 2: Repair `daily_kline` Duplicate Rows

**Files:**
- Modify: `src/data/clickhouse_table_maintenance.py`
- Modify: `scripts/maintain_clickhouse_tables.py`
- Test: `tests/test_data/test_clickhouse_table_maintenance.py`

- [x] Add `deduplicate_daily_kline(dry_run=True)` using a replacement `MergeTree` table.
- [x] Preserve the existing daily schema and keep one row per `(symbol,date)`.
- [x] Add CLI commands `daily-duplicates` and `dedup-daily`.
- [x] Run dry-run, then execute once against the current ClickHouse database after tests pass.

Result on 2026-06-23: `daily_kline` duplicate groups were reduced from 25,965 to 0, and extra duplicate rows from 46,736 to 0. Original table was retained as `daily_kline_backup_20260623_fix`.

### Task 3: Make Daily Repair Concurrent-Safe

**Files:**
- Modify: `src/data/clickhouse_daily_sync.py`
- Test: `tests/test_data/test_clickhouse_daily_sync.py`

- [x] Add a per-process lock plus ClickHouse repair marker table around latest-day daily repair.
- [x] If a run for the same `trade_date` is already active, return a skipped result instead of inserting.
- [x] Recheck existing daily rows immediately before insert.
- [x] Verify concurrent-like calls cannot insert twice in fake tests.

### Task 4: Surface Historical Invalid OHLC Data

**Files:**
- Modify: `src/web/backend/data_status.py`
- Test: `tests/test_web/test_clickhouse_data_status.py`

- [x] Add a historical invalid price check for `open/high/low/close <= 0`.
- [x] Keep latest-day anomaly check as-is for blocking freshness, but expose historical invalid rows as a quality issue.
- [x] Include sample symbols/date ranges so the repair target is visible.
- [x] Show the check in the data center scheduled quality section and repair plan as a manual re-import item.

Current remaining issue: 1,203 historical invalid OHLC rows across 14 symbols from 2020-01-02 to 2022-04-27. This does not block today's tail-selection freshness, but it can pollute long-horizon backtests until those rows are re-imported from a trusted historical source.

### Task 5: Stabilize Quote 5m Rollup Reads

**Files:**
- Modify: `src/data/clickhouse_source.py`
- Modify: `src/web/backend/data_status.py`
- Test: existing tests plus a focused fake query assertion if needed.

- [x] Add `FINAL` to `stock_quote_snapshots_5m` strategy/trend fallback read paths.
- [x] Add rollup duplicate stats to data status so unmerged versions are visible.
- [x] Defer table rebuild until daily P0 repair is complete.

### Task 6: System-Level Automation Follow-Up

**Files:**
- Create/modify launchd or cron installer script after data repair is stable.
- Modify docs once the chosen scheduler is final.

- [ ] Do not run web scheduler and system scheduler concurrently.
- [ ] Add an explicit runtime status that can distinguish “web scheduler stopped” from “web server not running”.

Deferred: this is an automation ownership change and should be handled separately after the data repair path has been observed through at least one trading session.
