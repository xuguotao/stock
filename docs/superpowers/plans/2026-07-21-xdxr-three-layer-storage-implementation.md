# XDXR 三层存储 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 XDXR 改为不可变事件版本日志、当前事实投影和研究运行快照，支持上游按股票全量抓取下的本地差异入库与可复现复权。

**Architecture:** 新版本日志和观察表为追加式 MergeTree；当前事实由整行 tuple 的 `argMax` View 派生，避免可空字段跨版本混合。旧 `mootdx_xdxr` 先保持不变；完成基线核验后才原子切换为兼容视图。

**Tech Stack:** Python、ClickHouse、pytest。

---

### Task 1: 新三层表与只读当前事实投影

**Files:**

- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [ ] **Step 1: 写失败的 DDL 测试**

```python
def test_ensure_mootdx_tables_creates_append_only_xdxr_versions_and_current_view() -> None:
    client = FakeClickHouse()
    ensure_mootdx_tables(client)
    sql = "\n".join(query.lower() for query, _ in client.commands)
    assert "create table if not exists mootdx_xdxr_event_versions" in sql
    assert "engine = mergetree" in sql
    assert "create table if not exists mootdx_xdxr_symbol_observations" in sql
    assert "create view if not exists mootdx_xdxr_current" in sql
    assert "argmax(tuple(" in sql
```

- [ ] **Step 2: 验证红灯**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr_versions or xdxr_current'`

Expected: FAIL，因为版本表、观察表和当前投影不存在。

- [ ] **Step 3: 最小 DDL 实现**

添加 `mootdx_xdxr_event_versions`：列包含 `ingest_seq`、`symbol`、`event_date`、`category`、`name`、所有 XDXR 业务字段、`content_hash`、`raw_json`、`observed_at`；使用 `MergeTree`，按事件日期分区、按 `(symbol,event_date,category,ingest_seq)` 排序。添加 `mootdx_xdxr_symbol_observations`：记录 `ingest_seq`、股票、`status`、事件数、事件集合哈希、耗时、错误和观察时间；使用追加式 `MergeTree`。

添加普通 View `mootdx_xdxr_current`：只连接 `mootdx_ingestion_runs FINAL` 中 `status='succeeded'` 的版本日志，对整个事件字段 tuple 使用 `argMax(tuple(...), ingest_seq)`，再拆出字段；禁止逐个可空字段 `argMax`。

- [ ] **Step 4: 增加 NULL 保留回归**

```python
def test_xdxr_current_view_selects_whole_latest_tuple_including_nulls() -> None:
    sql = mootdx_xdxr_current_view_sql().lower()
    assert "argmax(tuple(fenhong, peigujia, songzhuangu, peigu, suogu" in sql
    assert "argmax(fenhong" not in sql
```

- [ ] **Step 5: 绿灯、检查、提交**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr_versions or xdxr_current or nullable'`

Run: `git diff --check && git add src/data/mootdx_clickhouse_sync.py tests/test_data/test_mootdx_clickhouse_sync.py && git commit -m "feat: add xdxr version storage"`

### Task 2: 全量抓取下的差异版本写入与观察记录

**Files:**

- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [ ] **Step 1: 写失败测试**

```python
def test_repeated_identical_xdxr_fetch_writes_observation_not_new_version() -> None:
    result = sync_mootdx_offline_data(client=client, source=source, tasks=["xdxr"])
    assert result["inserted"]["mootdx_xdxr_event_versions"] == 0
    assert result["inserted"]["mootdx_xdxr_symbol_observations"] == 1
```

- [ ] **Step 2: 验证红灯**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr_observation or xdxr_version'`

Expected: FAIL，因为同步仍直接写旧表。

- [ ] **Step 3: 实现事件键、内容指纹与差异写入**

在成功获取一只股票的完整事件集后，生成稳定事件键 `(symbol,event_date,category)` 与规范 JSON 内容哈希。查询版本日志中每个键的最新哈希；只插入新增或变化行。无论是否变化都写观察记录。失败抓取写 `failed` 观察记录但不写版本。

- [ ] **Step 4: 消失事件不撤回**

```python
def test_missing_prior_event_records_observation_without_withdrawing_current_event() -> None:
    sync_mootdx_offline_data(client=client, source=source_without_old_event, tasks=["xdxr"])
    assert client.inserted_versions == []
    assert client.observations[-1]["status"] == "succeeded"
```

- [ ] **Step 5: 绿灯、检查、提交**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py -k 'xdxr_observation or xdxr_version or missing_prior'`

Run: `git diff --check && git add src/data/mootdx_clickhouse_sync.py tests/test_data/test_mootdx_clickhouse_sync.py && git commit -m "feat: version changed xdxr events"`

### Task 3: 新版本日志基线与兼容切换脚本

**Files:**

- Create: `scripts/migrate_xdxr_three_layer.py`
- Test: `tests/test_scripts/test_migrate_xdxr_three_layer.py`

- [ ] **Step 1: 写失败的 dry-run 测试**

```python
def test_migration_dry_run_reports_legacy_and_new_projection_differences() -> None:
    report = run_migration(client=client, dry_run=True)
    assert report["renamed"] is False
    assert report["legacy_event_count"] >= 0
    assert "business_key_difference_count" in report
```

- [ ] **Step 2: 验证红灯并实现迁移器**

Run: `pytest -q tests/test_scripts/test_migrate_xdxr_three_layer.py`

迁移器提供 `--dry-run`、`--baseline-run-id`、`--execute`。执行模式先要求新基线抓取成功和投影核验通过，再将旧表改名为 `mootdx_xdxr_legacy_<suffix>`，创建兼容 View `mootdx_xdxr` 指向 `mootdx_xdxr_current`；任何差异超出允许范围时拒绝切换。

- [ ] **Step 3: 绿灯、检查、提交**

Run: `pytest -q tests/test_scripts/test_migrate_xdxr_three_layer.py`

Run: `git diff --check && git add scripts/migrate_xdxr_three_layer.py tests/test_scripts/test_migrate_xdxr_three_layer.py && git commit -m "feat: add xdxr three-layer migration"`

### Task 4: 研究复权切换与全量基线发布

**Files:**

- Modify: `scripts/build_research_adjustment_data.py`
- Modify: `docs/notes/mootdx-data-source.md`
- Test: `tests/test_scripts/test_build_research_adjustment_data.py`

- [ ] **Step 1: 写失败测试**

```python
def test_research_build_reads_xdxr_event_versions_as_of_captured_sequence() -> None:
    events = _xdxr_events(client, ["000001.SZ"], input_ingest_seq=11)
    assert events[0]["source_ingest_seq"] == 11
```

- [ ] **Step 2: 验证红灯并切换读取**

Run: `pytest -q tests/test_scripts/test_build_research_adjustment_data.py -k event_versions`

研究构建从版本日志读取成功批次、不超过捕获边界的最新整行事件版本；将事件来源序号和哈希写入运行审计 payload。切换后首次运行拒绝增量，要求 `--full`。

- [ ] **Step 3: 全量验证与文档**

Run: `pytest -q tests/test_data/test_mootdx_clickhouse_sync.py tests/test_data/test_research_adjustment_store.py tests/test_data/test_research_adjustment_reader.py tests/test_scripts/test_build_research_adjustment_data.py tests/test_scripts/test_migrate_xdxr_three_layer.py`

记录全股票池基线执行、旧表与新投影差异核验、首次研究快照发布与回滚方式；提交 `docs: describe versioned xdxr research input`。
