# Mootdx XDXR Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scheduled, audited Mootdx-only XDXR sync that preserves source nulls and can be measured end-to-end before its first full bootstrap.

**Architecture:** Keep XDXR in the existing isolated `mootdx_xdxr` fact table and add a separate per-symbol audit table. Make the XDXR branch of `sync_mootdx_offline_data` responsible for per-symbol latency, empty/error classification, circuit breaking, and phase timing; all other Mootdx tasks retain their existing behavior. Register a post-close `mootdx_xdxr_sync` task with the benchmarked connection defaults, while leaving `xdxr_info`, `tdxrs`, and adjustment services untouched.

**Tech Stack:** Python 3, pandas, `mootdx==0.11.7`, ClickHouse `ReplacingMergeTree`, pytest.

---

## File structure

- Modify `src/data/mootdx_clickhouse_sync.py`: nullable XDXR schema migration, XDXR-specific row collection, symbol audit writes, phase timings, and circuit-break diagnostics.
- Modify `src/data/mootdx_clickhouse_sync.py`: materialize catalog lifecycle state so daily sync excludes confirmed removals and immediately restores reappearing symbols.
- Modify `src/data_ops/mootdx_tasks.py`: add the dedicated post-close Mootdx XDXR task and its connection defaults.
- Modify `src/data_ops/repository.py`: treat the new task as a connection-default migration candidate.
- Modify `scripts/sync_mootdx_clickhouse.py`: expose the existing `xdxr` task unchanged but print the XDXR diagnostics in the JSON result.
- Create `scripts/benchmark_mootdx_xdxr.py`: run the fixed, stratified 300-symbol end-to-end benchmark with an explicit `--write` opt-in.
- Modify `tests/test_data/test_mootdx_clickhouse_sync.py`: cover null preservation, event-key idempotence, per-symbol audit rows, phase timings, and circuit breaking.
- Modify `tests/test_data_ops/test_mootdx_tasks.py`, `tests/test_data_ops/test_handlers.py`, and `tests/test_data_ops/test_repository.py`: cover scheduling, source construction, and configuration migration.
- Modify `tests/test_scripts/test_sync_mootdx_clickhouse.py` and create `tests/test_scripts/test_benchmark_mootdx_xdxr.py`: cover CLI defaults and read-only/write opt-in behavior.
- Modify `docs/notes/mootdx-xdxr-interface-test-2026-07-13.md`: append the completed 300-symbol network benchmark and link to the new reproducible command.

### Task 1: Lock down the XDXR storage contract

**Files:**
- Modify: `tests/test_data/test_mootdx_clickhouse_sync.py`
- Modify: `src/data/mootdx_clickhouse_sync.py:MOOTDX_TABLE_SQL` and `_xdxr_rows`

- [ ] **Step 1: Write failing schema and row-shape tests**

Add tests that pass one XDXR row with `suogu=None` and missing capital fields, then assert the collected tuple contains `None` rather than `0.0`. Add a DDL assertion that the eight nullable source measurements are declared `Nullable(Float64)`:

```python
def test_xdxr_rows_preserve_source_nulls() -> None:
    rows, _ = _xdxr_rows(FakeXdxrSource([{
        "year": 2026, "month": 7, "day": 9, "category": 1,
        "name": "除权除息", "fenhong": 1.0, "suogu": None,
    }]), ["000001.SZ"], run_id="run")

    assert rows[0][8] is None
    assert rows[0][9:13] == (None, None, None, None)

def test_mootdx_xdxr_schema_keeps_nullable_source_measurements() -> None:
    sql = next(sql for sql in MOOTDX_TABLE_SQL if "create table if not exists mootdx_xdxr" in sql.lower())
    assert "suogu Nullable(Float64)" in sql
    assert "panqianliutong Nullable(Float64)" in sql
```

- [ ] **Step 2: Run the focused tests and confirm the current null-to-zero behavior fails**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr_rows_preserve_source_nulls or xdxr_schema_keeps_nullable' -v
```

Expected: FAIL because `_float(None)` returns `0.0` and the current DDL uses `Float64`.

- [ ] **Step 3: Implement a dedicated nullable XDXR conversion and table migration**

Add a helper that returns `None` for `None`, `NaN`, empty strings, and unparsable values; otherwise returns `float(value)`:

```python
def _nullable_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    numeric = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(numeric) else float(numeric)
```

Use it only for `mootdx_xdxr` measurements. Change `fenhong`, `peigujia`, `songzhuangu`, `peigu`, `suogu`, `panqianliutong`, `panhouliutong`, `qianzongguben`, and `houzongguben` to `Nullable(Float64)`. In `ensure_mootdx_tables`, after the create statements, execute `ALTER TABLE mootdx_xdxr MODIFY COLUMN ... Nullable(Float64)` for the same columns so a pre-existing table receives the compatible schema. Do not alter unrelated tables or legacy XDXR tables.

- [ ] **Step 4: Run focused tests and the surrounding sync suite**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr' -v
pytest tests/test_data/test_mootdx_clickhouse_sync.py -v
```

Expected: PASS, with existing XDXR partition-batching assertions still valid.

- [ ] **Step 5: Commit the isolated storage change**

```bash
git add src/data/mootdx_clickhouse_sync.py tests/test_data/test_mootdx_clickhouse_sync.py
git commit -m "feat: preserve nulls in mootdx xdxr"
```

### Task 2: Add per-symbol audit and phase timing to the XDXR branch

**Files:**
- Modify: `tests/test_data/test_mootdx_clickhouse_sync.py`
- Modify: `src/data/mootdx_clickhouse_sync.py:_run_task`, `_xdxr_rows`, `MOOTDX_TABLE_SQL`

- [ ] **Step 1: Write failing tests for symbol outcomes and circuit breaking**

Create a fake source that returns one non-empty frame, one empty frame, and then three exceptions. Assert that the sync result includes `diagnostics["xdxr"]` with `requested`, `success`, `empty`, `error`, `event_rows`, `request_seconds`, `parse_seconds`, and `circuit_breaker_triggered`; assert that `mootdx_xdxr_symbol_runs` receives rows with statuses `success`, `empty`, and `error`.

```python
assert result["diagnostics"]["xdxr"]["success"] == 1
assert result["diagnostics"]["xdxr"]["empty"] == 1
assert result["diagnostics"]["xdxr"]["error"] == 3
assert result["diagnostics"]["xdxr"]["circuit_breaker_triggered"] is True
assert {row[3] for row in audit_rows} == {"success", "empty", "error"}
```

Add an idempotence test asserting the table DDL remains `ReplacingMergeTree(ingested_at)` ordered by `(symbol, event_date, category)` and that one same-day, two-category input produces two distinct tuples.

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr_symbol_runs or xdxr_circuit or xdxr_same_day' -v
```

Expected: FAIL because there is no audit table, no XDXR diagnostic object, and exceptions escape at task scope.

- [ ] **Step 3: Implement XDXR-specific collection and audit persistence**

Create `mootdx_xdxr_symbol_runs` with these columns:

```sql
run_id String,
symbol String,
requested_at DateTime,
status LowCardinality(String),
event_rows UInt32,
request_ms Nullable(Float64),
parse_ms Nullable(Float64),
error String,
raw_columns Array(String)
```

Use `ReplacingMergeTree(requested_at)` ordered by `(run_id, symbol)`. Change `_xdxr_rows` to accept `run_id` and return `(event_rows, audit_rows, diagnostics)`. Around each `source.fetch_xdxr(symbol)` call, capture request time, classify a successful empty frame as `empty`, and append a single audit tuple. Parse only valid `year/month/day` rows; count invalid dates in diagnostics. On an exception, append an `error` audit tuple with `ExceptionType: message` truncated to 240 characters; increment a consecutive-error counter. Stop requesting after the third consecutive error, set `circuit_breaker_triggered=True`, and return the rows already collected.

In `_run_task`, insert both `mootdx_xdxr` and `mootdx_xdxr_symbol_runs` output collections and store the diagnostics under `diagnostics["xdxr"]`. Add `write_seconds` in `sync_mootdx_offline_data` around the two inserts, plus `total_seconds` from the existing task timer. Do not use the generic task-level exception path for individual symbol failures.

- [ ] **Step 4: Run focused and full sync tests**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr' -v
pytest tests/test_data/test_mootdx_clickhouse_sync.py -v
```

Expected: PASS; the generic default-task test still writes `mootdx_xdxr`, and the new symbol audit table is also written for the XDXR task.

- [ ] **Step 5: Commit the audited XDXR flow**

```bash
git add src/data/mootdx_clickhouse_sync.py tests/test_data/test_mootdx_clickhouse_sync.py
git commit -m "feat: audit mootdx xdxr sync"
```

### Task 3: Create the reproducible end-to-end benchmark command

**Files:**
- Create: `scripts/benchmark_mootdx_xdxr.py`
- Create: `tests/test_scripts/test_benchmark_mootdx_xdxr.py`
- Modify: `scripts/sync_mootdx_clickhouse.py`
- Modify: `tests/test_scripts/test_sync_mootdx_clickhouse.py`

- [ ] **Step 1: Write failing CLI tests**

Test `parse_args([])` returns `sample_size=300`, `rate_limit=0.02`, `timeout=10`, `bestip=False`, and `write=False`. Inject a fake source and fake ClickHouse client, then assert a no-write run never calls `execute("insert ...")`, while `--write` invokes `sync_mootdx_offline_data(tasks=["xdxr"], limit=300)` and includes diagnostics in JSON output.

```python
assert args.sample_size == 300
assert args.write is False
assert "mootdx_xdxr" not in "\n".join(client.sql).lower()
assert result["mode"] == "read_only"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
pytest tests/test_scripts/test_benchmark_mootdx_xdxr.py -v
```

Expected: FAIL because the benchmark command does not exist.

- [ ] **Step 3: Implement deterministic sampling and explicit write opt-in**

Implement a standalone script that fetches the current catalog, groups symbols by SH main board, SZ main board, ChiNext, and ST status, then round-robins sorted buckets to exactly `--sample-size` symbols. Defaults are `300`, `0.02`, `10`, and no `bestip`; reject `--bestip` with an argparse error. In default read-only mode, call `fetch_xdxr` sequentially and output JSON with catalog size, bucket counts, success/empty/error counts, P50/P95/P99, event rows, and request seconds. With `--write`, call `sync_mootdx_offline_data(tasks=["xdxr"], symbols=sample, ...)` and report returned phase diagnostics. Keep the existing generic sync CLI compatible; its existing `--tasks xdxr --limit 300` continues to work and prints `diagnostics` unchanged.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
pytest tests/test_scripts/test_benchmark_mootdx_xdxr.py tests/test_scripts/test_sync_mootdx_clickhouse.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit benchmark tooling**

```bash
git add scripts/benchmark_mootdx_xdxr.py scripts/sync_mootdx_clickhouse.py tests/test_scripts/test_benchmark_mootdx_xdxr.py tests/test_scripts/test_sync_mootdx_clickhouse.py
git commit -m "feat: add mootdx xdxr benchmark command"
```

### Task 4: Register the dedicated post-close Mootdx task

**Files:**
- Modify: `tests/test_data_ops/test_mootdx_tasks.py`
- Modify: `tests/test_data_ops/test_handlers.py`
- Modify: `tests/test_data_ops/test_models.py`
- Modify: `tests/test_data_ops/test_repository.py`
- Modify: `src/data_ops/mootdx_tasks.py`
- Modify: `src/data_ops/repository.py`

- [ ] **Step 1: Write failing registration and migration tests**

Extend expected task keys with `mootdx_xdxr_sync`. Assert its configuration is exactly `{"time": "17:10", "rate_limit": 0.02, "timeout": 10, "bestip": False}`, it runs with `tasks=["xdxr"]`, and seeded pre-existing configuration gains missing connection keys without overwriting a user-selected time or limit.

```python
assert handlers["mootdx_xdxr_sync"]({"trade_date": "2026-07-14"})["tasks"] == ["xdxr"]
assert created[-1] == {"rate_limit": 0.02, "timeout": 10, "bestip": False, "include_beijing": False}
```

- [ ] **Step 2: Run data-ops tests and confirm failure**

Run:

```bash
pytest tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_models.py tests/test_data_ops/test_repository.py -v
```

Expected: FAIL because the task is not defined or registered.

- [ ] **Step 3: Add the task definition and configuration migration**

Add a `MootdxTaskDefinition` after daily reconciliation:

```python
MootdxTaskDefinition(
    task_key="mootdx_xdxr_sync",
    label="除权除息同步",
    description="同步 Mootdx 除权除息及股本变动历史，并记录逐标的结果与耗时审计。",
    sync_task="xdxr",
    schedule_kind="daily_time",
    schedule_config={"time": "17:10", "rate_limit": 0.02, "timeout": 10, "bestip": False},
    max_runtime_seconds=900,
    stale_after_seconds=300,
)
```

Extend the task-key set in `_requires_default_update` so existing configs receive missing `rate_limit`, `timeout`, and `bestip`. Reuse `run_mootdx_sync` and `_mootdx_source_from_params`; do not invoke `run_xdxr_sync` or any legacy source.

- [ ] **Step 4: Run data-ops tests**

Run:

```bash
pytest tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_models.py tests/test_data_ops/test_repository.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit task registration**

```bash
git add src/data_ops/mootdx_tasks.py src/data_ops/repository.py tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_models.py tests/test_data_ops/test_repository.py
git commit -m "feat: schedule mootdx xdxr sync"
```

### Task 5: Verify the real 300-symbol write path and document evidence

**Files:**
- Modify: `docs/notes/mootdx-xdxr-interface-test-2026-07-13.md`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`, `tests/test_data_ops/`, `tests/test_scripts/`

- [ ] **Step 1: Run the complete automated regression set**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py tests/test_data_ops tests/test_scripts/test_benchmark_mootdx_xdxr.py tests/test_scripts/test_sync_mootdx_clickhouse.py -v
```

Expected: PASS with no legacy XDXR test changes outside the explicitly listed data-ops expectations.

- [ ] **Step 2: Run the read-only benchmark again**

Run:

```bash
python scripts/benchmark_mootdx_xdxr.py --sample-size 300 --rate-limit 0.02 --timeout 10
```

Expected: JSON reports `transport_ok_rate >= 0.99`, `bestip=false`, and no ClickHouse writes.

- [ ] **Step 3: Run the 300-symbol write benchmark only after confirming the target ClickHouse is the isolated development database**

Run:

```bash
python scripts/benchmark_mootdx_xdxr.py --sample-size 300 --rate-limit 0.02 --timeout 10 --write
```

Expected: JSON contains nonzero `mootdx_xdxr` inserted rows, phase timings, and no task failure. Then query the development database:

```sql
SELECT status, count() FROM mootdx_xdxr_symbol_runs GROUP BY status;
SELECT count(), countDistinct(symbol, event_date, category) FROM mootdx_xdxr FINAL;
SELECT count() FROM mootdx_xdxr FINAL WHERE isNull(suogu);
```

Expected: success/empty/error counts reconcile with JSON, event-key counts are equal, and at least the known null-bearing field remains queryable as `NULL`.

- [ ] **Step 4: Append measured write-path evidence to the interface note**

Record the command, timestamp, catalog/sample sizes, request/parse/write/total timings, inserted event count, symbol outcome counts, and the three query results. State explicitly whether the 99% threshold is met; do not substitute the prior read-only estimate for write-path evidence.

- [ ] **Step 5: Commit documentation and verification evidence**

```bash
git add docs/notes/mootdx-xdxr-interface-test-2026-07-13.md
git commit -m "docs: record mootdx xdxr write benchmark"
```

### Task 6: Make the catalog lifecycle control daily-sync eligibility

**Files:**
- Modify: `tests/test_data/test_mootdx_clickhouse_sync.py`
- Modify: `tests/test_web/test_mootdx_quality.py`
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Modify: `src/web/backend/mootdx_quality.py`

- [ ] **Step 1: Write failing lifecycle tests**

Create a three-snapshot fixture: initial catalog contains `000001.SZ`; the next successful snapshot omits it; the third successful snapshot omits it again. Assert the first omission yields `is_active=1`, `missing_catalog_runs=1`, and inclusion in `_latest_catalog_symbols`; assert the second omission writes `is_active=0`, `missing_catalog_runs=2`, and exclusion. Then provide a fourth snapshot containing the code and assert `is_active=1`, `missing_catalog_runs=0`, and inclusion. Add a catalog-count drop fixture (more than 2%) and assert no removal counter or active flag changes.

```python
assert active_after_first_missing == [("000001.SZ", 1, 1)]
assert active_after_second_missing == []
assert active_after_reappearance == [("000001.SZ", 1, 0)]
assert diagnostics["catalog_snapshot_anomalous"] is True
```

- [ ] **Step 2: Run the lifecycle tests and confirm failure**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py -k 'catalog_removal or catalog_reappearance or catalog_snapshot_anomalous' -v
```

Expected: FAIL because removal currently only creates an audit event and the old catalog row remains active in `FINAL`.

- [ ] **Step 3: Materialize active, pending, and dormant catalog state**

Extend `mootdx_stock_catalog` with `is_active UInt8 DEFAULT 1`, `missing_catalog_runs UInt8 DEFAULT 0`, `last_seen_at Nullable(DateTime)`, `deactivated_at Nullable(DateTime)`, and `reactivated_at Nullable(DateTime)`. Add compatible `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration statements. Extend `_latest_catalog_by_symbol` to return lifecycle fields.

During `_stock_catalog_rows`, a source-present symbol writes `is_active=1`, resets `missing_catalog_runs=0`, sets `last_seen_at=captured_at`, and sets `reactivated_at` only when the previous state was inactive. For a source-absent symbol, write no state transition when the count drop exceeds 2%; otherwise write a replacement row retaining prior identity data, increment `missing_catalog_runs`, retain `is_active=1` at count 1, and set `is_active=0` plus `deactivated_at=captured_at` at count 2. Continue producing `removed`/`added` audit events only on lifecycle boundaries, not on every pending run.

Filter `_latest_catalog_symbols` and Mootdx daily quality catalog queries by `is_active=1`. Do not alter legacy tables or add daily probes for dormant symbols.

- [ ] **Step 4: Run focused lifecycle and full Mootdx sync tests**

Run:

```bash
pytest tests/test_data/test_mootdx_clickhouse_sync.py tests/test_web/test_mootdx_quality.py -v
```

Expected: PASS; dormant symbols are excluded from daily targets, reappearing symbols are included on the same post-catalog cycle, and anomalous catalog snapshots cannot deactivate symbols.

- [ ] **Step 5: Commit catalog lifecycle behavior**

```bash
git add src/data/mootdx_clickhouse_sync.py src/web/backend/mootdx_quality.py tests/test_data/test_mootdx_clickhouse_sync.py tests/test_web/test_mootdx_quality.py
git commit -m "feat: manage mootdx catalog lifecycle"
```

## Plan self-review

- Spec coverage: Task 1 covers nullable source semantics and event keys; Task 2 covers per-symbol results, phase timings, and circuit breaking; Task 3 provides a repeatable 300-symbol benchmark; Task 4 creates the dedicated Mootdx-only task; Task 5 performs and records end-to-end acceptance evidence.
- Scope: no task changes `xdxr_info`, `tdxrs`, `AdjustmentService`, or any other source. The only operational write is the explicit `--write` development benchmark in Task 5.
- Consistency: the task key is `mootdx_xdxr_sync`, its sync task is `xdxr`, its candidate source defaults are `rate_limit=0.02`, `timeout=10`, `bestip=False`, and the audit table is `mootdx_xdxr_symbol_runs` in every task.
