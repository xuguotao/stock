# 研究复权数据层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 Mootdx 原始日线和 XDXR 生成经过校验、可版本化发布的研究复权因子，不改变线上策略读取口径。

**Architecture:** 纯函数层判定事件并计算单日/累计因子；存储层以候选运行写入事件审计和因子，再原子发布有效版本；研究读取层将已发布因子与原始日线关联。`research_adjustment_refresh` 在 XDXR 同步之后运行，并在上游异常时保留上一有效版本。

**Tech Stack:** Python、pandas、ClickHouse、data-ops、pytest。

---

### Task 1: 事件校验与因子纯函数

**Files:**

- Create: `src/data/research_adjustment_events.py`
- Create: `src/data/research_adjustment_validation.py`
- Test: `tests/test_data/test_research_adjustment_events.py`
- Test: `tests/test_data/test_research_adjustment_validation.py`

- [ ] **Step 1: 写入失败的单事件校验测试**

```python
def test_approved_cash_dividend_emits_ratio() -> None:
    event = {"event_date": date(2026, 1, 10), "fenhong": 1.0, "songzhuangu": 0.0,
             "peigu": 0.0, "peigujia": 0.0, "suogu": None}
    result = validate_event(event, pre_close=10.0, ex_close=9.0)
    assert result.status == "approved"
    assert result.ratio == pytest.approx(0.9)

def test_missing_ex_date_bar_is_not_eligible() -> None:
    assert validate_event({"event_date": date(2026, 1, 10)}, pre_close=10.0, ex_close=None).status == "missing_ex_date_bar"
```

- [ ] **Step 2: 验证测试先失败**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_events.py tests/test_data/test_research_adjustment_validation.py`

Expected: FAIL，因为模块和 `validate_event` 尚不存在。

- [ ] **Step 3: 实现最小纯函数**

实现 `ValidatedEvent(status, ratio, theoretical_price, error)`；只有合法前收盘、事件日价格和有限正数调整率才返回 `approved`。空 `suogu` 作为 1.0；未批准事件的 `ratio` 为 `None`。实现 `daily_ratio(events)`，只组合已批准事件并按 `(event_date, category, name)` 稳定排序。

- [ ] **Step 4: 追加累计因子测试并实现**

```python
def test_factors_rebuild_all_dates_for_one_changed_event() -> None:
    factors = build_daily_factors([date(2026, 1, 9), date(2026, 1, 10), date(2026, 1, 11)],
                                  {date(2026, 1, 10): 0.9})
    assert factors[date(2026, 1, 9)].forward_factor == pytest.approx(0.9)
    assert factors[date(2026, 1, 11)].forward_factor == pytest.approx(1.0)
```

实现前/后累计因子，不直接生成价格。

- [ ] **Step 5: 运行并提交**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_events.py tests/test_data/test_research_adjustment_validation.py`

Run: `git add src/data/research_adjustment_events.py src/data/research_adjustment_validation.py tests/test_data/test_research_adjustment_events.py tests/test_data/test_research_adjustment_validation.py && git commit -m "feat: validate research adjustment events"`

### Task 2: 版本化存储与发布

**Files:**

- Create: `src/data/research_adjustment_store.py`
- Test: `tests/test_data/test_research_adjustment_store.py`

- [ ] **Step 1: 写入失败的 DDL/发布测试**

```python
def test_publish_run_makes_only_complete_run_current() -> None:
    store = ResearchAdjustmentStore(FakeClient())
    store.ensure_tables()
    store.publish_run("run-ok", formula_version="v1", completed=True)
    assert "research_adjustment_events" in store.client.sql.lower()
    assert store.current_run("v1") == "run-ok"
```

- [ ] **Step 2: 验证失败并实现表与发布 API**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_store.py`

创建事件、日级因子和版本发布表；候选写入以 `run_id` 区分，发布表仅接受 `completed=True`。`current_run()` 只返回最近已发布运行，候选或失败运行不可见。

- [ ] **Step 3: 运行并提交**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_store.py`

Run: `git add src/data/research_adjustment_store.py tests/test_data/test_research_adjustment_store.py && git commit -m "feat: store versioned research adjustment factors"`

### Task 3: 构建服务与研究读取

**Files:**

- Create: `src/data/research_adjustment_reader.py`
- Create: `scripts/build_research_adjustment_data.py`
- Test: `tests/test_data/test_research_adjustment_reader.py`
- Test: `tests/test_scripts/test_build_research_adjustment_data.py`

- [ ] **Step 1: 写入失败的研究读取测试**

```python
def test_reader_returns_raw_and_forward_ohlcv_from_published_factors() -> None:
    frame = reader.get_bars(["000001.SZ"], date(2026, 1, 1), date(2026, 1, 2), formula_version="v1")
    assert {"raw_close", "forward_close", "backward_close", "forward_volume", "quality_status"} <= set(frame.columns)
```

- [ ] **Step 2: 验证失败并实现最小读取器**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_reader.py`

读取器仅关联 `mootdx_stock_kline final` 的 daily 行与当前发布 `run_id` 的因子；价格乘因子、成交量除以价格因子、成交额保持原值。没有发布因子时返回空集而非回退至线上服务。

- [ ] **Step 3: 实现显式构建命令并测试**

命令支持 `--symbols`、`--formula-version`、`--full`，默认只构建变化标的；写候选结果后才发布。测试断言脚本不会导入或调用 `DataAggregator`。

- [ ] **Step 4: 运行并提交**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_reader.py tests/test_scripts/test_build_research_adjustment_data.py`

Run: `git add src/data/research_adjustment_reader.py scripts/build_research_adjustment_data.py tests/test_data/test_research_adjustment_reader.py tests/test_scripts/test_build_research_adjustment_data.py && git commit -m "feat: expose research adjustment data"`

### Task 4: Data-ops 联动刷新

**Files:**

- Modify: `src/data_ops/mootdx_tasks.py`
- Modify: `src/data_ops/handlers.py`
- Test: `tests/test_data_ops/test_mootdx_tasks.py`
- Test: `tests/test_data_ops/test_handlers.py`

- [ ] **Step 1: 写入失败的任务定义与阻塞测试**

```python
def test_research_adjustment_refresh_runs_after_xdxr_at_1725() -> None:
    task = MOOTDX_TASK_BY_KEY["research_adjustment_refresh"]
    assert task.schedule_config["time"] == "17:25"

def test_refresh_handler_rejects_failed_upstream() -> None:
    with pytest.raises(RuntimeError, match="xdxr"):
        run_research_adjustment_refresh({"upstream_status": {"xdxr": "failed"}}, runner=lambda **_: {})
```

- [ ] **Step 2: 验证失败并实现任务**

Run: `uv run --no-sync pytest -q tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py -k 'research_adjustment'`

添加每日 17:25 任务；handler 检查传入的日线和 XDXR 上游状态，任一非成功则抛错、不调用构建器。正常路径把 `symbols`、`formula_version`、`full` 传给构建服务。

- [ ] **Step 3: 运行并提交**

Run: `uv run --no-sync pytest -q tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py -k 'research_adjustment'`

Run: `git add src/data_ops/mootdx_tasks.py src/data_ops/handlers.py tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py && git commit -m "feat: schedule research adjustment refresh"`

### Task 5: 回归验证与文档

**Files:**

- Modify: `docs/notes/mootdx-data-source.md`

- [ ] **Step 1: 记录研究专用口径和非目标**

写明因子表输入、17:25 刷新、`approved_only` 策略、原始数据不变和 `DataAggregator` 不受影响。

- [ ] **Step 2: 完整验证并提交**

Run: `uv run --no-sync pytest -q tests/test_data/test_research_adjustment_events.py tests/test_data/test_research_adjustment_validation.py tests/test_data/test_research_adjustment_store.py tests/test_data/test_research_adjustment_reader.py tests/test_scripts/test_build_research_adjustment_data.py tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data/test_adjustment.py tests/test_data/test_adjustment_service.py tests/test_data/test_aggregator_adjustment.py`

Run: `git diff --check && git add docs/notes/mootdx-data-source.md && git commit -m "docs: describe research adjustment data layer"`
