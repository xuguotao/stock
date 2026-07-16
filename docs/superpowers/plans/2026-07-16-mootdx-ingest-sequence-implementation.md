# Mootdx 全局入库序号 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以全局 `ingest_seq` 替换秒级入库时间，向复权层提供精确、可审计的增量输入边界。

**Architecture:** 每次 Mootdx 原始数据同步先获得一个不可复用的全局序号，并以同一序号写入日线和 XDXR 行；成功序号才可被复权消费。复权运行保存最大成功序号，构建范围为 `(previous_seq, captured_seq]`，并继续生成完整 raw/event/factor 快照。

**Tech Stack:** Python、ClickHouse、pytest。

---

### Task 1: 入库运行审计与序号分配

**Files:**

- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [ ] **Step 1: 写失败测试**

```python
def test_successful_raw_sync_assigns_one_global_ingest_seq_to_daily_and_xdxr_rows() -> None:
    result = sync_mootdx_offline_data(client=client, source=source, tasks=["stock_kline_daily", "xdxr"])
    assert result["ingest_seq"] == 1
    assert {row[-2] for row in client.inserts["mootdx_stock_kline"]} == {1}
    assert {row[-2] for row in client.inserts["mootdx_xdxr"]} == {1}
```

- [ ] **Step 2: 验证红灯**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k ingest_seq`

Expected: FAIL，因为原始表行和同步结果没有 `ingest_seq`。

- [ ] **Step 3: 最小实现**

在 `ensure_mootdx_tables()` 创建 `mootdx_ingestion_runs`，并通过 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ingest_seq UInt64 DEFAULT 0` 演进两张现有原始表。实现 `_start_ingestion_run()`：在同一 ClickHouse 客户端上读取最大序号、插入 `running` 行，返回新序号；实现 `_finish_ingestion_run()` 写入成功/失败、结束时间、行数和错误。把序号传入 `_daily_kline_rows`、`_stock_kline_rows_from_frame`、`_xdxr_rows` 和对应 insert 列。

- [ ] **Step 4: 失败运行不成为可消费水位**

```python
def test_failed_sync_keeps_consumption_watermark_on_last_successful_sequence() -> None:
    sync_mootdx_offline_data(client=client, source=failing_source, tasks=["xdxr"])
    assert client.ingestion_runs[-1]["status"] == "failed"
    assert latest_successful_ingest_seq(client) == 0
```

- [ ] **Step 5: 绿灯、检查、提交**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k ingest_seq`

Run: `git diff --check && git add src/data/mootdx_clickhouse_sync.py tests/test_data/test_mootdx_clickhouse_sync.py && git commit -m "feat: add mootdx ingestion sequence"`

### Task 2: 复权运行保存并消费序号

**Files:**

- Modify: `src/data/research_adjustment_store.py`
- Modify: `scripts/build_research_adjustment_data.py`
- Test: `tests/test_data/test_research_adjustment_store.py`
- Test: `tests/test_scripts/test_build_research_adjustment_data.py`

- [ ] **Step 1: 写失败测试**

```python
def test_incremental_build_consumes_only_successful_sequences_after_published_sequence() -> None:
    current = {"run_id": "old", "input_ingest_seq": 17}
    result = build_research_adjustment_data(store=store, client=client, formula_version="v1")
    assert result["input_ingest_seq"] == 21
    assert client.changed_symbols_params == {"previous_ingest_seq": 17, "captured_ingest_seq": 21}
```

- [ ] **Step 2: 验证红灯**

Run: `pytest -q tests/test_data/test_research_adjustment_store.py tests/test_scripts/test_build_research_adjustment_data.py -k ingest_seq`

Expected: FAIL，因为发布运行没有 `input_ingest_seq` 且构建查询仍使用 `ingested_at`。

- [ ] **Step 3: 最小实现**

将 `research_adjustment_runs.input_watermark` 演进为 `input_ingest_seq Nullable(UInt64)`（保留旧字段仅用于历史兼容，不再作为增量边界）。`current_run()` 返回该序号；`publish_run()` 接受并持久化非空序号。构建开始时查询 `mootdx_ingestion_runs` 的最大 `succeeded` 序号；目标标的分别从日线和 XDXR 取 `ingest_seq > previous_ingest_seq AND ingest_seq <= captured_ingest_seq` 的并集。所有原始读取限制到 `ingest_seq <= captured_ingest_seq`，并把实际输入写入现有 raw snapshot。

- [ ] **Step 4: 迁移与 no-op 边界**

```python
def test_incremental_build_requires_full_when_current_run_has_no_ingest_sequence() -> None:
    with pytest.raises(ValueError, match="--full"):
        build_research_adjustment_data(store=legacy_store, client=client)

def test_equal_successful_sequence_returns_unpublished_noop() -> None:
    assert build_research_adjustment_data(store=store, client=client)["published"] is False
```

- [ ] **Step 5: 绿灯、检查、提交**

Run: `pytest -q tests/test_data/test_research_adjustment_store.py tests/test_scripts/test_build_research_adjustment_data.py`

Run: `git diff --check && git add src/data/research_adjustment_store.py scripts/build_research_adjustment_data.py tests/test_data/test_research_adjustment_store.py tests/test_scripts/test_build_research_adjustment_data.py && git commit -m "feat: consume mootdx ingestion sequences"`

### Task 3: 端到端边界与兼容性验证

**Files:**

- Modify: `docs/notes/mootdx-data-source.md`
- Test: `tests/test_data/test_research_adjustment_reader.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`
- Test: `tests/test_scripts/test_build_research_adjustment_data.py`

- [ ] **Step 1: 写跨批次失败测试**

```python
def test_capture_at_sequence_31_defers_sequence_32_to_next_research_publication() -> None:
    first = build_at_sequence(31)
    second = build_at_sequence(32, current=first.current_run)
    assert first.raw_symbols == {"000001.SZ"}
    assert second.rebuilt_symbols == {"000002.SZ"}
```

- [ ] **Step 2: 验证红灯并实现最小接线**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py tests/test_scripts/test_build_research_adjustment_data.py -k 'sequence or capture'`

确保失败同步序号不被捕获，捕获后成功的新序号不混入当前运行，Reader 继续只读已发布 run 的 raw snapshot 与 factors。

- [ ] **Step 3: 完整验证与文档**

在 `docs/notes/mootdx-data-source.md` 说明：`ingest_seq=0` 是迁移前历史数据、首次必须 `--full`、增量只消费成功序号、单机发布锁限制不变。

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py tests/test_data/test_research_adjustment_events.py tests/test_data/test_research_adjustment_validation.py tests/test_data/test_research_adjustment_store.py tests/test_data/test_research_adjustment_reader.py tests/test_scripts/test_build_research_adjustment_data.py`

Run: `git diff --check && git add docs/notes/mootdx-data-source.md tests/test_data/test_research_adjustment_reader.py tests/test_data/test_mootdx_clickhouse_sync.py tests/test_scripts/test_build_research_adjustment_data.py && git commit -m "docs: describe mootdx ingestion sequence"`
