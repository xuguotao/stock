# 策略数据就绪度页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建策略数据就绪度页面，让用户按指定回测窗口查看股票在日线、5m 分钟线、行情快照、除权除息四个维度上的可用性，并支持受限批量回补。

**Architecture:** 采用“离线覆盖快照 + 缺口明细 + 查询时窗口聚合”的模式。data_ops 定期把每只股票每个维度的覆盖摘要写入 `stock_data_readiness`，并把逐交易日缺口写入 `stock_data_readiness_gaps`；Web API 按用户输入的 `start/end/dimensions/universe/status` 聚合窗口覆盖率并返回分页结果；前端按当前 `vue-router + feature` 架构新增独立页面。

**Tech Stack:** Python 3.12+, ClickHouse, FastAPI, Vue 3, vue-router, Element Plus, pytest, vue-tsc, Vite

---

## 当前约束

- 初始股票池来自 ClickHouse `stocks FINAL`：仅 SH/SZ，排除 ST、退市、上市未满 60 个自然日的股票；不依赖 `research_eligible`。
- 窗口就绪度以用户查询窗口为准，不再用“从最新日期往前连续天数”替代窗口判断。
- 状态取值：`ready`、`partial`、`repairable`、`unrepairable`、`no_data`。
- 回补限制：单股票单维度最多 3 次失败尝试；单次批量不超过 100 只；每日不超过 500 只。
- data_ops handler 必须可注入 runner/client，便于测试；避免 monkeypatch 私有全局对象。
- 前端必须走 `frontend/src/router.ts` 注册页面，不能恢复 `App.vue activePage` 分支。
- 前端新增代码按 feature 组织：`frontend/src/features/stock-readiness/*`，页面只负责布局和事件连接。
- `frontend/src/api/client.ts` 可以先追加类型和 API 方法；后续若继续拆 API client，再迁到 feature api 文件。

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/data/stock_data_readiness.py` | 计算股票池、维度覆盖快照、缺口明细、窗口就绪度、ClickHouse 建表与批量写入 |
| `tests/test_data/test_stock_data_readiness.py` | 纯计算和 ClickHouse SQL 边界测试 |
| `src/data_ops/handlers.py` | 注册 `stock_readiness_snapshot` 和 `stock_readiness_repair` handlers |
| `src/data_ops/models.py` | 注册默认 data_ops 任务配置 |
| `tests/test_data_ops/test_stock_readiness_handlers.py` | data_ops handler 注入式测试 |
| `src/web/backend/stock_readiness.py` | Web 服务层：summary、query、repair payload 校验 |
| `src/web/backend/app.py` | 注册 `/api/stock-readiness/*` 路由 |
| `tests/test_web/test_stock_readiness_api.py` | Web API 测试 |
| `frontend/src/features/stock-readiness/types.ts` | 前端类型 |
| `frontend/src/features/stock-readiness/formatters.ts` | 状态标签、覆盖率、日期格式化 |
| `frontend/src/features/stock-readiness/useStockReadiness.ts` | 页面数据加载、筛选、回补触发状态 |
| `frontend/src/pages/StockReadiness.vue` | 页面布局 |
| `frontend/src/router.ts` | 注册菜单和路由 |
| `frontend/src/api/client.ts` | 追加 API 类型和请求函数 |
| `tests/test_frontend/test_stock_readiness_page.py` | 前端结构测试 |

---

## 数据模型

### ClickHouse 表：`stock_data_readiness`

表记录每只股票每个维度的覆盖摘要。`dimension` 取 `daily`、`minute5`、`snapshot`、`xdxr`。

```sql
CREATE TABLE IF NOT EXISTS stock_data_readiness
(
    symbol String,
    name String,
    market LowCardinality(String),
    board LowCardinality(String),
    dimension LowCardinality(String),
    first_date Nullable(Date),
    latest_date Nullable(Date),
    covered_days UInt32,
    missing_days UInt32,
    checked_days UInt32,
    repair_attempts UInt8,
    last_repair_error String,
    computed_at DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (symbol, dimension)
```

### ClickHouse 表：`stock_data_readiness_gaps`

表记录逐交易日缺口，服务任意窗口查询和回补。

```sql
CREATE TABLE IF NOT EXISTS stock_data_readiness_gaps
(
    symbol String,
    dimension LowCardinality(String),
    trade_date Date,
    reason LowCardinality(String),
    repair_attempts UInt8,
    last_repair_error String,
    computed_at DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (dimension, trade_date, symbol)
```

维度语义：

- `daily`：`daily_kline.date` 按交易日覆盖。
- `minute5`：`minute5_kline.datetime` 聚合到交易日覆盖。
- `snapshot`：`stock_quote_snapshots.snapshot_at` 聚合到交易日覆盖。
- `xdxr`：不是逐交易日行情覆盖。第一版只记录同步检查状态和最近 `ex_date`，不把“无除权事件日期”算作缺口。后续如需严格调整因子完备性，应新增专门的 corporate action 审计任务。

### API 查询口径

`GET /api/stock-readiness` 参数：

- `start`: `YYYY-MM-DD`
- `end`: `YYYY-MM-DD`
- `dimensions`: comma list，默认 `daily,minute5`
- `status`: `all|ready|partial|repairable|unrepairable|no_data`
- `market`: `all|SH|SZ`
- `board`: `all|MAIN|STAR|CHINEXT`
- `q`: 股票代码或名称关键字
- `page`, `page_size`

窗口状态计算：

- `ready`: 该维度在 `[start, end]` 内无缺口。
- `no_data`: 维度没有覆盖记录，或窗口内全部交易日缺失。
- `unrepairable`: 窗口内有缺口，且任一缺口 `repair_attempts >= 3`。
- `repairable`: 窗口内有缺口，缺口 `repair_attempts < 3`，且该维度支持自动回补。
- `partial`: 窗口内有缺口，但该维度不支持自动回补或暂不应自动回补。

返回项每只股票包含 `dimensions` 字段，维度结构：

```json
{
  "status": "repairable",
  "coverage_ratio": 0.97,
  "covered_days": 175,
  "expected_days": 180,
  "missing_days": 5,
  "missing_samples": ["2026-06-18", "2026-06-19"],
  "first_date": "2020-01-02",
  "latest_date": "2026-07-07",
  "repair_attempts": 1,
  "repairable": true
}
```

---

## Task 1: 核心计算模块

**Files:**
- Create: `src/data/stock_data_readiness.py`
- Create: `tests/test_data/test_stock_data_readiness.py`

- [ ] **Step 1: 写股票池过滤失败测试**

测试要求：
- SH/SZ 正常股票保留。
- BJ、ST、退市、上市未满 60 天排除。

Run: `python -m pytest tests/test_data/test_stock_data_readiness.py::test_initial_pool_filters_market_name_and_listing_age -v`
Expected: FAIL with `ModuleNotFoundError` or missing function.

- [ ] **Step 2: 实现 `compute_initial_pool(client, as_of)`**

接口：

```python
def compute_initial_pool(client: Any, *, as_of: date) -> list[dict[str, Any]]:
    ...
```

实现要求：
- 查询 `stocks FINAL` 的 `symbol,name,market,list_date`。
- `market in ("SH", "SZ")`。
- 名称包含 `ST`、以 `退市` 开头、以 `退` 或 `退市` 结尾时排除。
- `as_of - list_date < 60 days` 时排除。
- 返回 `symbol/name/market/board/list_date`，其中 `board` 由代码规则推导：`688* -> STAR`，`300* -> CHINEXT`，其他为 `MAIN`。

- [ ] **Step 3: 写窗口覆盖失败测试**

测试 `evaluate_window_coverage(trade_dates, data_dates, repair_attempts)`：
- 全覆盖返回 `ready`。
- 缺 1 天且 attempts < 3 返回 `repairable`。
- 缺 1 天且 attempts >= 3 返回 `unrepairable`。
- 无数据返回 `no_data`。

Run: `python -m pytest tests/test_data/test_stock_data_readiness.py::test_evaluate_window_coverage_statuses -v`
Expected: FAIL with missing function.

- [ ] **Step 4: 实现窗口覆盖函数**

接口：

```python
def evaluate_window_coverage(
    *,
    trade_dates: list[date],
    data_dates: set[date],
    repair_attempts: int,
) -> dict[str, Any]:
    ...
```

实现要求：
- `expected_days = len(trade_dates)`。
- `covered_days = number of trade_dates present in data_dates`。
- `missing_days = expected_days - covered_days`。
- `coverage_ratio = covered_days / expected_days`，当 `expected_days == 0` 时为 `0`。
- 状态按“API 查询口径”执行。

- [ ] **Step 5: 写 ClickHouse 表和批量写入失败测试**

测试：
- `ensure_readiness_table(client)` 执行包含 `CREATE TABLE IF NOT EXISTS stock_data_readiness` 和 `stock_data_readiness_gaps` 的 SQL。
- `persist_readiness_snapshot(client, rows, gap_rows)` 使用批量 insert，不逐行 insert。

Run: `python -m pytest tests/test_data/test_stock_data_readiness.py::test_persist_readiness_snapshot_uses_batch_insert -v`
Expected: FAIL with missing function.

- [ ] **Step 6: 实现建表和批量写入**

接口：

```python
def ensure_readiness_table(client: Any) -> None:
    ...

def persist_readiness_snapshot(
    client: Any,
    rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
) -> None:
    ...
```

实现要求：
- 表结构使用上文两个 ClickHouse 表。
- `rows` 非空时一次 `INSERT INTO stock_data_readiness (...) VALUES`，参数为 tuple 列表。
- `gap_rows` 非空时一次 `INSERT INTO stock_data_readiness_gaps (...) VALUES`，参数为 tuple 列表。
- 两个列表都为空时直接返回。

- [ ] **Step 7: 运行核心测试**

Run: `python -m pytest tests/test_data/test_stock_data_readiness.py -v`
Expected: all tests pass.

---

## Task 2: data_ops 快照任务

**Files:**
- Modify: `src/data_ops/handlers.py`
- Modify: `src/data_ops/models.py`
- Create: `tests/test_data_ops/test_stock_readiness_handlers.py`

- [ ] **Step 1: 写 handler 注册失败测试**

测试：

```python
from src.data_ops.handlers import build_default_handlers

def test_stock_readiness_snapshot_handler_is_registered():
    handlers = build_default_handlers(stock_readiness_snapshot_runner=lambda params: {"total": 0})
    assert "stock_readiness_snapshot" in handlers
```

Run: `python -m pytest tests/test_data_ops/test_stock_readiness_handlers.py::test_stock_readiness_snapshot_handler_is_registered -v`
Expected: FAIL because parameter/handler is not registered.

- [ ] **Step 2: 扩展 `build_default_handlers` 注入点**

新增可选参数：

```python
stock_readiness_snapshot_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None
stock_readiness_repair_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None
```

默认 runner 从 `src.data.stock_data_readiness` 导入：
- `run_readiness_snapshot(params)`
- `run_readiness_repair(params)`

返回 handlers：
- `stock_readiness_snapshot`
- `stock_readiness_repair`

- [ ] **Step 3: 写默认任务配置失败测试**

测试 `default_task_configs()` 包含：
- `stock_readiness_snapshot`
- daily time，例如 `15:40`
- `max_runtime_seconds >= 1800`

Run: `python -m pytest tests/test_data_ops/test_stock_readiness_handlers.py::test_stock_readiness_snapshot_default_config_exists -v`
Expected: FAIL.

- [ ] **Step 4: 注册默认任务配置**

在 `src/data_ops/models.py` 的 `default_task_configs()` 追加：

```python
DataOpsTaskConfig(
    task_key="stock_readiness_snapshot",
    enabled=True,
    schedule_kind="daily_time",
    schedule_config={"time": "15:40"},
    max_runtime_seconds=3600,
    stale_after_seconds=900,
)
```

回补任务不默认开启，只允许手动触发：

```python
DataOpsTaskConfig(
    task_key="stock_readiness_repair",
    enabled=False,
    schedule_kind="manual",
    schedule_config={},
    max_runtime_seconds=3600,
    stale_after_seconds=900,
)
```

- [ ] **Step 5: 运行 data_ops 测试**

Run: `python -m pytest tests/test_data_ops -q`
Expected: all tests pass.

---

## Task 3: 后端服务层和 API

**Files:**
- Create: `src/web/backend/stock_readiness.py`
- Modify: `src/web/backend/app.py`
- Create: `tests/test_web/test_stock_readiness_api.py`

- [ ] **Step 1: 写服务层 summary 失败测试**

测试 `build_readiness_summary(client, start, end, dimensions)`：
- 返回 `total_symbols`
- 返回每个维度的 `ready/repairable/unrepairable/no_data` 计数
- 使用 fake client，不依赖真实 ClickHouse

Run: `python -m pytest tests/test_web/test_stock_readiness_api.py::test_build_readiness_summary_groups_statuses -v`
Expected: FAIL with missing module.

- [ ] **Step 2: 实现服务层纯函数**

接口：

```python
def build_readiness_summary(client: Any, *, start: date, end: date, dimensions: list[str]) -> dict[str, Any]:
    ...

def query_readiness(
    client: Any,
    *,
    start: date,
    end: date,
    dimensions: list[str],
    status: str = "all",
    market: str = "all",
    board: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    ...
```

实现要求：
- 从 `stock_data_readiness FINAL` 读取覆盖摘要，从 `stock_data_readiness_gaps FINAL` 读取窗口内缺口。
- 交易日列表从 `trade_calendar` 读取 `[start, end]`。
- 对每个维度调用 `evaluate_window_coverage`，其中 `data_dates` 由交易日列表减去窗口内 gap dates 得到。
- 分页在服务层完成，返回 `items/total/page/page_size`。
- SQL sort key 使用白名单，不能直接拼用户输入。

- [ ] **Step 3: 写路由测试**

使用 `create_app(run_jobs_inline=True, ...)` 的现有测试模式。测试：
- `GET /api/stock-readiness/summary?start=...&end=...` 返回 200。
- `GET /api/stock-readiness?start=...&end=...` 返回分页结构。
- 缺少 start/end 返回 422 或 400。

Run: `python -m pytest tests/test_web/test_stock_readiness_api.py -v`
Expected: route tests fail before route registration.

- [ ] **Step 4: 注册路由**

在 `src/web/backend/app.py` 注册：
- `GET /api/stock-readiness/summary`
- `GET /api/stock-readiness`
- `POST /api/stock-readiness/repair`

实现约束：
- 路由内只做参数解析和调用服务层。
- ClickHouse client 通过 `app.state` 或现有 `ClickHouseStockDataSource()._client_instance()` 获取，测试必须可注入。
- repair route 创建 job kind：`stock_readiness_repair`，payload 包含 `symbols/dimensions/start/end`。

- [ ] **Step 5: 运行 Web 测试**

Run: `python -m pytest tests/test_web/test_stock_readiness_api.py tests/test_web/test_health_api.py -q`
Expected: all tests pass.

---

## Task 4: 前端 API 和 Feature 模块

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/features/stock-readiness/types.ts`
- Create: `frontend/src/features/stock-readiness/formatters.ts`
- Create: `frontend/src/features/stock-readiness/useStockReadiness.ts`
- Create: `tests/test_frontend/test_stock_readiness_page.py`

- [ ] **Step 1: 写前端结构失败测试**

测试要求：
- `frontend/src/features/stock-readiness/types.ts` 存在并导出 `StockReadinessItem`。
- `useStockReadiness.ts` 存在并调用 `api.getStockReadiness`。
- `frontend/src/router.ts` 包含 `name: 'stock-readiness'`。

Run: `python -m pytest tests/test_frontend/test_stock_readiness_page.py -v`
Expected: FAIL with missing files.

- [ ] **Step 2: 追加 API 类型和请求**

在 `frontend/src/api/client.ts` 追加：

```ts
export interface StockReadinessDimension {
  status: 'ready' | 'partial' | 'repairable' | 'unrepairable' | 'no_data' | string
  coverage_ratio: number
  covered_days: number
  expected_days: number
  missing_days: number
  first_date: string | null
  latest_date: string | null
  repair_attempts: number
  repairable: boolean
}

export interface StockReadinessItem {
  symbol: string
  name: string
  market: string
  board: string
  dimensions: Record<string, StockReadinessDimension>
}
```

API 方法：
- `getStockReadinessSummary(params)`
- `getStockReadiness(params)`
- `repairStockReadiness(payload)`

- [ ] **Step 3: 实现 feature types/formatters/composable**

`useStockReadiness.ts` 负责：
- 默认窗口：最近 180 天。
- 默认维度：`daily`、`minute5`。
- 加载 summary 和 table。
- 管理 `loading/error/page/pageSize/filters`。
- 调用 `repairStockReadiness` 并刷新列表。

`formatters.ts` 负责：
- `statusText`
- `statusType`
- `formatCoverage`
- `dimensionLabel`

- [ ] **Step 4: 运行前端结构测试**

Run: `python -m pytest tests/test_frontend/test_stock_readiness_page.py -v`
Expected: tests pass.

---

## Task 5: 前端页面和路由

**Files:**
- Create: `frontend/src/pages/StockReadiness.vue`
- Modify: `frontend/src/router.ts`
- Modify: `tests/test_frontend/test_stock_readiness_page.py`

- [ ] **Step 1: 创建页面**

页面必须包含：
- 日期范围选择器。
- 维度多选：日线、5m、行情快照、除权除息。
- 状态、市场、板块、关键字筛选。
- summary cards：总数、全部 ready、可回补、不可回补、无数据。
- 表格：股票、市场、板块、每个维度的状态/覆盖率/缺失天数/最新日期。
- 回补按钮：仅当至少一个选择维度 `repairable` 时可点击。

- [ ] **Step 2: 注册路由**

在 `frontend/src/router.ts`：
- import `StockReadiness`。
- `navigationRoutes` 增加 `{ name: 'stock-readiness', label: '策略数据就绪度' }`。
- routes 增加 `{ path: '/stock-readiness', name: 'stock-readiness', component: StockReadiness }`。

- [ ] **Step 3: 更新前端测试**

测试：
- router 注册 `stock-readiness`。
- 页面包含“策略数据就绪度”“回补”“覆盖率”“缺失天数”。
- 页面使用 `useStockReadiness`。

Run: `python -m pytest tests/test_frontend/test_stock_readiness_page.py -v`
Expected: tests pass.

- [ ] **Step 4: 前端构建**

Run: `cd frontend && npm run build`
Expected: `vue-tsc --noEmit` and `vite build` pass.

---

## Task 6: 集成验证

- [ ] **Step 1: 运行核心数据测试**

Run: `python -m pytest tests/test_data/test_stock_data_readiness.py -q`
Expected: pass.

- [ ] **Step 2: 运行 data_ops 测试**

Run: `python -m pytest tests/test_data_ops/test_stock_readiness_handlers.py tests/test_data_ops/test_handlers.py -q`
Expected: pass.

- [ ] **Step 3: 运行 Web 测试**

Run: `python -m pytest tests/test_web/test_stock_readiness_api.py tests/test_web/test_health_api.py -q`
Expected: pass.

- [ ] **Step 4: 运行前端测试**

Run: `python -m pytest tests/test_frontend -q`
Expected: pass.

- [ ] **Step 5: 前端构建**

Run: `cd frontend && npm run build`
Expected: pass.

- [ ] **Step 6: 手动冒烟**

启动现有 Web 服务后检查：
- `/stock-readiness` 页面可打开。
- 默认窗口能加载 summary 和列表。
- 改变日期范围会刷新结果。
- 对 repairable 行触发回补会创建 job。

---

## 风险和后续优化

- `xdxr` 第一版只做同步检查状态，不做逐交易日完整性判断；如果策略开始依赖精确复权因子，应新增 corporate action 审计表。
- `frontend/src/api/client.ts` 仍是全局 API 文件；本计划先追加，后续可按 feature 拆 API client。
- 回补 runner 第一版只需要创建受限任务和记录尝试次数；具体多数据源优先级可在后续计划中细化。
- 如果 ClickHouse `trade_calendar` 对停牌没有区分，本页面展示的是“交易日维度的数据覆盖”，不是“真实应有行情行”的严格判定。

## Self-Review

- 已移除旧 `activePage` 前端模式，改为 `vue-router` 注册。
- 已把核心口径从“最新连续天数”修正为“按查询窗口评估覆盖率”。
- 已统一 `determine_status` 的矛盾，改由 `evaluate_window_coverage` 直接返回窗口状态。
- 已新增 `stock_data_readiness_gaps` 缺口明细表，避免用聚合摘要错误回答任意窗口查询。
- 已明确批量写入，避免逐行 insert。
- 已明确 data_ops runner/client 注入边界，避免测试依赖私有全局 monkeypatch。
