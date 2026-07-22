# 统一可用股票池标签实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可全项目复用的股票池标签快照、可配置的流动性规则、每日刷新任务和目录质量页的筛选统计。

**Architecture:** 新增 `stock_universe_profiles` 保存按标的最新标签快照，并由 `StockUniverseProfileService` 从 mootdx 目录与日线事实表计算。规则配置复用 data-ops 配置表中的唯一任务配置；后台通过质量服务同时提供快照、筛选聚合和标的明细，Vue 页面只读取这些轻量 API。

**Tech Stack:** Python、ClickHouse、FastAPI、Vue 3、Element Plus、pytest。

---

### Task 1: 标签表、规则与计算服务

**Files:**
- Create: `src/data/stock_universe_profile.py`
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Create: `tests/test_data/test_stock_universe_profile.py`
- Modify: `tests/test_data/test_mootdx_clickhouse_sync.py`

- [ ] **Step 1: 写失败测试，定义默认规则和单标的排除口径**

```python
def test_build_profile_marks_st_and_low_liquidity_as_ineligible() -> None:
    profile = build_profile(
        catalog_row=("000001.SZ", "平安银行", "SZ", False, date(1991, 4, 3)),
        daily_metrics=(date(2026, 7, 10), 20, 15, 12_000_000.0, 10_000_000.0, 0),
        rules=StockUniverseProfileRules(),
        computed_at=datetime(2026, 7, 13, 16, 15),
    )
    assert profile["universe_eligible"] is True
```

- [ ] **Step 2: 运行失败测试，确认接口尚不存在**

Run: `uv run --extra market pytest tests/test_data/test_stock_universe_profile.py -q`

Expected: FAIL，提示 `stock_universe_profile` 或 `build_profile` 不存在。

- [ ] **Step 3: 实现规则对象、标签计算、全量查询和写入**

```python
@dataclass(frozen=True)
class StockUniverseProfileRules:
    lookback_days: int = 20
    min_trading_days: int = 15
    min_average_amount: float = 10_000_000.0
    min_listing_age_days: int = 0
    include_beijing: bool = False

def refresh_stock_universe_profiles(*, client: Any, rules: StockUniverseProfileRules, symbols: Sequence[str] | None = None, progress=None) -> dict[str, Any]:
    ...
```

实现要求：使用最近 20 个开市日；`mootdx_stock_catalog final` 提供目录事实，`mootdx_stock_kline final` 提供所有来源的日线；只统计 OHLC 正数、`volume > 0`、`amount > 0` 的合法成交日；全量结果准备完成后一次写入 `stock_universe_profiles`，查询或计算失败时不写入任何不完整快照。

- [ ] **Step 4: 在 mootdx 建表集合中增加标签表，并补充建表测试**

```sql
create table if not exists stock_universe_profiles (
    symbol String,
    as_of_date Date,
    computed_at DateTime,
    rule_version UInt32,
    market LowCardinality(String),
    is_st UInt8,
    list_date Nullable(Date),
    listing_age_days UInt32,
    catalog_valid UInt8,
    latest_daily_valid UInt8,
    recent_20d_bar_count UInt16,
    recent_20d_trading_days UInt16,
    recent_20d_avg_amount Float64,
    recent_20d_median_amount Float64,
    recent_20d_zero_volume_days UInt16,
    liquidity_qualified UInt8,
    liquidity_level LowCardinality(String),
    universe_eligible UInt8,
    exclusion_reasons Array(LowCardinality(String))
) engine = ReplacingMergeTree(computed_at)
order by symbol
```

- [ ] **Step 5: 运行数据层测试，确认通过**

Run: `uv run --extra market pytest tests/test_data/test_stock_universe_profile.py tests/test_data/test_mootdx_clickhouse_sync.py -q`

Expected: PASS。

### Task 2: data-ops 唯一刷新任务

**Files:**
- Modify: `src/data_ops/mootdx_tasks.py`
- Modify: `src/data_ops/handlers.py`
- Modify: `src/data_ops/models.py`
- Modify: `src/web/backend/mootdx_monitor.py`
- Modify: `tests/test_data_ops/test_mootdx_tasks.py`
- Modify: `tests/test_data_ops/test_handlers.py`
- Modify: `tests/test_data_ops/test_models.py`

- [ ] **Step 1: 写失败测试，定义 16:15 刷新任务及其规则参数**

```python
assert next(item for item in MOOTDX_TASK_DEFINITIONS if item.task_key == "stock_universe_profile_refresh").schedule_config == {
    "time": "16:15",
    "lookback_days": 20,
    "min_trading_days": 15,
    "min_average_amount": 10_000_000,
    "min_listing_age_days": 0,
    "include_beijing": False,
}
```

- [ ] **Step 2: 运行失败测试，确认该任务尚未注册**

Run: `uv run --extra market pytest tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_models.py -q`

Expected: FAIL，任务列表中缺少 `stock_universe_profile_refresh`。

- [ ] **Step 3: 注册任务并实现 handler**

```python
def run_stock_universe_profile_refresh(params: dict[str, Any], runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    rules = StockUniverseProfileRules.from_mapping(params)
    return runner(rules=rules, symbols=params.get("symbols"), progress=params.get("progress"))
```

任务定义固定为交易日 `16:15`；默认配置保存上述阈值，用户在 data-ops 配置页调整后的配置原样传入 handler。任务审计结果必须含 `as_of_date`、`rule_version`、目录总数、目录有效数、日线有效数、流动性达标数、最终可用数和失败样本。

- [ ] **Step 4: 运行 data-ops 测试，确认通过**

Run: `uv run --extra market pytest tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_models.py tests/test_data_ops/test_repository.py -q`

Expected: PASS。

### Task 3: 质量 API 与策略读取入口

**Files:**
- Modify: `src/web/backend/mootdx_quality.py`
- Modify: `src/web/backend/app.py`
- Modify: `src/data/strategy_universe.py`
- Modify: `tests/test_web/test_mootdx_quality.py`
- Modify: `tests/test_data/test_strategy_universe.py`

- [ ] **Step 1: 写失败测试，定义快照、统计、标的明细与默认策略池读取**

```python
response = service.catalog_quality(event_limit=20)
assert response["universe_profile"]["summary"]["universe_eligible"] == 2
assert response["universe_profile"]["distributions"]["exclusion_reasons"][0]["key"] == "st"
```

- [ ] **Step 2: 运行失败测试，确认 API 输出尚无标签区块**

Run: `uv run --extra market pytest tests/test_web/test_mootdx_quality.py tests/test_data/test_strategy_universe.py -q`

Expected: FAIL，`universe_profile` 键或标签查询函数不存在。

- [ ] **Step 3: 实现轻量标签查询和 API**

```python
@app.get("/api/data/mootdx/catalog-quality/universe-profiles")
def get_mootdx_universe_profiles(filters: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    return app.state.mootdx_quality_service.universe_profiles(filters=filters, limit=limit, offset=offset)
```

`catalog_quality` 返回漏斗、规则版本、快照时间、事实是否更新、市场/上市年限/成交天数/成交额/流动性等级/排除原因的分布。明细 API 只查询 `stock_universe_profiles final`，过滤器采用已知字段和值的 JSON 数组，服务端白名单映射为参数化 SQL。`resolve_strategy_universe` 的默认路径优先读取 `universe_eligible = 1` 的标签快照，标签不存在时保留当前日线计算的兼容降级。

- [ ] **Step 4: 运行服务与策略测试，确认通过**

Run: `uv run --extra market pytest tests/test_web/test_mootdx_quality.py tests/test_web/test_data_ops_tasks_api.py tests/test_data/test_strategy_universe.py -q`

Expected: PASS。

### Task 4: 目录质量页筛选统计与标的抽屉

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/CatalogQuality.vue`
- Modify: `tests/test_frontend/test_catalog_quality_page.py`

- [ ] **Step 1: 写失败的静态页面测试，定义多选筛选和明细入口**

```python
source = Path("frontend/src/pages/CatalogQuality.vue").read_text()
assert "可用股票池筛选统计" in source
assert "v-model=\"selectedFilters\"" in source
assert "getMootdxUniverseProfiles" in source
```

- [ ] **Step 2: 运行失败测试，确认页面尚无标签统计区**

Run: `uv run --extra market pytest tests/test_frontend/test_catalog_quality_page.py -q`

Expected: FAIL，页面内容或 API 客户端方法不存在。

- [ ] **Step 3: 实现页面 API 类型和交互**

```ts
getMootdxUniverseProfiles(filters: UniverseProfileFilter[], limit = 100, offset = 0) {
  return request<MootdxUniverseProfilesResponse>(`/api/data/mootdx/catalog-quality/universe-profiles?${params}`)
}
```

页面新增：漏斗卡片、规则和刷新状态、可多选的市场/ST/上市年限/日线有效/成交天数/日均成交额/流动性等级/排除原因观察条件、分布表、点击统计项加载标的明细的抽屉。筛选只影响观察统计与抽屉，不修改任务实际同步池。刷新按钮保持原有目录质量刷新语义。

- [ ] **Step 4: 运行前端测试与构建**

Run: `uv run --extra market pytest tests/test_frontend/test_catalog_quality_page.py -q && cd frontend && npm run build`

Expected: pytest PASS，Vite build 成功。

### Task 5: 文档与端到端验证

**Files:**
- Modify: `docs/notes/mootdx-data-source.md`
- Modify: `docs/superpowers/specs/2026-07-13-stock-universe-profile-design.md`

- [ ] **Step 1: 补充中文任务说明与手工运行示例**

```text
stock_universe_profile_refresh：交易日 16:15 执行；规则位于 data_ops_task_config；手动运行可传 symbols=["000001.SZ"]；结果审计读取任务中心或 Mootdx 数据源页面。
```

- [ ] **Step 2: 运行完整相关回归测试与格式检查**

Run: `uv run --extra market pytest tests/test_data/test_stock_universe_profile.py tests/test_data/test_strategy_universe.py tests/test_data_ops/test_mootdx_tasks.py tests/test_data_ops/test_handlers.py tests/test_data_ops/test_models.py tests/test_web/test_mootdx_quality.py tests/test_web/test_data_ops_tasks_api.py tests/test_frontend/test_catalog_quality_page.py -q && git diff --check && cd frontend && npm run build`

Expected: 全部 PASS，`git diff --check` 无输出，前端构建成功。

## 覆盖核对

- 标签快照、版本与全量一致写入：Task 1。
- 16:15 唯一任务、可配阈值与审计：Task 2。
- 轻量 API、筛选明细、策略复用：Task 3。
- 页面漏斗、多选观察、分布、标的明细：Task 4。
- 中文使用说明、回归和构建验证：Task 5。
