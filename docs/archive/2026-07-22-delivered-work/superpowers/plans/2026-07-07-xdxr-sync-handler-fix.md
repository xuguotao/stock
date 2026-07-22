# XDXR Sync Handler Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `xdxr_sync` 默认数据任务 handler，使独立 data ops runner 执行该任务时不再因为不存在的 ClickHouse 导入路径崩溃。

**Architecture:** 保持 `src.data_ops.handlers` 现有任务 handler 结构不变，只把 ClickHouse client 获取方式切换到项目现有入口 `ClickHouseStockDataSource()._client_instance()`。测试层新增一个默认 handler 路径测试，证明 `xdxr_sync` 不再依赖不存在的 `src.clickhouse.client`。

**Tech Stack:** Python 3.12+、pytest、ClickHouse driver 现有封装、项目现有 `src.data.clickhouse_source.ClickHouseStockDataSource`。

---

## 文件结构

- 修改：`src/data_ops/handlers.py`
  - 负责构建并执行独立数据任务 handler。
  - 本轮只修改 `run_xdxr_sync` 的 ClickHouse client 获取方式。
- 修改：`tests/test_data_ops/test_handlers.py`
  - 新增默认 `xdxr_sync` handler 的回归测试。
  - 测试不连接真实 ClickHouse，通过 monkeypatch 替换 `ClickHouseStockDataSource` 和 `tdxrs` 可用性检查。
- 参考：`src/data/clickhouse_source.py`
  - 提供项目当前真实存在的 ClickHouse client 入口。

## Task 1: 添加失败测试

**Files:**

- Modify: `tests/test_data_ops/test_handlers.py`

- [x] **Step 1: 写一个覆盖默认 handler 路径的测试**

在 `tests/test_data_ops/test_handlers.py` 中新增测试：

```python
def test_xdxr_sync_handler_uses_clickhouse_data_source(monkeypatch) -> None:
    calls = {}

    class FakeClient:
        def execute(self, query):
            calls["query"] = query
            return [("600519.SH",), ("000001.SZ",)]

    class FakeClickHouseSource:
        def _client_instance(self):
            calls["client_created"] = True
            return FakeClient()

    monkeypatch.setattr("src.data.tdxrs_sync.is_tdxrs_available", lambda: True)
    monkeypatch.setattr("src.data_ops.handlers.ClickHouseStockDataSource", FakeClickHouseSource)

    def fake_runner(*, client, symbols):
        calls["client"] = client
        calls["symbols"] = symbols
        return {"inserted": len(symbols)}

    result = build_default_handlers(xdxr_sync_runner=fake_runner)["xdxr_sync"]({})

    assert result == {"inserted": 2}
    assert calls["client_created"] is True
    assert calls["symbols"] == ["600519.SH", "000001.SZ"]
    assert "stocks FINAL" in calls["query"]
```

- [x] **Step 2: 运行测试确认失败**

Run:

```bash
python -m pytest tests/test_data_ops/test_handlers.py::test_xdxr_sync_handler_uses_clickhouse_data_source -q
```

Expected:

实际结果：

测试失败在 `src.data_ops.handlers` 模块没有可 monkeypatch 的 `ClickHouseStockDataSource`，证明当前默认 handler 没有使用项目现有 ClickHouse 数据源入口。

## Task 2: 修复 handler

**Files:**

- Modify: `src/data_ops/handlers.py`

- [x] **Step 1: 在模块顶部引入 ClickHouse 数据源**

在 `src/data_ops/handlers.py` 顶部 import 区域增加：

```python
from src.data.clickhouse_source import ClickHouseStockDataSource
```

- [x] **Step 2: 替换不存在的 client 导入**

把 `run_xdxr_sync` 中的：

```python
from src.clickhouse.client import get_clickhouse_client
from src.data.tdxrs_sync import is_tdxrs_available
```

改为：

```python
from src.data.tdxrs_sync import is_tdxrs_available
```

把：

```python
client = get_clickhouse_client()
```

改为：

```python
client = ClickHouseStockDataSource()._client_instance()
```

- [x] **Step 3: 运行单测确认通过**

Run:

```bash
python -m pytest tests/test_data_ops/test_handlers.py::test_xdxr_sync_handler_uses_clickhouse_data_source -q
```

Expected:

实际结果：测试通过。

## Task 3: 回归验证

**Files:**

- Test: `tests/test_data_ops/test_handlers.py`
- Test: `tests/test_data_ops/test_xdxr_sync_task.py`

- [x] **Step 1: 跑 data ops 相关测试**

Run:

```bash
python -m pytest tests/test_data_ops -q
```

Expected:

实际结果：37 个 data ops 测试全部通过。

- [x] **Step 2: 跑编译检查**

Run:

```bash
python -m compileall -q src scripts
```

Expected:

实际结果：命令退出码为 0，无编译错误。

- [x] **Step 3: 检查差异**

Run:

```bash
git diff -- src/data_ops/handlers.py tests/test_data_ops/test_handlers.py docs/superpowers/reviews/2026-07-07-platform-architecture-and-data-ops-review.md docs/superpowers/plans/2026-07-07-xdxr-sync-handler-fix.md
```

Expected:

差异只包含本轮文档、新测试和 `xdxr_sync` handler 修复。

## 自检

- 计划覆盖了已确认 P0 缺陷。
- 没有把 Web 拆分、legacy local DB 清理、`DataAggregator` 收窄等 P1/P2 工作混入本轮。
- 新测试验证默认 handler 真实执行路径，而不是只验证默认配置里存在 `xdxr_sync`。
- 生产代码变更保持最小，只替换不存在的 ClickHouse client 获取方式。
