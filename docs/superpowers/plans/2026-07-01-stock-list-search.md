# 股票列表检索页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个只读检索页「股票列表」,支持按代码/名称/行业/市场/状态检索已入库股票,显示最新日线日期,行内展开摘要并能跳转个股趋势页。

**Architecture:** 后端在 `data_status.py` 新增 `fetch_stock_list(client)`,一条 ClickHouse SQL(`stocks LEFT JOIN daily_kline` 取 `max(date)`)返回全量股票 + 最新日线日期,`is_st` 由 `is_st(name)` 推导。`app.py` 注册 `GET /api/stocks`,通过 `app.state.stock_list_runner` 调用(便于测试注入 mock client)。前端新增 `StockList.vue`,一次性加载全量后客户端搜索/筛选/排序/分页,行内展开摘要,「查看趋势」emit 到 `App.vue` 复用现有 `targetSymbol` 跳转机制。

**Tech Stack:** Python / FastAPI / clickhouse-driver(后端);Vue 3 + Element Plus + Vite + TypeScript(前端);pytest(测试)。

## Global Constraints

- 所有项目文档与 UI 文案使用中文叙述;代码标识、命令、API 路径、表名、字段名、文件路径保留原文。
- 后端查询数据源为 ClickHouse `stock` 库,与 `docs/superpowers/reviews/2026-07-01-stock-vs-daily-count-gap-analysis.md` 同源。
- `is_st` 口径统一使用 `src/core/constants.py:73` 的 `is_st(name)`,不在前端重复实现。
- stocks 表结构:`symbol, name, industry, market, list_date, updated_at`(无 `is_st`、无 `delist_date` 列)。
- 前端无测试设施,前端改动靠后端测试 + 手动验证覆盖。
- 遵循外科手术式改动:只动该动的,匹配既有风格,不顺手重构相邻代码。

---

## File Structure

- **Create:** `tests/test_web/test_stocks_api.py` — 后端 `/api/stocks` 接口测试。
- **Modify:** `src/web/backend/data_status.py` — 新增 `fetch_stock_list(client)` 函数。
- **Modify:** `src/web/backend/app.py` — `create_app` 增加 `stock_list_runner` 参数并挂到 `app.state`;新增 `GET /api/stocks` 路由。
- **Modify:** `frontend/src/api/client.ts` — 新增 `StockListItem` / `StockListResponse` 类型与 `listStocks()` 方法。
- **Create:** `frontend/src/pages/StockList.vue` — 检索页。
- **Modify:** `frontend/src/App.vue` — 侧边栏菜单项 + `v-else-if` 渲染 + `open-trend` emit 处理。

---

## Task 1: 后端 `fetch_stock_list` 查询函数

**Files:**
- Modify: `src/web/backend/data_status.py`(文件末尾追加)
- Test: `tests/test_web/test_stocks_api.py`

**Interfaces:**
- Consumes: `src/core/constants.py` 的 `is_st(name) -> bool`;`src/data/clickhouse_source.py` 的 `ClickHouseStockDataSource`(用于从 env 构造 client)。
- Produces: `fetch_stock_list(client: Any | None = None) -> dict[str, Any]`,返回 `{"items": [...], "total": int}`。`items` 每项字段:`symbol, name, industry, market, list_date, last_daily_date, is_st`。`client` 为 None 时从 `STOCK_CLICKHOUSE_*` env 构造;env 未配置时抛 `RuntimeError`(路由层转 500)。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_web/test_stocks_api.py`:

```python
from __future__ import annotations

from typing import Any

from src.web.backend.data_status import fetch_stock_list


class _FakeClickHouseClient:
    """记录最后一次查询并返回预设行。"""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.last_query: str | None = None

    def execute(self, query: str, params: dict[str, Any] | None = None) -> list[tuple]:
        self.last_query = query
        return self._rows


def test_fetch_stock_list_returns_full_fields_and_is_st_derivation() -> None:
    rows = [
        ("000001.SZ", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-30"),
        ("000004.SZ", "*ST国华", "软件", "SZ", "1990-12-01", "2026-06-17"),
    ]
    client = _FakeClickHouseClient(rows)

    result = fetch_stock_list(client)

    assert result["total"] == 2
    assert result["items"] == [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "industry": "银行",
            "market": "SZ",
            "list_date": "1991-04-03",
            "last_daily_date": "2026-06-30",
            "is_st": False,
        },
        {
            "symbol": "000004.SZ",
            "name": "*ST国华",
            "industry": "软件",
            "market": "SZ",
            "list_date": "1990-12-01",
            "last_daily_date": "2026-06-17",
            "is_st": True,
        },
    ]


def test_fetch_stock_list_keeps_stocks_without_daily_via_left_join() -> None:
    # 000005 无任何日线,last_daily_date 应为 None 但仍出现在结果里
    rows = [
        ("000001.SZ", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-30"),
        ("000005.SZ", "best科技", "软件", "SZ", "1991-01-01", None),
    ]
    client = _FakeClickHouseClient(rows)

    result = fetch_stock_list(client)

    assert result["total"] == 2
    no_daily = next(item for item in result["items"] if item["symbol"] == "000005.SZ")
    assert no_daily["last_daily_date"] is None
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python -m pytest tests/test_web/test_stocks_api.py -v`
Expected: FAIL,`ImportError: cannot import name 'fetch_stock_list'`。

- [ ] **Step 3: 实现 `fetch_stock_list`**

在 `src/web/backend/data_status.py` 文件末尾追加(保持与文件内其它函数风格一致,用 `Any` 类型、显式 dict):

```python
def fetch_stock_list(client: Any | None = None) -> dict[str, Any]:
    """Return all stocks with their latest daily bar date.

    数据源为 ClickHouse `stock` 库。`is_st` 由 `is_st(name)` 推导(stocks 表无此列)。
    LEFT JOIN 保留有 stocks 记录但无任何日线的股票,其 `last_daily_date` 为 None。
    """
    if client is None:
        source = ClickHouseStockDataSource.from_env()
        if source is None:
            raise RuntimeError(
                "ClickHouse 未配置(STOCK_CLICKHOUSE_HOST 未设置),无法读取股票列表"
            )
        client = source._client_instance()

    rows = client.execute(
        """
        select
            s.symbol,
            s.name,
            s.industry,
            s.market,
            s.list_date,
            max(d.date) as last_daily_date
        from stocks s
        left join daily_kline d on d.symbol = s.symbol
        group by s.symbol, s.name, s.industry, s.market, s.list_date
        order by s.symbol
        """
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        values = tuple(row)
        name = str(values[1] or "") if len(values) > 1 else ""
        list_date = values[4] if len(values) > 4 else None
        last_daily = values[5] if len(values) > 5 else None
        items.append(
            {
                "symbol": str(values[0] or ""),
                "name": name,
                "industry": str(values[2] or "") if len(values) > 2 else "",
                "market": str(values[3] or "") if len(values) > 3 else "",
                "list_date": str(list_date) if list_date is not None else None,
                "last_daily_date": str(last_daily) if last_daily is not None else None,
                "is_st": is_st(name),
            }
        )

    return {"items": items, "total": len(items)}
```

确认 `data_status.py` 顶部已 import `is_st` 与 `ClickHouseStockDataSource`(若未 import 则补;参考文件内现有 import,`inspect_clickhouse_database` 已用 `ClickHouseStockDataSource`,通常已导入,`is_st` 来自 `src.core.constants`)。检查方式:在文件顶部 grep,若无则添加:

```python
from src.core.constants import is_st
```

(仅当确实缺失时添加;`ClickHouseStockDataSource` 已在文件中使用,无需重复 import。)

- [ ] **Step 4: 运行测试,确认通过**

Run: `python -m pytest tests/test_web/test_stocks_api.py -v`
Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add tests/test_web/test_stocks_api.py src/web/backend/data_status.py
git commit -m "feat(data-status): 新增 fetch_stock_list 查询全量股票及最新日线日期"
```

---

## Task 2: 后端 `GET /api/stocks` 路由

**Files:**
- Modify: `src/web/backend/app.py`(`create_app` 签名 + `app.state` + 路由)
- Test: `tests/test_web/test_stocks_api.py`(追加测试)

**Interfaces:**
- Consumes: Task 1 的 `fetch_stock_list(client) -> dict`。
- Produces: `GET /api/stocks` 返回 `{"items": [...], "total": int}`;失败返回 500。`create_app` 新增参数 `stock_list_runner: Callable[[], dict] = fetch_stock_list`,挂到 `app.state.stock_list_runner`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_web/test_stocks_api.py` 末尾追加:

```python
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_stocks_api_returns_items(tmp_path) -> None:
    def _runner() -> dict:
        return {
            "items": [
                {
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "industry": "银行",
                    "market": "SZ",
                    "list_date": "1991-04-03",
                    "last_daily_date": "2026-06-30",
                    "is_st": False,
                }
            ],
            "total": 1,
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        stock_list_runner=_runner,
    )
    client = TestClient(app)

    response = client.get("/api/stocks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["symbol"] == "000001.SZ"


def test_stocks_api_returns_500_when_clickhouse_unavailable(tmp_path) -> None:
    def _runner() -> dict:
        raise RuntimeError("ClickHouse 未配置")

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        stock_list_runner=_runner,
    )
    client = TestClient(app)

    response = client.get("/api/stocks")

    assert response.status_code == 500
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python -m pytest tests/test_web/test_stocks_api.py -v`
Expected: 两个新测试 FAIL(`stock_list_runner` 参数不存在;路由 404)。

- [ ] **Step 3: 在 `create_app` 增加 `stock_list_runner` 参数并挂到 `app.state`**

在 `src/web/backend/app.py` 的 `create_app` 签名中,找到 `data_status_runner=inspect_clickhouse_database,` 这一行(约 193 行),在其后加一行:

```python
    stock_list_runner=fetch_stock_list,
```

并在 import 区(文件顶部已 import `inspect_clickhouse_database,` 等 from `data_status`)把 `fetch_stock_list` 加入同一 import。找到现有:

```python
from src.web.backend.data_status import (
    inspect_clickhouse_database,
    ...
    persist_clickhouse_quality_snapshot,
)
```

在合适位置(按字母序或文件内既有顺序)加入 `fetch_stock_list,`。

然后在挂载 `app.state` 的区块(找到 `app.state.data_status_runner = data_status_runner`,约 285 行),在其后加:

```python
    app.state.stock_list_runner = stock_list_runner
```

- [ ] **Step 4: 新增 `GET /api/stocks` 路由**

在 `app.py` 中找到 `@app.get("/api/data/status")` 路由(约 396 行)之前或之后,新增:

```python
    @app.get("/api/stocks")
    def list_stocks() -> dict[str, Any]:
        return app.state.stock_list_runner()
```

注意:此路由会捕获 runner 抛出的异常,FastAPI 默认将未处理异常转为 500 响应,符合 spec「失败就明确失败」的要求。无需额外 try/except。

- [ ] **Step 5: 运行测试,确认通过**

Run: `python -m pytest tests/test_web/test_stocks_api.py -v`
Expected: 4 passed(含 Task 1 的 2 个 + 本任务 2 个)。

- [ ] **Step 6: 提交**

```bash
git add tests/test_web/test_stocks_api.py src/web/backend/app.py
git commit -m "feat(web): 新增 GET /api/stocks 股票列表接口"
```

---

## Task 3: 前端 API client 类型与方法

**Files:**
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: 后端 `GET /api/stocks` 返回结构(Task 2)。
- Produces: `StockListItem` / `StockListResponse` 类型;`api.listStocks()` 方法。

- [ ] **Step 1: 新增类型定义**

在 `frontend/src/api/client.ts` 中,在 `StockTrendResponse` interface 之后(约 903 行后)新增:

```typescript
export interface StockListItem {
  symbol: string
  name: string
  industry: string
  market: string
  list_date: string | null
  last_daily_date: string | null
  is_st: boolean
}

export interface StockListResponse {
  items: StockListItem[]
  total: number
}
```

- [ ] **Step 2: 新增 `listStocks` 方法**

在 `client.ts` 的 `export const api = { ... }` 对象内,找到 `getStockTrend(...)` 方法(约 987 行),在其后加入:

```typescript
  listStocks() {
    return request<StockListResponse>('/api/stocks')
  },
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无新增类型错误退出码 0(若项目本身有既存错误,确认本次新增代码不引入新错误)。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(frontend): 新增 listStocks API client 方法与类型"
```

---

## Task 4: 前端 `StockList.vue` 页面

**Files:**
- Create: `frontend/src/pages/StockList.vue`

**Interfaces:**
- Consumes: Task 3 的 `api.listStocks()` 与 `StockListItem` 类型。
- Produces: Vue 组件 `StockList`,emit `open-trend` 事件(payload: symbol 字符串)。

- [ ] **Step 1: 创建 `StockList.vue`**

创建 `frontend/src/pages/StockList.vue`,对齐 `DataCenter.vue` 的 `<template>`/`<script setup lang="ts">`/`<style scoped>` 结构:

```vue
<template>
  <div class="stock-list" v-loading="loading">
    <el-form :inline="true" class="filters">
      <el-form-item label="代码 / 名称">
        <el-input v-model="keyword" placeholder="代码 / 名称" clearable style="width: 200px" />
      </el-form-item>
      <el-form-item label="行业">
        <el-select
          v-model="industries"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="全部"
          style="width: 220px"
        >
          <el-option v-for="ind in industryOptions" :key="ind" :label="ind" :value="ind" />
        </el-select>
      </el-form-item>
      <el-form-item label="市场">
        <el-select
          v-model="markets"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="全部"
          style="width: 140px"
        >
          <el-option v-for="m in marketOptions" :key="m" :label="m" :value="m" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="status" style="width: 140px">
          <el-option label="全部" value="all" />
          <el-option label="非 ST" value="non_st" />
          <el-option label="ST" value="st" />
          <el-option label="退市" value="delisted" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <div class="summary">
      共 {{ items.length }} 只 / 符合筛选 {{ filtered.length }} 只
      (非 ST {{ countNonSt }} · ST {{ countSt }} · 退市 {{ countDelisted }})
    </div>

    <el-table v-if="!error" :data="paged" stripe border>
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-detail">
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="代码">{{ row.symbol }}</el-descriptions-item>
              <el-descriptions-item label="名称">{{ row.name }}</el-descriptions-item>
              <el-descriptions-item label="是否 ST">{{ row.is_st ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="行业">{{ row.industry || '—' }}</el-descriptions-item>
              <el-descriptions-item label="市场">{{ row.market || '—' }}</el-descriptions-item>
              <el-descriptions-item label="上市日">{{ row.list_date || '—' }}</el-descriptions-item>
              <el-descriptions-item label="最新日线">{{ row.last_daily_date || '—' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="代码" prop="symbol" width="120" />
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }">
          <span>{{ row.name }}</span>
          <el-tag v-if="isDelisted(row.name)" type="info" size="small" style="margin-left: 6px">退市</el-tag>
          <el-tag v-else-if="row.is_st" type="danger" size="small" style="margin-left: 6px">ST</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="行业" prop="industry" min-width="120">
        <template #default="{ row }">{{ row.industry || '—' }}</template>
      </el-table-column>
      <el-table-column label="市场" prop="market" width="80">
        <template #default="{ row }">{{ row.market || '—' }}</template>
      </el-table-column>
      <el-table-column label="上市日" prop="list_date" width="120">
        <template #default="{ row }">{{ row.list_date || '—' }}</template>
      </el-table-column>
      <el-table-column label="最新日线" width="130">
        <template #default="{ row }">
          <span :class="{ stale: isStale(row.last_daily_date) }">
            {{ row.last_daily_date || '—' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="emit('open-trend', row.symbol)">
            查看趋势
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="error" :description="error">
      <el-button @click="load">重试</el-button>
    </el-empty>

    <el-pagination
      v-if="!error"
      class="pager"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="[20, 50, 100]"
      :total="filtered.length"
      layout="total, sizes, prev, pager, next"
      @current-change="page = $event"
      @size-change="onPageSizeChange"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type StockListItem } from '../api/client'

const emit = defineEmits<{ (e: 'open-trend', symbol: string): void }>()

const items = ref<StockListItem[]>([])
const loading = ref(false)
const error = ref('')

const keyword = ref('')
const industries = ref<string[]>([])
const markets = ref<string[]>([])
const status = ref<'all' | 'non_st' | 'st' | 'delisted'>('all')
const page = ref(1)
const pageSize = ref(50)

const industryOptions = computed(() =>
  [...new Set(items.value.map((i) => i.industry).filter(Boolean))].sort()
)
const marketOptions = computed(() =>
  [...new Set(items.value.map((i) => i.market).filter(Boolean))].sort()
)

function isDelisted(name: string) {
  return name.includes('退市')
}

const latestDaily = computed(() => {
  const dates = items.value.map((i) => i.last_daily_date).filter(Boolean) as string[]
  if (!dates.length) return ''
  return dates.sort().slice(-1)[0]
})

function isStale(lastDaily: string | null) {
  if (!lastDaily || !latestDaily.value) return false
  return lastDaily < latestDaily.value
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return items.value.filter((row) => {
    if (kw) {
      const hit =
        row.symbol.toLowerCase().includes(kw) || row.name.toLowerCase().includes(kw)
      if (!hit) return false
    }
    if (industries.value.length && !industries.value.includes(row.industry)) return false
    if (markets.value.length && !markets.value.includes(row.market)) return false
    if (status.value === 'non_st' && (row.is_st || isDelisted(row.name))) return false
    if (status.value === 'st' && !row.is_st) return false
    if (status.value === 'delisted' && !isDelisted(row.name)) return false
    return true
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const countNonSt = computed(
  () => items.value.filter((i) => !i.is_st && !isDelisted(i.name)).length
)
const countSt = computed(() => items.value.filter((i) => i.is_st).length)
const countDelisted = computed(() => items.value.filter((i) => isDelisted(i.name)).length)

function onPageSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
}

function resetFilters() {
  keyword.value = ''
  industries.value = []
  markets.value = []
  status.value = 'all'
  page.value = 1
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.listStocks()
    items.value = res.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

load()
</script>

<style scoped>
.stock-list {
  background: #fff;
  padding: 16px;
  border-radius: 4px;
}

.filters {
  margin-bottom: 12px;
}

.summary {
  margin-bottom: 12px;
  color: #606266;
  font-size: 13px;
}

.expand-detail {
  padding: 12px 16px;
}

.stale {
  color: #f56c6c;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无新增类型错误。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/StockList.vue
git commit -m "feat(frontend): 新增股票列表检索页 StockList.vue"
```

---

## Task 5: 接入 `App.vue` 菜单与跳转

**Files:**
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: Task 4 的 `StockList` 组件(emit `open-trend`)。
- Produces: 侧边栏「股票列表」入口;`openPage('stock-trend', symbol)` 跳转。

- [ ] **Step 1: 添加菜单项**

在 `frontend/src/App.vue` 的 `<el-menu>` 中,找到 `<el-menu-item index="data">数据中心</el-menu-item>` 这一行(约 7 行),在其后加:

```vue
        <el-menu-item index="stock-list">股票列表</el-menu-item>
```

- [ ] **Step 2: 添加组件渲染**

在 `<el-main>` 内,找到 `<DataCenter v-else-if="activePage === 'data'" />`(约 28 行),在其后加:

```vue
        <StockList
          v-else-if="activePage === 'stock-list'"
          @open-trend="openTrend"
        />
```

- [ ] **Step 3: import 组件并新增 `openTrend` 方法**

在 `<script setup lang="ts">` 的 import 区(约 47-59 行),加入:

```typescript
import StockList from './pages/StockList.vue'
```

在 `openPage` 函数之后(约 73 行后),新增:

```typescript
function openTrend(symbol: string) {
  targetSymbol.value = symbol
  activePage.value = 'stock-trend'
}
```

注意:`openPage` 现有逻辑会在切页时清空 `targetSymbol`(`if (page !== 'stock-trend') targetSymbol.value = ''`),`openTrend` 在设 `activePage` 之前先设 `targetSymbol`,顺序正确,不会被清空。

- [ ] **Step 4: 类型检查 + 构建**

Run: `cd frontend && npx vue-tsc --noEmit && npm run build`
Expected: 类型检查通过,`vite build` 成功产出 `dist/`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/App.vue
git commit -m "feat(frontend): 接入股票列表页菜单与跳转个股趋势"
```

---

## Task 6: 手动验证

**Files:** 无代码改动。

- [ ] **Step 1: 启动后端**

确认 ClickHouse env 已配置(`STOCK_CLICKHOUSE_HOST` 等在 `.env` 中)。启动后端(参考项目既有启动方式,如 `uvicorn src.web.backend.app:create_app --factory` 或项目脚本)。

- [ ] **Step 2: 启动前端**

Run: `cd frontend && npm run dev`
打开浏览器访问 vite 提示的地址(如 `http://127.0.0.1:5173`)。

- [ ] **Step 3: 执行验证清单**

逐项核对(对应 spec「手动验证清单」):
- 侧边栏点「股票列表」,页面加载,汇总条显示总数约 5207,口径「非 ST ~4978 · ST ~229 · 退市 ~7」量级与排查报告对得上。
- 搜「茅台」→ 1 条;搜「000001」→ 平安银行等前缀匹配。
- 状态筛「ST」→ ~229 条,最新日线列普遍停在 2026-06-17(红色)。
- 状态筛「退市」→ 名称含「退市」的那些,last_daily_date 早于最新交易日(红色)。
- 任一行点「查看趋势」→ 跳到「个股趋势」页,且 symbol 正确传入(K 线加载的是该股票)。
- 行内展开 → 显示该股票全部基础信息摘要,字段齐全。

- [ ] **Step 4: 全量后端测试回归**

Run: `python -m pytest tests/test_web/ -v`
Expected: 全部通过(含新增 4 个测试 + 既有测试无回归)。

- [ ] **Step 5: 提交验证记录(可选)**

如发现 bug,回到对应 Task 修复后重新提交;无 bug 则无需提交。
