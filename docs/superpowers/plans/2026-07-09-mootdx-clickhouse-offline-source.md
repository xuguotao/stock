# mootdx ClickHouse Offline Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `mootdx` 建成一个独立的离线 ClickHouse 数据源链路，只写 `mootdx_*` 独立表，不污染现有生产表和默认数据源链路。

**Architecture:** 新增 `src/data/mootdx_clickhouse_sync.py` 作为离线同步模块，复用 `MootdxSource` 获取数据，并通过显式脚本 `scripts/sync_mootdx_clickhouse.py` 写入独立 ClickHouse 表。第一阶段不把 `mootdx` 加入 `DataAggregator()` 默认 fallback，不写 `stocks`、`daily_kline`、`minute5_kline`、`stock_quote_snapshots` 等现有生产表；后续是否晋升为生产 fallback 由独立评估报告决定。

**Tech Stack:** Python 3.13, pandas, mootdx 0.11.7, clickhouse-driver, pytest, ClickHouse MergeTree/ReplacingMergeTree.

---

## 离线任务计划获取的数据

第一阶段离线任务分为“默认采集”和“扩展探测”两层。默认采集是可定期落库的数据；扩展探测用于判断 `mootdx` 能否作为后续增强源，默认不跑全量。

### 默认采集数据

| 任务 key | 数据类型 | mootdx 接口 | 默认范围 | 目标表 |
| --- | --- | --- | --- | --- |
| `stock_catalog` | 股票列表/数量 | `stocks(market=0/1/2)`, `stock_count(market=0/1/2)` | SZ/SH，BJ 可配置 | `mootdx_stock_catalog` |
| `quote_snapshot` | 实时行情快照 | `quotes(symbol=[股票代码列表])` | 配置股票池，支持 limit | `mootdx_quote_snapshots` |
| `stock_kline_daily` | 股票日 K | `bars(symbol, frequency="day")` | 配置股票池，默认最近 800 根 | `mootdx_stock_kline` |
| `stock_kline_intraday` | 股票分钟 K | `bars(symbol, frequency in 1m/5m/15m/30m/1h)` | 配置股票池和交易日，默认 5m | `mootdx_stock_kline` |
| `index_kline` | 指数 K 线 | `index(symbol, frequency=指定频率)` | 默认 `000001.SH`, `399001.SZ`, `399006.SZ` | `mootdx_index_kline` |
| `xdxr` | 除权除息 | `xdxr(symbol)` | 配置股票池 | `mootdx_xdxr` |
| `finance_snapshot` | 个股财务摘要 | `finance(symbol)` | 配置股票池 | `mootdx_finance_snapshot` |
| `sync_run` | 同步运行记录 | 本地生成 | 每次任务一条 | `mootdx_sync_runs` |

### 扩展探测数据

| 任务 key | 数据类型 | mootdx 接口 | 默认策略 | 目标表 |
| --- | --- | --- | --- | --- |
| `minutes_probe` | 历史分时 | `minutes(symbol, date=交易日)` | 小样本探测，不默认全量 | `mootdx_minutes` |
| `realtime_minute_probe` | 实时分时 | `minute(symbol)` | 只和 `minutes()` 对比，不作为主路径 | `mootdx_minutes` |
| `transaction_probe` | 当前分笔 | `transaction(symbol, start, offset)` | 小样本或指定股票 | `mootdx_transactions` |
| `historical_transaction_probe` | 历史分笔 | `transactions(symbol, date, start, offset)` | 小样本或指定股票 | `mootdx_transactions` |
| `f10_catalog_probe` | F10 资料目录 | `F10C(symbol)` | 小样本文本探测 | `mootdx_f10_catalog` |
| `f10_detail_probe` | F10 资料详情 | `F10(symbol, name)` | 只按目录白名单抓取 | `mootdx_f10_detail` |
| `affair_file_list_probe` | 专业财务文件列表 | `Affair.files()` | 只记录文件名/哈希/大小，不下载 | `mootdx_affair_files` |

### 明确不做

- 不写入现有表：`stocks`、`daily_kline`、`minute5_kline`、`stock_quote_snapshots`、`stock_quote_snapshots_1m`、`stock_quote_snapshots_5m`。
- 不修改 `DataAggregator()` 默认 source 顺序。
- 不把 `mootdx` 数据混入今日尾盘选股、数据中心质量矩阵或生产维护任务。
- 不默认下载 `Affair.fetch()` 专业财务压缩包；文件较大且含独立解析语义，后续另开任务。
- 不使用扩展市场 `market="ext"`；官方文档标注该能力目前失效。

## ClickHouse 独立表设计

所有表使用 `mootdx_` 前缀，便于权限、清理和质量评估时隔离。

### `mootdx_sync_runs`

记录每次离线任务运行结果。

```sql
create table if not exists mootdx_sync_runs (
    run_id String,
    task_key LowCardinality(String),
    started_at DateTime,
    finished_at Nullable(DateTime),
    status LowCardinality(String),
    params_json String,
    result_json String,
    error String,
    source_version String
)
engine = ReplacingMergeTree(finished_at)
partition by toDate(started_at)
order by (task_key, started_at, run_id)
ttl started_at + interval 365 day delete
```

### `mootdx_stock_catalog`

独立股票目录，不替换现有 `stocks`。

```sql
create table if not exists mootdx_stock_catalog (
    captured_at DateTime,
    market UInt8,
    symbol String,
    code String,
    name String,
    is_st UInt8,
    source LowCardinality(String),
    raw_json String
)
engine = ReplacingMergeTree(captured_at)
partition by toDate(captured_at)
order by (symbol, captured_at)
ttl captured_at + interval 365 day delete
```

### `mootdx_quote_snapshots`

实时行情快照，仅用于对比 `stock_quote_snapshots`。

```sql
create table if not exists mootdx_quote_snapshots (
    snapshot_at DateTime,
    symbol String,
    price Float64,
    open Float64,
    prev_close Float64,
    high Float64,
    low Float64,
    volume UInt64,
    amount Float64,
    change_pct Float64,
    quote_time Nullable(DateTime),
    source LowCardinality(String),
    raw_json String
)
engine = MergeTree
partition by toDate(snapshot_at)
order by (snapshot_at, symbol)
ttl snapshot_at + interval 180 day delete
```

### `mootdx_stock_kline`

统一存股票日线和分钟线，用 `frequency` 区分。

```sql
create table if not exists mootdx_stock_kline (
    datetime DateTime,
    trade_date Date,
    frequency LowCardinality(String),
    symbol String,
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume UInt64,
    amount Float64,
    source LowCardinality(String),
    ingested_at DateTime,
    raw_json String
)
engine = ReplacingMergeTree(ingested_at)
partition by (trade_date, frequency)
order by (frequency, symbol, datetime)
ttl trade_date + interval 1095 day delete
```

### `mootdx_index_kline`

指数 K 线独立存放，不进入股票 K 线表。

```sql
create table if not exists mootdx_index_kline (
    datetime DateTime,
    trade_date Date,
    frequency LowCardinality(String),
    symbol String,
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume UInt64,
    amount Float64,
    up_count Nullable(UInt32),
    down_count Nullable(UInt32),
    source LowCardinality(String),
    ingested_at DateTime,
    raw_json String
)
engine = ReplacingMergeTree(ingested_at)
partition by (trade_date, frequency)
order by (frequency, symbol, datetime)
ttl trade_date + interval 1095 day delete
```

### `mootdx_xdxr`

除权除息原始事件。

```sql
create table if not exists mootdx_xdxr (
    symbol String,
    event_date Date,
    category Int16,
    name String,
    fenhong Float64,
    peigujia Float64,
    songzhuangu Float64,
    peigu Float64,
    suogu Float64,
    panqianliutong Float64,
    panhouliutong Float64,
    qianzongguben Float64,
    houzongguben Float64,
    ingested_at DateTime,
    raw_json String
)
engine = ReplacingMergeTree(ingested_at)
partition by toYYYYMM(event_date)
order by (symbol, event_date, category)
```

### `mootdx_finance_snapshot`

个股财务摘要，保留原始字段 JSON，先不映射到项目 `FinancialStatement`。

```sql
create table if not exists mootdx_finance_snapshot (
    captured_at DateTime,
    symbol String,
    updated_date Nullable(Date),
    ipo_date Nullable(Date),
    industry String,
    liutongguben Float64,
    zongguben Float64,
    zongzichan Float64,
    jingzichan Float64,
    zhuyingshouru Float64,
    jinglirun Float64,
    meigujingzichan Float64,
    source LowCardinality(String),
    raw_json String
)
engine = ReplacingMergeTree(captured_at)
partition by toDate(captured_at)
order by (symbol, captured_at)
ttl captured_at + interval 1095 day delete
```

### 扩展探测表

扩展探测表只服务评估，不进入生产链路。

```sql
create table if not exists mootdx_minutes (
    captured_at DateTime,
    trade_date Date,
    symbol String,
    source_method LowCardinality(String),
    row_index UInt16,
    price Float64,
    volume UInt64,
    raw_json String
)
engine = ReplacingMergeTree(captured_at)
partition by trade_date
order by (trade_date, symbol, source_method, row_index)
ttl trade_date + interval 180 day delete
```

```sql
create table if not exists mootdx_transactions (
    captured_at DateTime,
    trade_date Nullable(Date),
    symbol String,
    source_method LowCardinality(String),
    row_index UInt32,
    price Float64,
    volume UInt64,
    amount Float64,
    raw_json String
)
engine = ReplacingMergeTree(captured_at)
partition by toDate(captured_at)
order by (symbol, source_method, captured_at, row_index)
ttl captured_at + interval 180 day delete
```

```sql
create table if not exists mootdx_f10_catalog (
    captured_at DateTime,
    symbol String,
    title String,
    raw_json String
)
engine = ReplacingMergeTree(captured_at)
partition by toDate(captured_at)
order by (symbol, title, captured_at)
ttl captured_at + interval 365 day delete
```

```sql
create table if not exists mootdx_f10_detail (
    captured_at DateTime,
    symbol String,
    title String,
    content String
)
engine = ReplacingMergeTree(captured_at)
partition by toDate(captured_at)
order by (symbol, title, captured_at)
ttl captured_at + interval 365 day delete
```

```sql
create table if not exists mootdx_affair_files (
    captured_at DateTime,
    filename String,
    hash String,
    filesize UInt64,
    raw_json String
)
engine = ReplacingMergeTree(captured_at)
partition by toDate(captured_at)
order by (filename, captured_at)
ttl captured_at + interval 365 day delete
```

## File Structure

- Create: `src/data/mootdx_clickhouse_sync.py`
  - Owns ClickHouse table creation and insert logic for all `mootdx_*` tables.
  - Provides one public function: `sync_mootdx_offline_data` with the full signature defined in Task 2.
- Modify: `src/data/mootdx_source.py`
  - Add small methods needed by the sync module if missing: F10 catalog/detail and Affair file list wrappers.
  - Keep `MootdxSource` optional and explicit.
- Create: `scripts/sync_mootdx_clickhouse.py`
  - CLI entry point for one-shot offline sync.
  - Does not register with `DataOpsRunner` in first implementation.
- Create: `tests/test_data/test_mootdx_clickhouse_sync.py`
  - Unit tests with fake ClickHouse client and fake source.
- Modify: `tests/test_data/test_mootdx_source.py`
  - Add tests for F10/Affair wrapper methods if implemented.
- Modify: `docs/notes/mootdx-data-source.md`
  - Add ClickHouse offline sync usage and table isolation notes.

## Task 1: Define ClickHouse Table Creation

**Files:**
- Create: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] **Step 1: Write the failing table creation test**

```python
class FakeClickHouse:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        return []


def test_ensure_mootdx_tables_creates_only_prefixed_tables():
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    joined = "\n".join(client.sql)
    assert "create table if not exists mootdx_sync_runs" in joined
    assert "create table if not exists mootdx_stock_catalog" in joined
    assert "create table if not exists mootdx_quote_snapshots" in joined
    assert "create table if not exists mootdx_stock_kline" in joined
    assert "create table if not exists mootdx_index_kline" in joined
    assert "create table if not exists stocks (" not in joined
    assert "create table if not exists daily_kline" not in joined
    assert "create table if not exists minute5_kline" not in joined
```

- [x] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_clickhouse_sync.py::test_ensure_mootdx_tables_creates_only_prefixed_tables -q
```

Expected: FAIL with `ModuleNotFoundError` or `cannot import name 'ensure_mootdx_tables'`.

- [x] **Step 3: Implement `ensure_mootdx_tables(client)`**

Create `src/data/mootdx_clickhouse_sync.py` with an `ensure_mootdx_tables` function and a `MOOTDX_TABLE_SQL` list. The list must contain the complete SQL statements from the “ClickHouse 独立表设计” section in this plan, in the same table order.

```python
from __future__ import annotations

from typing import Any


def ensure_mootdx_tables(client: Any) -> None:
    for sql in MOOTDX_TABLE_SQL:
        client.execute(sql)


MOOTDX_TABLE_SQL = [
    SYNC_RUNS_SQL,
    STOCK_CATALOG_SQL,
    QUOTE_SNAPSHOTS_SQL,
    STOCK_KLINE_SQL,
    INDEX_KLINE_SQL,
    XDXR_SQL,
    FINANCE_SNAPSHOT_SQL,
    MINUTES_SQL,
    TRANSACTIONS_SQL,
    F10_CATALOG_SQL,
    F10_DETAIL_SQL,
    AFFAIR_FILES_SQL,
]
```

- [x] **Step 4: Run the test and verify it passes**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_clickhouse_sync.py::test_ensure_mootdx_tables_creates_only_prefixed_tables -q
```

Expected: PASS.

## Task 2: Normalize and Insert Default Offline Data

**Files:**
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] **Step 1: Write the failing default sync test**

```python
from datetime import date

import pandas as pd


class FakeSource:
    def fetch_stock_list(self):
        from src.data.models import StockInfo
        return [StockInfo(symbol="000001.SZ", code="000001", name="平安银行")]

    def fetch_realtime_quotes(self, symbols):
        return pd.DataFrame([{
            "symbol": "000001.SZ",
            "price": 10.5,
            "open": 10.1,
            "prev_close": 10.0,
            "high": 10.8,
            "low": 10.0,
            "volume": 100,
            "amount": 1000.0,
            "change_pct": 5.0,
            "timestamp": "2026-07-09 14:30:00",
        }])

    def fetch_bars(self, symbol, start, end, frequency="daily"):
        return pd.DataFrame([{
            "date": date(2026, 7, 9),
            "open": 10.1,
            "high": 10.8,
            "low": 10.0,
            "close": 10.5,
            "volume": 100,
            "amount": 1000.0,
            "adjusted_close": 10.5,
            "symbol": symbol,
        }])

    def fetch_intraday_bars(self, symbol, trade_date, frequency):
        return pd.DataFrame([{
            "datetime": pd.Timestamp("2026-07-09 14:45:00"),
            "time": pd.Timestamp("2026-07-09 14:45:00").time(),
            "symbol": symbol,
            "open": 10.1,
            "high": 10.8,
            "low": 10.0,
            "close": 10.5,
            "volume": 100,
            "amount": 1000.0,
        }])

    def fetch_index_bars(self, symbol, frequency):
        return pd.DataFrame([{
            "datetime": pd.Timestamp("2026-07-09 15:00:00"),
            "open": 4000.0,
            "high": 4010.0,
            "low": 3990.0,
            "close": 4005.0,
            "volume": 100,
            "amount": 1000.0,
        }])

    def fetch_xdxr(self, symbol):
        return pd.DataFrame([{"year": 2026, "month": 7, "day": 9, "category": 1, "name": "分红"}])

    def fetch_finance_frame(self, symbol):
        return pd.DataFrame([{"code": "000001", "industry": "银行", "jinglirun": 1.0}])


class FakeClickHouse:
    def __init__(self):
        self.inserts = []

    def execute(self, sql, params=None):
        if "insert into" in sql.lower():
            self.inserts.append((sql, params or []))
        return []


def test_sync_default_tasks_writes_only_mootdx_tables():
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FakeSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        frequencies=["5m", "daily"],
        tasks=["stock_catalog", "quote_snapshot", "stock_kline_daily", "stock_kline_intraday", "index_kline", "xdxr", "finance_snapshot"],
        ensure_tables=False,
    )

    inserted_sql = "\n".join(sql for sql, _ in client.inserts)
    assert "insert into mootdx_stock_catalog" in inserted_sql
    assert "insert into mootdx_quote_snapshots" in inserted_sql
    assert "insert into mootdx_stock_kline" in inserted_sql
    assert "insert into mootdx_index_kline" in inserted_sql
    assert "insert into mootdx_xdxr" in inserted_sql
    assert "insert into mootdx_finance_snapshot" in inserted_sql
    assert "insert into daily_kline" not in inserted_sql
    assert "insert into minute5_kline" not in inserted_sql
    assert result["inserted"]["mootdx_stock_kline"] >= 2
```

- [x] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_clickhouse_sync.py::test_sync_default_tasks_writes_only_mootdx_tables -q
```

Expected: FAIL with missing `sync_mootdx_offline_data`.

- [x] **Step 3: Implement `sync_mootdx_offline_data`**

Implementation signature:

```python
def sync_mootdx_offline_data(
    *,
    client: Any | None = None,
    source: Any | None = None,
    symbols: list[str] | None = None,
    trade_date: date | None = None,
    frequencies: list[str] | None = None,
    tasks: list[str] | None = None,
    include_beijing: bool = False,
    limit: int = 0,
    ensure_tables: bool = True,
    progress: Callable[[int, str, str], None] | None = None,
) -> dict[str, Any]:
    return {"trade_date": "", "tasks": [], "symbols": [], "inserted": {}, "failed": {}, "duration_seconds": 0.0}
```

Rules:

- Default `tasks`: `stock_catalog`, `quote_snapshot`, `stock_kline_daily`, `stock_kline_intraday`, `index_kline`, `xdxr`, `finance_snapshot`.
- Default `frequencies`: `["5m"]` for intraday plus `daily` when `stock_kline_daily` is present.
- Resolve symbols from explicit `symbols`; if missing, use `source.fetch_stock_list()`, filter ST unless a later option explicitly allows it, apply `limit`.
- Every insert SQL must target only `mootdx_*` tables.
- Return a result dictionary with `trade_date`, `tasks`, `symbols`, `inserted`, `failed`, and `duration_seconds`.

- [x] **Step 4: Run the default sync test and verify it passes**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_clickhouse_sync.py::test_sync_default_tasks_writes_only_mootdx_tables -q
```

Expected: PASS.

## Task 3: Add Extended Probe Task Persistence

**Files:**
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Test: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] **Step 1: Write the failing extended tasks test**

```python
def test_sync_extended_probe_tasks_write_probe_tables():
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class ExtendedSource(FakeSource):
        def fetch_minutes(self, symbol, trade_date):
            return pd.DataFrame([{"price": 10.1, "vol": 100, "volume": 100}])

        def fetch_realtime_minute(self, symbol):
            return pd.DataFrame([{"price": 10.2, "vol": 120, "volume": 120}])

        def fetch_transactions(self, symbol, trade_date=None, start=0, offset=800):
            return pd.DataFrame([{"price": 10.2, "vol": 120, "amount": 1224.0}])

        def fetch_f10_catalog(self, symbol):
            return pd.DataFrame([{"title": "最新提示"}])

        def fetch_f10_detail(self, symbol, title):
            return "公司经营正常"

        def fetch_affair_files(self):
            return [{"filename": "gpcw20260331.zip", "hash": "abc", "filesize": 123}]

    client = FakeClickHouse()
    sync_mootdx_offline_data(
        client=client,
        source=ExtendedSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["minutes_probe", "realtime_minute_probe", "transaction_probe", "historical_transaction_probe", "f10_catalog_probe", "f10_detail_probe", "affair_file_list_probe"],
        ensure_tables=False,
    )

    inserted_sql = "\n".join(sql for sql, _ in client.inserts)
    assert "insert into mootdx_minutes" in inserted_sql
    assert "insert into mootdx_transactions" in inserted_sql
    assert "insert into mootdx_f10_catalog" in inserted_sql
    assert "insert into mootdx_f10_detail" in inserted_sql
    assert "insert into mootdx_affair_files" in inserted_sql
```

- [x] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_clickhouse_sync.py::test_sync_extended_probe_tasks_write_probe_tables -q
```

Expected: FAIL until extended task handlers exist.

- [x] **Step 3: Implement extended task handlers**

Add task-specific functions:

- `_sync_minutes_probe`
- `_sync_realtime_minute_probe`
- `_sync_transactions`
- `_sync_f10_catalog`
- `_sync_f10_detail`
- `_sync_affair_files`

All functions write only `mootdx_minutes`, `mootdx_transactions`, `mootdx_f10_catalog`, `mootdx_f10_detail`, or `mootdx_affair_files`.

- [x] **Step 4: Run the extended test and verify it passes**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_clickhouse_sync.py::test_sync_extended_probe_tasks_write_probe_tables -q
```

Expected: PASS.

## Task 4: Add Missing Source Wrappers

**Files:**
- Modify: `src/data/mootdx_source.py`
- Test: `tests/test_data/test_mootdx_source.py`

- [x] **Step 1: Write failing tests for F10 and Affair wrappers**

```python
def test_mootdx_source_exposes_f10_and_affair_helpers():
    class Client:
        def F10C(self, symbol):
            return pd.DataFrame([{"title": "最新提示"}])

        def F10(self, symbol, name):
            return "详情正文"

    source = MootdxSource(client=Client())
    assert source.fetch_f10_catalog("000001.SZ").iloc[0]["title"] == "最新提示"
    assert source.fetch_f10_detail("000001.SZ", "最新提示") == "详情正文"


def test_mootdx_source_fetch_affair_files_uses_injected_fetcher():
    source = MootdxSource(client=object(), affair_files_fetcher=lambda: [{"filename": "gpcw20260331.zip"}])
    assert source.fetch_affair_files() == [{"filename": "gpcw20260331.zip"}]
```

- [x] **Step 2: Run the tests and verify they fail**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_source.py -q
```

Expected: FAIL for missing wrapper methods or constructor parameter.

- [x] **Step 3: Implement wrappers**

Add optional constructor parameter:

```python
affair_files_fetcher: Callable[[], list[dict[str, Any]]] | None = None
```

Add methods:

```python
def fetch_f10_catalog(self, symbol: str) -> pd.DataFrame:
    client = self._client_instance()
    self._wait_for_rate_limit()
    return _safe_frame(client.F10C(symbol=_code(symbol)))


def fetch_f10_detail(self, symbol: str, title: str) -> str:
    client = self._client_instance()
    self._wait_for_rate_limit()
    value = client.F10(symbol=_code(symbol), name=title)
    return "" if value is None else str(value)


def fetch_affair_files(self) -> list[dict[str, Any]]:
    if self._affair_files_fetcher is not None:
        return self._affair_files_fetcher()
    try:
        from mootdx.affair import Affair
    except ModuleNotFoundError as exc:
        raise RuntimeError("mootdx is not installed; install the market extra with `uv sync --extra market`.") from exc
    return list(Affair.files())
```

- [x] **Step 4: Run source tests**

Run:

```bash
python -m pytest tests/test_data/test_mootdx_source.py -q
```

Expected: PASS.

## Task 5: Add CLI Script

**Files:**
- Create: `scripts/sync_mootdx_clickhouse.py`
- Test: `tests/test_scripts/test_sync_mootdx_clickhouse.py`

- [x] **Step 1: Write the failing CLI argument test**

```python
def test_parse_args_supports_default_and_extended_tasks():
    from scripts.sync_mootdx_clickhouse import parse_args

    args = parse_args([
        "--symbols", "000001.SZ,600519.SH",
        "--trade-date", "2026-07-09",
        "--tasks", "stock_catalog,quote_snapshot,stock_kline_intraday",
        "--frequencies", "1m,5m",
        "--limit", "2",
        "--no-ensure-tables",
    ])

    assert args.symbols == "000001.SZ,600519.SH"
    assert args.trade_date == "2026-07-09"
    assert args.tasks == "stock_catalog,quote_snapshot,stock_kline_intraday"
    assert args.frequencies == "1m,5m"
    assert args.limit == 2
    assert args.ensure_tables is False
```

- [x] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m pytest tests/test_scripts/test_sync_mootdx_clickhouse.py::test_parse_args_supports_default_and_extended_tasks -q
```

Expected: FAIL with missing script.

- [x] **Step 3: Implement CLI**

Script behavior:

```bash
python scripts/sync_mootdx_clickhouse.py \
  --symbols 000001.SZ,600519.SH \
  --trade-date 2026-07-09 \
  --tasks stock_catalog,quote_snapshot,stock_kline_daily,stock_kline_intraday,index_kline,xdxr,finance_snapshot \
  --frequencies 5m,daily \
  --limit 0
```

CLI options:

- `--symbols`: comma-separated symbols.
- `--trade-date`: defaults to today.
- `--tasks`: comma-separated task keys.
- `--frequencies`: comma-separated K-line frequencies.
- `--limit`: cap symbol count after resolution.
- `--include-beijing`: include BJ stocks in catalog resolution.
- `--bestip`: ask mootdx to test fastest server.
- `--server host:port`: pin server.
- `--timeout`: mootdx timeout.
- `--no-ensure-tables`: skip DDL creation.

- [x] **Step 4: Run CLI tests**

Run:

```bash
python -m pytest tests/test_scripts/test_sync_mootdx_clickhouse.py -q
```

Expected: PASS.

## Task 6: Add Documentation

**Files:**
- Modify: `docs/notes/mootdx-data-source.md`

- [x] **Step 1: Add a ClickHouse offline section**

Add this section:

```markdown
## ClickHouse 离线同步

第一阶段离线同步只写 `mootdx_*` 表，不写现有生产表。默认任务包括：

- `stock_catalog`
- `quote_snapshot`
- `stock_kline_daily`
- `stock_kline_intraday`
- `index_kline`
- `xdxr`
- `finance_snapshot`

扩展探测任务包括：

- `minutes_probe`
- `realtime_minute_probe`
- `transaction_probe`
- `historical_transaction_probe`
- `f10_catalog_probe`
- `f10_detail_probe`
- `affair_file_list_probe`

示例：

```bash
python scripts/sync_mootdx_clickhouse.py \
  --symbols 000001.SZ,600519.SH \
  --trade-date 2026-07-09 \
  --tasks stock_catalog,quote_snapshot,stock_kline_daily,stock_kline_intraday,index_kline,xdxr,finance_snapshot \
  --frequencies 5m,daily
```

验收时先查 `mootdx_sync_runs` 和各 `mootdx_*` 表，不应看到 `daily_kline`、`minute5_kline`、`stock_quote_snapshots` 有新增 mootdx 写入。
```

- [x] **Step 2: Verify no placeholder text remains**

Run:

```bash
rg -n "T[B]D|TO[D]O|待[补]|以后[再]" docs/notes/mootdx-data-source.md docs/superpowers/plans/2026-07-09-mootdx-clickhouse-offline-source.md
```

Expected: no output.

## Task 7: Final Verification

**Files:**
- All files above.

- [x] **Step 1: Run focused tests**

Run:

```bash
python -m pytest \
  tests/test_data/test_mootdx_source.py \
  tests/test_data/test_mootdx_clickhouse_sync.py \
  tests/test_scripts/test_sync_mootdx_clickhouse.py \
  -q
```

Expected: all tests pass.

- [x] **Step 2: Run a dry small ClickHouse sync against configured ClickHouse**

Use a small explicit symbol set:

```bash
python scripts/sync_mootdx_clickhouse.py \
  --symbols 000001.SZ \
  --trade-date 2026-07-09 \
  --tasks stock_catalog,quote_snapshot,stock_kline_daily,stock_kline_intraday,index_kline,xdxr,finance_snapshot \
  --frequencies 5m,daily \
  --limit 1
```

Expected: command exits 0 and prints JSON summary with inserts only under `mootdx_*` tables.

- [x] **Step 3: Verify ClickHouse isolation**

Run:

```bash
python - <<'PY'
from src.data.clickhouse_source import ClickHouseStockDataSource
client = ClickHouseStockDataSource()._client_instance()
tables = [row[0] for row in client.execute("show tables")]
print([table for table in tables if table.startswith("mootdx_")])
for table in tables:
    if table.startswith("mootdx_"):
        print(table, client.execute(f"select count() from {table}")[0][0])
PY
```

Expected: only `mootdx_*` tables are listed for the new source. Existing production table counts are not part of this sync’s success criteria and must not be written by the new code.

## Self-Review

- Scope coverage: the plan includes the requested offline source addition, ClickHouse-only persistence, table isolation, and a concrete list of data collected by the offline task.
- Placeholder scan: no deferred placeholder requirements are allowed in implementation steps.
- Type consistency: task keys, table names, and source method names are consistent across data plan, tests, sync module, CLI, and docs.
