# 引入 tdxrs 数据源 + 除权除息同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 tdxrs 作为专用数据同步源（除权除息），清理 mootdx/legacy local DB 遗留代码。

**Architecture:** tdxrs 通过通达信 TCP 协议获取 HTTP API 无法提供的数据（除权除息、五档盘口、逐笔成交）。**不加入 DataAggregator 优先级链**——只作为离线同步任务的专用源，将除权除息数据写入 ClickHouse `xdxr_info` 表。同时清理从未使用的 mootdx 和 legacy local DB 遗留代码。

**Tech Stack:** Python 3.11+, tdxrs (Rust+PyO3), ClickHouse, existing data_ops framework

## Global Constraints

- tdxrs 只用于离线同步任务，**不加入 DataAggregator 读取链**
- 所有同步任务必须注册到 `data_ops/models.py` 的 `default_task_configs()`
- 后台读取层（FastAPI）和前端不需要改动
- 监控层（data_status.py, data_quality_calendar.py）只做最小扩展

---

### Task 1: 清理 DataAggregator 中的 legacy local DB 遗留

**Files:**
- Modify: `src/data/aggregator.py:40-43` (移除 legacy local DB 源加载)
- Modify: `src/data/aggregator.py:61` (更新 `_prefer_source_over_cache`)
- Test: `tests/test_data/test_aggregator.py`

**Interfaces:**
- Consumes: 无（清理任务）
- Produces: `DataAggregator` 不再加载 legacy local DB 源，优先级链变为 `ClickHouse → Tencent → Sina → AKShare`

- [ ] **Step 1: Write failing test for legacy local DB removal**

```python
# tests/test_data/test_aggregator.py
from __future__ import annotations
from pathlib import Path
from src.data.aggregator import DataAggregator

def test_aggregator_no_legacy_local_db_source():
    """legacy local DB should not be in the default source chain."""
    agg = DataAggregator()
    source_names = [s.name for s in agg.sources]
    assert "legacy_local_db" not in source_names, f"legacy local DB should be removed, found: {source_names}"

def test_prefer_source_over_cache_no_legacy_local_db():
    """_prefer_source_over_cache should not check for legacy_local_db."""
    agg = DataAggregator()
    from src.data.clickhouse_source import ClickHouseStockDataSource
    agg.sources = [ClickHouseStockDataSource()]
    assert agg._prefer_source_over_cache() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_aggregator.py::test_aggregator_no_legacy_local_db_source -v`
Expected: FAIL (legacy local DB still in sources if legacy-stock-store exists)

- [ ] **Step 3: Remove legacy local DB from aggregator.py**

Edit `src/data/aggregator.py` lines 40-43, remove:
```python
            legacy_local_db_path = Path("data/legacy-stock-store")
            if legacy_local_db_path.exists():
                from src.data.legacy_local_db_source import legacy local DBStockDataSource
                sources.append(legacy local DBStockDataSource(legacy_local_db_path))
```

Edit line 61, change:
```python
    def _prefer_source_over_cache(self) -> bool:
        return bool(
            self.sources and getattr(self.sources[0], "name", "") in {"clickhouse", "legacy_local_db"}
        )
```
to:
```python
    def _prefer_source_over_cache(self) -> bool:
        return bool(
            self.sources and getattr(self.sources[0], "name", "") == "clickhouse"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_aggregator.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/aggregator.py tests/test_data/test_aggregator.py
git commit -m "refactor: remove legacy local DB from DataAggregator priority chain

ClickHouse is now the sole authoritative local data source.
legacy local DB backup has been fully migrated."
```

---

### Task 2: 清理 mootdx 死代码

**Files:**
- Delete: `src/data/mootdx_source.py`
- Delete: `tests/test_data/test_mootdx_source.py`
- Modify: `src/data/aggregator.py:44-46` (移除 mootdx 加载)
- Modify: `pyproject.toml:37` (移除 mootdx 依赖声明)
- Modify: `scripts/check_data_sources.py:23-50,96-105` (移除 mootdx 检查)
- Modify: `tests/test_scripts/test_check_data_sources.py:35-43` (移除 mootdx 测试)

**Interfaces:**
- Consumes: 无（清理任务）
- Produces: 删除 mootdx 相关代码，aggregator 链变为 `ClickHouse → Tencent → Sina → AKShare`

- [ ] **Step 1: Remove mootdx from aggregator.py**

Edit `src/data/aggregator.py` lines 44-46, remove:
```python
            from src.data.mootdx_source import MootdxSource, is_mootdx_available
            if is_mootdx_available():
                sources.append(MootdxSource(rate_limit=0.1))
```

- [ ] **Step 2: Remove mootdx from pyproject.toml**

Edit `pyproject.toml` line 37, remove:
```toml
    "mootdx>=0.10",
```

- [ ] **Step 3: Remove mootdx from check_data_sources.py**

Edit `scripts/check_data_sources.py`:
- Remove lines 23, 40-41, 43, 50, 96-105 (all mootdx-related code)
- Remove the `_check_mootdx` function

- [ ] **Step 4: Update test_check_data_sources.py**

Edit `tests/test_scripts/test_check_data_sources.py`:
- Remove lines 35, 43 (mootdx-related assertions)

- [ ] **Step 5: Delete mootdx source file**

```bash
rm src/data/mootdx_source.py
```

- [ ] **Step 6: Delete mootdx test file**

```bash
rm tests/test_data/test_mootdx_source.py
```

- [ ] **Step 7: Run tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: All tests PASS (no references to mootdx remain)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove mootdx dead code

mootdx was declared as optional dependency but never installed in production.
is_mootdx_available() always returned False, so MootdxSource was never added
to the DataAggregator chain."
```

---

### Task 3: 创建 tdxrs 同步源（精简版）

**Files:**
- Create: `src/data/tdxrs_sync.py`
- Test: `tests/test_data/test_tdxrs_sync.py`

**Interfaces:**
- Consumes: `tdxrs` library (optional dependency)
- Produces: `fetch_xdxr_info()` 函数，获取除权除息数据

- [ ] **Step 1: Write failing test for tdxrs xdxr fetch**

```python
# tests/test_data/test_tdxrs_sync.py
from __future__ import annotations
from src.data.tdxrs_sync import is_tdxrs_available, fetch_xdxr_info

def test_is_tdxrs_available():
    """Check if tdxrs is available (may be False if not installed)."""
    result = is_tdxrs_available()
    assert isinstance(result, bool)

def test_fetch_xdxr_info_returns_list():
    """fetch_xdxr_info should return a list of xdxr events."""
    if not is_tdxrs_available():
        return  # Skip if not installed
    result = fetch_xdxr_info("000001.SZ")
    assert isinstance(result, list)
    if result:
        assert "year" in result[0]
        assert "month" in result[0]
        assert "day" in result[0]
        assert "category" in result[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_tdxrs_sync.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.data.tdxrs_sync'"

- [ ] **Step 3: Create tdxrs_sync.py**

```python
# src/data/tdxrs_sync.py
"""Tdxrs sync utilities for data not available via HTTP APIs."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_tdxrs_available() -> bool:
    """Check if tdxrs library is installed."""
    try:
        import tdxrs
        return True
    except ImportError:
        return False


def fetch_xdxr_info(symbol: str, client: Any | None = None) -> list[dict]:
    """Fetch 除权除息 information for a symbol from 通达信.

    Args:
        symbol: Stock symbol like "000001.SZ"
        client: Optional pre-connected TdxHqClient. If None, creates a new connection.

    Returns:
        List of xdxr events with fields: year, month, day, category, bonus_amount, etc.
    """
    if not is_tdxrs_available():
        logger.warning("tdxrs is not installed")
        return []

    import tdxrs

    # Parse symbol
    parts = symbol.split(".")
    code = parts[0]
    market_suffix = parts[1] if len(parts) > 1 else "SZ"
    market = 0 if market_suffix == "SZ" else 1

    # Connect if needed
    should_disconnect = client is None
    if client is None:
        client = tdxrs.TdxHqClient()
        # Use a known stable server
        client.connect("58.63.254.191", 7709)

    try:
        xdxr_list = client.get_xdxr_info(market, code)
        return xdxr_list if xdxr_list else []
    except Exception as e:
        logger.warning(f"fetch_xdxr_info failed for {symbol}: {e}")
        return []
    finally:
        if should_disconnect:
            client.disconnect()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_tdxrs_sync.py -v`
Expected: All tests PASS (or skip if tdxrs not installed)

- [ ] **Step 5: Commit**

```bash
git add src/data/tdxrs_sync.py tests/test_data/test_tdxrs_sync.py
git commit -m "feat: add tdxrs sync utilities for 除权除息 data

Provides fetch_xdxr_info() to get dividend/split data from 通达信 TCP protocol.
This data is not available via HTTP APIs (Tencent/Sina/AKShare)."
```

---

### Task 4: 创建 ClickHouse 除权除息表 + 同步任务

**Files:**
- Create: `src/data/clickhouse_xdxr_sync.py`
- Modify: `src/data/clickhouse_setup.py` (添加 xdxr_info 表创建逻辑)
- Test: `tests/test_data/test_clickhouse_xdxr_sync.py`

**Interfaces:**
- Consumes: `fetch_xdxr_info` from `src/data/tdxrs_sync.py`, ClickHouse client
- Produces: `sync_clickhouse_xdxr_info()` 函数，写入 ClickHouse `xdxr_info` 表

- [ ] **Step 1: Write failing test for xdxr sync**

```python
# tests/test_data/test_clickhouse_xdxr_sync.py
from __future__ import annotations
from src.data.clickhouse_xdxr_sync import sync_clickhouse_xdxr_info

class FakeClient:
    def __init__(self):
        self.commands = []

    def execute(self, query, params=None):
        self.commands.append((query, params))

def fake_fetch_xdxr(symbol):
    if symbol == "000001.SZ":
        return [
            {
                "year": 2023,
                "month": 6,
                "day": 15,
                "category": 1,
                "bonus_amount": 0.5,
                "ratening_amount": 0.0,
                "increased_amount": 0.0,
                "ignore": False,
            }
        ]
    return []

def test_sync_xdxr_info_inserts_data():
    """sync_clickhouse_xdxr_info should insert xdxr data into ClickHouse."""
    fake_client = FakeClient()
    result = sync_clickhouse_xdxr_info(
        client=fake_client,
        fetch_fn=fake_fetch_xdxr,
        symbols=["000001.SZ"],
    )
    assert result["inserted"] == 1
    assert len(fake_client.commands) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_clickhouse_xdxr_sync.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.data.clickhouse_xdxr_sync'"

- [ ] **Step 3: Create ClickHouse xdxr_info table schema**

Edit `src/data/clickhouse_setup.py`, add table creation:
```sql
CREATE TABLE IF NOT EXISTS xdxr_info (
    symbol String,
    year UInt16,
    month UInt8,
    day UInt8,
    category UInt8 COMMENT '1=分红, 2=送股, 3=配股, 4=缩股',
    bonus_amount Float64 COMMENT '每股分红金额（元）',
    bonus_shares Float64 COMMENT '每股送股数',
    increased_shares Float64 COMMENT '每股配股数',
    reduced_shares Float64 COMMENT '每股缩股数',
    ex_date Date MATERIALIZED toDate(concat(toString(year), '-', lpad(toString(month), 2, '0'), '-', lpad(toString(day), 2, '0'))),
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (symbol, ex_date);
```

- [ ] **Step 4: Create clickhouse_xdxr_sync.py**

```python
# src/data/clickhouse_xdxr_sync.py
"""Sync 除权除息 data from tdxrs to ClickHouse."""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def sync_clickhouse_xdxr_info(
    client: Any,
    fetch_fn: Callable[[str], list[dict]],
    symbols: list[str],
) -> dict[str, int]:
    """Sync xdxr info for given symbols into ClickHouse xdxr_info table.

    Args:
        client: ClickHouse client
        fetch_fn: Function that fetches xdxr data for a symbol (e.g., fetch_xdxr_info)
        symbols: List of stock symbols like ["000001.SZ", "600000.SH"]

    Returns dict with counts: {"inserted": N, "failed": K}
    """
    inserted = 0
    failed = 0

    for symbol in symbols:
        try:
            xdxr_list = fetch_fn(symbol)
            if not xdxr_list:
                continue

            for xdxr in xdxr_list:
                query = """
                INSERT INTO xdxr_info (
                    symbol, year, month, day, category,
                    bonus_amount, bonus_shares, increased_shares, reduced_shares
                ) VALUES
                """
                values = (
                    symbol,
                    xdxr.get("year", 0),
                    xdxr.get("month", 0),
                    xdxr.get("day", 0),
                    xdxr.get("category", 0),
                    float(xdxr.get("bonus_amount", 0.0)),
                    float(xdxr.get("ratening_amount", 0.0)),
                    float(xdxr.get("increased_amount", 0.0)),
                    float(xdxr.get("ignore", 0.0)),
                )
                client.execute(query, [values])
                inserted += 1

        except Exception as e:
            logger.warning(f"Failed to sync xdxr for {symbol}: {e}")
            failed += 1

    return {"inserted": inserted, "failed": failed}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_data/test_clickhouse_xdxr_sync.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/data/clickhouse_xdxr_sync.py tests/test_data/test_clickhouse_xdxr_sync.py src/data/clickhouse_setup.py
git commit -m "feat: add ClickHouse xdxr_info table and sync task

Syncs 除权除息 data from tdxrs (通达信) into ClickHouse.
Supports 分红, 送股, 配股, 缩股 events.
Historical data available from 1990."
```

---

### Task 5: 注册 xdxr_sync 到 data_ops 调度

**Files:**
- Modify: `src/data_ops/models.py:86-136` (添加 xdxr_sync 任务配置)
- Modify: `src/data_ops/handlers.py` (添加 xdxr_sync handler)
- Modify: `src/data_ops/runner.py:21-25` (添加 xdxr_sync 到 maintenance 组)
- Test: `tests/test_data_ops/test_models.py`, `tests/test_data_ops/test_handlers.py`

**Interfaces:**
- Consumes: `sync_clickhouse_xdxr_info` from `src/data/clickhouse_xdxr_sync.py`, `fetch_xdxr_info` from `src/data/tdxrs_sync.py`
- Produces: `xdxr_sync` 任务，`daily_time` 类型，15:30 执行

- [ ] **Step 1: Write failing test for xdxr_sync task config**

```python
# tests/test_data_ops/test_models.py (append)
def test_xdxr_sync_in_default_configs():
    """xdxr_sync should be in default task configs."""
    from src.data_ops.models import default_task_configs
    configs = default_task_configs()
    task_keys = [c.task_key for c in configs]
    assert "xdxr_sync" in task_keys, f"xdxr_sync not found in: {task_keys}"

def test_xdxr_sync_schedule():
    """xdxr_sync should be scheduled daily at 15:30."""
    from src.data_ops.models import default_task_configs
    configs = default_task_configs()
    xdxr_config = next(c for c in configs if c.task_key == "xdxr_sync")
    assert xdxr_config.schedule_kind == "daily_time"
    assert xdxr_config.schedule_config["time"] == "15:30"
    assert xdxr_config.enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_ops/test_models.py::test_xdxr_sync_in_default_configs -v`
Expected: FAIL (xdxr_sync not in configs yet)

- [ ] **Step 3: Add xdxr_sync to default_task_configs()**

Edit `src/data_ops/models.py` line 136 (end of default_task_configs list), add:
```python
        DataOpsTaskConfig(
            task_key="xdxr_sync",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "15:30"},
            max_runtime_seconds=1800,
            stale_after_seconds=900,
        ),
```

- [ ] **Step 4: Add xdxr_sync to maintenance task group**

Edit `src/data_ops/runner.py` line 24, change:
```python
    "maintenance": {"stock_master_sync", "quality_snapshot", "post_close_maintenance"},
```
to:
```python
    "maintenance": {"stock_master_sync", "quality_snapshot", "post_close_maintenance", "xdxr_sync"},
```

- [ ] **Step 5: Add xdxr_sync handler**

Edit `src/data_ops/handlers.py`, add handler function:
```python
def _handle_xdxr_sync(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for xdxr_sync task."""
    from src.data.clickhouse_xdxr_sync import sync_clickhouse_xdxr_info
    from src.data.tdxrs_sync import fetch_xdxr_info, is_tdxrs_available
    from src.clickhouse.client import get_clickhouse_client

    if not is_tdxrs_available():
        return {"status": "skipped", "reason": "tdxrs not installed"}

    client = get_clickhouse_client()

    # Get all stock symbols from ClickHouse
    symbols_result = client.execute("SELECT DISTINCT symbol FROM stocks WHERE market IN ('SZ', 'SH')")
    symbols = [row[0] for row in symbols_result]

    result = sync_clickhouse_xdxr_info(
        client=client,
        fetch_fn=fetch_xdxr_info,
        symbols=symbols,
    )
    return result
```

Then in `build_default_handlers()`, add:
```python
    handlers["xdxr_sync"] = _handle_xdxr_sync
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_data_ops/test_models.py tests/test_data_ops/test_handlers.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/data_ops/models.py src/data_ops/handlers.py src/data_ops/runner.py tests/
git commit -m "feat: register xdxr_sync task in data_ops scheduler

Scheduled daily at 15:30 (post-close) in maintenance task group.
Syncs 除权除息 data for all A-share stocks from tdxrs to ClickHouse."
```

---

### Task 6: 扩展数据质量监控

**Files:**
- Modify: `src/data/data_status.py` (添加 xdxr_info 表检查)
- Test: `tests/test_web/test_clickhouse_data_status.py`

**Interfaces:**
- Consumes: ClickHouse `xdxr_info` 表
- Produces: 质量报告中包含 xdxr 数据状态

- [ ] **Step 1: Write failing test for xdxr in data_status**

```python
# tests/test_web/test_clickhouse_data_status.py (append)
def test_inspect_includes_xdxr_info():
    """inspect_clickhouse_database should include xdxr_info checks."""
    from src.data.data_status import inspect_clickhouse_database

    class FakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "xdxr_info" in normalized:
                if "count" in normalized:
                    return [(100,)]
                return []
            return []

    result = inspect_clickhouse_database(client=FakeClient())
    assert "xdxr_info" in str(result) or any("xdxr" in str(v).lower() for v in result.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web/test_clickhouse_data_status.py::test_inspect_includes_xdxr_info -v`
Expected: FAIL (xdxr_info not in inspect yet)

- [ ] **Step 3: Add xdxr_info check to data_status.py**

Edit `src/data/data_status.py`, in `inspect_clickhouse_database()`, add a check block:
```python
    # XDXR info coverage
    xdxr_count_result = client.execute("SELECT count() FROM xdxr_info")
    xdxr_count = xdxr_count_result[0][0] if xdxr_count_result else 0
    xdxr_symbols_result = client.execute("SELECT count(DISTINCT symbol) FROM xdxr_info")
    xdxr_symbols = xdxr_symbols_result[0][0] if xdxr_symbols_result else 0

    datasets_health.append({
        "key": "xdxr_info",
        "name": "除权除息数据",
        "category": "reference",
        "source": "tdxrs (通达信)",
        "update_mechanism": "data_ops xdxr_sync (daily 15:30)",
        "consumers": ["复权计算", "策略回测"],
        "quality_rules": ["非空", "覆盖主流标的"],
        "repairable": True,
        "status": "ok" if xdxr_count > 0 else "warning",
        "issues": [] if xdxr_count > 0 else ["xdxr_info 表为空"],
        "count": xdxr_count,
        "symbol_coverage": xdxr_symbols,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web/test_clickhouse_data_status.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/data_status.py tests/test_web/test_clickhouse_data_status.py
git commit -m "feat: add xdxr_info to data quality monitoring

Includes xdxr coverage in ClickHouse quality inspection report."
```

---

## 计划总结

**最终架构：**
```
外部数据源
  │
  ├── Tencent/Sina/AKShare (HTTP API)
  │   → 日线、分钟线、实时行情
  │   → 写入: ClickHouse daily_kline, minute5_kline, quote_snapshots
  │
  └── TDXRS (TCP 协议) ← 新增
      → 除权除息（全量历史，1990 年起）
      → 写入: ClickHouse xdxr_info
      │
      ▼
┌─────────────────────────────────┐
│  ClickHouse                      │
│  + xdxr_info 表                  │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  DataAggregator (简化后)         │
│  ClickHouse → Tencent → Sina → AKShare │
│  (无 legacy local DB, 无 mootdx, 无 tdxrs)     │
└─────────────────────────────────┘
```

**改动清单：**

| # | 任务 | 类型 | 文件 |
|---|------|------|------|
| 1 | 清理 legacy local DB 遗留 | 清理 | `aggregator.py` |
| 2 | 清理 mootdx 死代码 | 清理 | `aggregator.py`, `pyproject.toml`, `check_data_sources.py`, 删除 2 个文件 |
| 3 | 创建 tdxrs 同步源 | 新增 | `tdxrs_sync.py` |
| 4 | 创建 xdxr_info 表 + 同步 | 新增 | `clickhouse_xdxr_sync.py`, `clickhouse_setup.py` |
| 5 | 注册 xdxr_sync 到 data_ops | 新增 | `models.py`, `handlers.py`, `runner.py` |
| 6 | 扩展数据质量监控 | 扩展 | `data_status.py` |

**删除的代码：**
- `src/data/mootdx_source.py` (207 行)
- `tests/test_data/test_mootdx_source.py`
- aggregator.py 中 legacy local DB + mootdx 加载逻辑
- pyproject.toml 中 mootdx 依赖声明
- check_data_sources.py 中 mootdx 检查逻辑

**新增的代码：**
- `src/data/tdxrs_sync.py` (~50 行)
- `src/data/clickhouse_xdxr_sync.py` (~60 行)
- ClickHouse `xdxr_info` 表
- data_ops 调度任务 `xdxr_sync`

**不动的部分：**
- 后台读取层（FastAPI）
- 前端（Vue）
- 现有 Tencent/Sina/AKShare 同步逻辑
- launchd 调度（复用 data_ops runner）

---

Plan complete and saved to `docs/superpowers/plans/2026-07-03-tdxrs-data-source.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
