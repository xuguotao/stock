# 数据质量日历实施计划

> **给执行代理:** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务执行本计划。步骤使用 checkbox（`- [ ]`）格式跟踪。

**目标:** 建立按交易日 × 数据源沉淀的数据质量日历，让数据中心能看清某一天哪些数据源缺失、断档、重复、节拍不足或尚未检查。

**架构:** 新增独立后端服务 `data_quality_calendar.py`，负责 ClickHouse 表结构、单日质量统计、范围查询和手动生成。FastAPI 只做请求编排，前端 DataCenter 只消费 `/api/data/quality-calendar` 和生成接口，不复用“当前健康矩阵”的瞬时判断作为历史结论。

**技术栈:** Python 3.13、FastAPI、ClickHouse、Vue 3、Element Plus、pytest、vue-tsc。

---

## 设计边界

- 第一版只覆盖核心数据链路：`daily_kline`、`minute5_kline`、`stock_quote_snapshots`、`stock_quote_snapshots_1m`、`stock_quote_snapshots_5m`、`data_source_health`。
- 不做“今日总控”和策略可用性判断。
- 不做自动大范围历史回算；页面只提供手动生成质量统计。
- 不把历史质量判断塞进 `inspect_clickhouse_database()`，避免健康矩阵和历史日历职责混在一起。
- 所有文档、页面文案、测试断言使用中文描述。

## 文件结构

- 新建: `src/web/backend/data_quality_calendar.py`
  - 负责 ClickHouse 表结构、质量源定义、统计计算、结果入库、范围查询。
- 修改: `src/web/backend/app.py`
  - 注入数据质量日历服务，新增查询与生成 API。
- 修改: `frontend/src/api/client.ts`
  - 新增数据质量日历响应类型、生成请求类型和 API 方法。
- 修改: `frontend/src/pages/DataCenter.vue`
  - 在“数据健康矩阵”和“更新任务状态”之间新增“数据日历”模块。
- 新建: `tests/test_web/test_data_quality_calendar_api.py`
  - 覆盖后端统计、入库、查询和 API。
- 修改: `tests/test_frontend/test_data_center_page.py`
  - 覆盖页面顺序、筛选器、矩阵、详情和生成入口。
- 可选修改: `docs/superpowers/specs/2026-07-01-data-quality-calendar-design.md`
  - 如实现过程中字段名发生变化，同步修正设计稿。

---

### 任务 1: 后端数据模型与 ClickHouse 表

**文件:**
- 新建: `src/web/backend/data_quality_calendar.py`
- 测试: `tests/test_web/test_data_quality_calendar_api.py`

- [ ] **步骤 1: 写失败测试，确认会创建质量日历表**

```python
from __future__ import annotations

from datetime import date, datetime

from src.web.backend.data_quality_calendar import DataQualityCalendarService


class FakeCalendarClient:
    def __init__(self):
        self.commands: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from data_quality_calendar final" in normalized:
            return []
        if "from trade_calendar" in normalized:
            return [(date(2026, 7, 1),)]
        return []


def test_data_quality_calendar_ensure_table_creates_replacing_table() -> None:
    client = FakeCalendarClient()
    service = DataQualityCalendarService(client=client)

    service.ensure_table()

    executed = [" ".join(query.lower().split()) for query, _ in client.commands]
    assert any("create table if not exists data_quality_calendar" in query for query in executed)
    assert any("replacingmergetree(checked_at)" in query for query in executed)
    assert any("order by (trade_date, source_key)" in query for query in executed)
```

- [ ] **步骤 2: 运行测试确认失败**

执行: `pytest tests/test_web/test_data_quality_calendar_api.py::test_data_quality_calendar_ensure_table_creates_replacing_table -v`

预期: 失败，提示 `src.web.backend.data_quality_calendar` 不存在。

- [ ] **步骤 3: 实现最小服务和表结构**

```python
"""按交易日沉淀 ClickHouse 数据质量日历。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource


QUALITY_SOURCE_KEYS = (
    "daily_kline",
    "minute5_kline",
    "stock_quote_snapshots",
    "stock_quote_snapshots_1m",
    "stock_quote_snapshots_5m",
    "data_source_health",
)


@dataclass(frozen=True)
class QualityCalendarSource:
    key: str
    name: str
    table: str
    expected_cadence: str
    repairability: str


QUALITY_SOURCES = {
    "daily_kline": QualityCalendarSource("daily_kline", "股票日线", "daily_kline", "日终 1 次", "可修复"),
    "minute5_kline": QualityCalendarSource("minute5_kline", "5m 分钟线", "minute5_kline", "交易时段 5 分钟桶", "可修复"),
    "stock_quote_snapshots": QualityCalendarSource("stock_quote_snapshots", "秒级行情快照", "stock_quote_snapshots", "交易时段约 10 秒", "盘中断档不可完全追回"),
    "stock_quote_snapshots_1m": QualityCalendarSource("stock_quote_snapshots_1m", "1m 快照聚合", "stock_quote_snapshots_1m", "交易时段 1 分钟桶", "可由原始快照重建"),
    "stock_quote_snapshots_5m": QualityCalendarSource("stock_quote_snapshots_5m", "5m 快照聚合", "stock_quote_snapshots_5m", "交易时段 5 分钟桶", "可由原始快照重建"),
    "data_source_health": QualityCalendarSource("data_source_health", "质量快照", "data_source_health", "质量任务写入", "重新检查可生成"),
}


class DataQualityCalendarService:
    def __init__(
        self,
        *,
        client: Any | None = None,
        host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        self._source = None if client is not None else ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._source._client_instance()
        return self._client

    def ensure_table(self) -> None:
        self.client.execute(
            """
            create table if not exists data_quality_calendar (
                trade_date Date,
                source_key LowCardinality(String),
                source_name String,
                status LowCardinality(String),
                latest_time Nullable(DateTime),
                expected_symbols UInt32,
                covered_symbols UInt32,
                coverage_ratio Float64,
                expected_buckets UInt32,
                observed_buckets UInt32,
                missing_buckets UInt32,
                duplicate_rows UInt32,
                max_gap_seconds UInt32,
                repairability String,
                summary String,
                details String,
                checked_at DateTime
            )
            engine = ReplacingMergeTree(checked_at)
            partition by toYYYYMM(trade_date)
            order by (trade_date, source_key)
            """
        )
```

- [ ] **步骤 4: 运行测试确认通过**

执行: `pytest tests/test_web/test_data_quality_calendar_api.py::test_data_quality_calendar_ensure_table_creates_replacing_table -v`

预期: 通过。

- [ ] **步骤 5: 提交**

```bash
git add src/web/backend/data_quality_calendar.py tests/test_web/test_data_quality_calendar_api.py
git commit -m "feat(data): add quality calendar table service"
```

---

### 任务 2: 单日质量统计与入库

**文件:**
- 修改: `src/web/backend/data_quality_calendar.py`
- 修改: `tests/test_web/test_data_quality_calendar_api.py`

- [ ] **步骤 1: 写失败测试，生成单日统计会写入 6 个数据源**

```python
def test_generate_day_writes_core_quality_sources() -> None:
    client = FakeQualityCalendarClient()
    service = DataQualityCalendarService(client=client)

    result = service.generate(start=date(2026, 7, 1), end=date(2026, 7, 1))

    assert result == {"generated_dates": 1, "rows": 6}
    inserts = [
        params
        for query, params in client.commands
        if "insert into data_quality_calendar" in " ".join(query.lower().split())
    ]
    assert len(inserts) == 1
    rows = inserts[0]
    assert [row[1] for row in rows] == [
        "daily_kline",
        "minute5_kline",
        "stock_quote_snapshots",
        "stock_quote_snapshots_1m",
        "stock_quote_snapshots_5m",
        "data_source_health",
    ]
    minute5 = next(row for row in rows if row[1] == "minute5_kline")
    assert minute5[3] == "warning"
    assert minute5[10] > 0
```

测试桩补充：

```python
class FakeQualityCalendarClient(FakeCalendarClient):
    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from trade_calendar" in normalized:
            return [(date(2026, 7, 1),)]
        if "from stocks" in normalized and "count()" in normalized:
            return [(2,)]
        if "from daily_kline" in normalized and "count()" in normalized:
            return [(2, datetime(2026, 7, 1, 0, 0), 2, 0)]
        if "from minute5_kline" in normalized and "count()" in normalized:
            return [(80, datetime(2026, 7, 1, 15, 0), 2, 40, 0)]
        if "from stock_quote_snapshots_1m" in normalized:
            return [(400, datetime(2026, 7, 1, 15, 0), 2, 200, 0)]
        if "from stock_quote_snapshots_5m" in normalized:
            return [(80, datetime(2026, 7, 1, 15, 0), 2, 40, 0)]
        if "from stock_quote_snapshots" in normalized:
            return [(2000, datetime(2026, 7, 1, 15, 0), 2, 1000, 0, 20)]
        if "from data_source_health" in normalized:
            return [(6, datetime(2026, 7, 1, 15, 10), 5, 1)]
        return []
```

- [ ] **步骤 2: 运行测试确认失败**

执行: `pytest tests/test_web/test_data_quality_calendar_api.py::test_generate_day_writes_core_quality_sources -v`

预期: 失败，提示 `generate` 不存在。

- [ ] **步骤 3: 实现 `generate()`、交易日列表和每个数据源统计**

核心实现要求：

```python
    def generate(
        self,
        *,
        start: date,
        end: date,
        source_keys: list[str] | None = None,
        checked_at: datetime | None = None,
    ) -> dict[str, int]:
        self.ensure_table()
        selected = [key for key in (source_keys or list(QUALITY_SOURCE_KEYS)) if key in QUALITY_SOURCES]
        trade_dates = self._trade_dates(start=start, end=end)
        now = checked_at or datetime.now()
        rows = []
        for trade_date in trade_dates:
            for key in selected:
                rows.append(self._build_row(trade_date=trade_date, source_key=key, checked_at=now))
        if rows:
            self.client.execute(
                """
                insert into data_quality_calendar
                    (trade_date, source_key, source_name, status, latest_time, expected_symbols,
                     covered_symbols, coverage_ratio, expected_buckets, observed_buckets,
                     missing_buckets, duplicate_rows, max_gap_seconds, repairability,
                     summary, details, checked_at)
                values
                """,
                rows,
            )
        return {"generated_dates": len(trade_dates), "rows": len(rows)}
```

单源统计规则：

- `daily_kline`
  - expected_symbols：非 ST 股票数。
  - covered_symbols：当日有日线的非 ST 标的数。
  - expected_buckets：1。
  - observed_buckets：`1 if covered_symbols > 0 else 0`。
  - duplicate_rows：`group by symbol, date having count() > 1` 的 extra rows。
- `minute5_kline`
  - expected_buckets：48。
  - observed_buckets：当日 distinct 5m bucket 数。
  - missing_buckets：`max(0, expected_buckets - observed_buckets)`。
  - duplicate_rows：`group by symbol, datetime having count() > 1` 的 extra rows。
- `stock_quote_snapshots`
  - expected_buckets：交易时段 10 秒轮次，第一版用 `1440`。
  - observed_buckets：当日 distinct `snapshot_at` 轮次。
  - max_gap_seconds：按 distinct `snapshot_at` 计算最大断档，忽略午休断档。
- `stock_quote_snapshots_1m`
  - expected_buckets：240。
  - observed_buckets：当日 distinct `bucket_start`。
- `stock_quote_snapshots_5m`
  - expected_buckets：48。
  - observed_buckets：当日 distinct `bucket_start`。
- `data_source_health`
  - expected_buckets：1。
  - observed_buckets：当日是否有质量快照。
  - covered_symbols：`ok` 检查数量。
  - duplicate_rows：失败检查数量，不表示行重复，仅放入 details 说明。

状态规则：

```python
def _status_from_metrics(*, expected_symbols: int, covered_symbols: int, expected_buckets: int, observed_buckets: int, duplicate_rows: int, source_key: str) -> str:
    if observed_buckets == 0 or (expected_symbols > 0 and covered_symbols == 0):
        return "failed"
    missing_buckets = max(0, expected_buckets - observed_buckets)
    coverage = covered_symbols / expected_symbols if expected_symbols else 1.0
    if duplicate_rows > 0 or missing_buckets > 0 or coverage < 0.98:
        return "warning"
    return "ok"
```

- [ ] **步骤 4: 运行后端测试**

执行: `pytest tests/test_web/test_data_quality_calendar_api.py -v`

预期: 通过。

- [ ] **步骤 5: 提交**

```bash
git add src/web/backend/data_quality_calendar.py tests/test_web/test_data_quality_calendar_api.py
git commit -m "feat(data): generate quality calendar snapshots"
```

---

### 任务 3: 范围查询和 API

**文件:**
- 修改: `src/web/backend/data_quality_calendar.py`
- 修改: `src/web/backend/app.py`
- 修改: `tests/test_web/test_data_quality_calendar_api.py`

- [ ] **步骤 1: 写失败测试，服务查询返回日期和数据源矩阵**

```python
def test_list_quality_calendar_returns_matrix_rows() -> None:
    client = StoredQualityCalendarClient()
    service = DataQualityCalendarService(client=client)

    payload = service.list(start=date(2026, 7, 1), end=date(2026, 7, 2))

    assert payload["range"] == {"start": "2026-07-01", "end": "2026-07-02"}
    assert payload["source_keys"] == list(QUALITY_SOURCE_KEYS)
    assert payload["dates"][0]["trade_date"] == "2026-07-01"
    assert payload["dates"][0]["overall_status"] == "warning"
    assert payload["dates"][0]["sources"][0]["source_key"] == "daily_kline"
```

- [ ] **步骤 2: 写失败测试，FastAPI 暴露查询和生成接口**

```python
from fastapi.testclient import TestClient
from src.web.backend.app import create_app


class FakeQualityCalendarService:
    def list(self, *, start, end, source_keys=None):
        return {
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "source_keys": source_keys or ["daily_kline"],
            "dates": [{"trade_date": start.isoformat(), "overall_status": "unchecked", "sources": []}],
        }

    def generate(self, *, start, end, source_keys=None):
        return {"generated_dates": 1, "rows": 1}


def test_data_quality_calendar_api_lists_and_generates(tmp_path) -> None:
    app = create_app(
        db_path=tmp_path / "jobs.legacy_local_db3",
        legacy stock DB path=tmp_path / "legacy-stock-store",
        data_quality_calendar_service=FakeQualityCalendarService(),
    )
    client = TestClient(app)

    listed = client.get("/api/data/quality-calendar?start=2026-07-01&end=2026-07-01")
    generated = client.post("/api/data/quality-calendar/generate", json={"start": "2026-07-01", "end": "2026-07-01"})

    assert listed.status_code == 200
    assert listed.json()["dates"][0]["overall_status"] == "unchecked"
    assert generated.status_code == 200
    assert generated.json() == {"generated_dates": 1, "rows": 1}
```

- [ ] **步骤 3: 实现 `list()` 查询**

返回结构：

```python
{
    "range": {"start": "2026-07-01", "end": "2026-07-05"},
    "source_keys": ["daily_kline", "minute5_kline"],
    "sources": [{"key": "daily_kline", "name": "股票日线", "table": "daily_kline"}],
    "dates": [
        {
            "trade_date": "2026-07-01",
            "overall_status": "warning",
            "checked_at": "2026-07-01 15:30:00",
            "sources": [
                {
                    "source_key": "daily_kline",
                    "source_name": "股票日线",
                    "status": "ok",
                    "latest_time": "2026-07-01 00:00:00",
                    "coverage_ratio": 1.0,
                    "expected_symbols": 5200,
                    "covered_symbols": 5200,
                    "expected_buckets": 1,
                    "observed_buckets": 1,
                    "missing_buckets": 0,
                    "duplicate_rows": 0,
                    "max_gap_seconds": 0,
                    "repairability": "可修复",
                    "summary": "覆盖 5200/5200，缺桶 0",
                    "details": {}
                }
            ],
        }
    ],
}
```

未入库的交易日必须补 `unchecked` 单元格，不能在页面端猜。

- [ ] **步骤 4: 在 `create_app()` 注入服务和 API**

修改函数签名：

```python
from src.web.backend.data_quality_calendar import DataQualityCalendarService

def create_app(..., data_quality_calendar_service: Any | None = None, ...):
    ...
    app.state.data_quality_calendar = data_quality_calendar_service or DataQualityCalendarService()
```

新增请求模型：

```python
class DataQualityCalendarGenerateRequest(BaseModel):
    start: date
    end: date
    source_keys: list[str] | None = None
```

新增路由：

```python
    @app.get("/api/data/quality-calendar")
    def get_data_quality_calendar(start: date, end: date, source_keys: str | None = None) -> dict[str, Any]:
        selected = [key for key in source_keys.split(",") if key] if source_keys else None
        return app.state.data_quality_calendar.list(start=start, end=end, source_keys=selected)

    @app.post("/api/data/quality-calendar/generate")
    def generate_data_quality_calendar(payload: DataQualityCalendarGenerateRequest) -> dict[str, Any]:
        return app.state.data_quality_calendar.generate(start=payload.start, end=payload.end, source_keys=payload.source_keys)
```

- [ ] **步骤 5: 运行 API 测试**

执行: `pytest tests/test_web/test_data_quality_calendar_api.py -v`

预期: 通过。

- [ ] **步骤 6: 提交**

```bash
git add src/web/backend/data_quality_calendar.py src/web/backend/app.py tests/test_web/test_data_quality_calendar_api.py
git commit -m "feat(api): expose data quality calendar"
```

---

### 任务 4: 前端 API 类型与客户端方法

**文件:**
- 修改: `frontend/src/api/client.ts`
- 修改: `tests/test_frontend/test_data_center_page.py`

- [ ] **步骤 1: 写失败测试，前端 client 暴露日历接口**

```python
def test_data_center_client_exposes_quality_calendar_api() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "DataQualityCalendarResponse" in client
    assert "DataQualityCalendarGeneratePayload" in client
    assert "getDataQualityCalendar" in client
    assert "generateDataQualityCalendar" in client
    assert "/api/data/quality-calendar" in client
    assert "/api/data/quality-calendar/generate" in client
```

- [ ] **步骤 2: 运行测试确认失败**

执行: `pytest tests/test_frontend/test_data_center_page.py::test_data_center_client_exposes_quality_calendar_api -v`

预期: 失败。

- [ ] **步骤 3: 增加 TypeScript 类型**

```ts
export interface DataQualityCalendarSource {
  key: string
  name: string
  table: string
  expected_cadence: string
  repairability: string
}

export interface DataQualityCalendarCell {
  source_key: string
  source_name: string
  status: string
  latest_time: string | null
  expected_symbols: number
  covered_symbols: number
  coverage_ratio: number
  expected_buckets: number
  observed_buckets: number
  missing_buckets: number
  duplicate_rows: number
  max_gap_seconds: number
  repairability: string
  summary: string
  details: Record<string, unknown>
}

export interface DataQualityCalendarDateRow {
  trade_date: string
  overall_status: string
  checked_at: string | null
  sources: DataQualityCalendarCell[]
}

export interface DataQualityCalendarResponse {
  range: { start: string; end: string }
  source_keys: string[]
  sources: DataQualityCalendarSource[]
  dates: DataQualityCalendarDateRow[]
}

export interface DataQualityCalendarGeneratePayload {
  start: string
  end: string
  source_keys?: string[] | null
}
```

- [ ] **步骤 4: 增加 API 方法**

```ts
  getDataQualityCalendar(start: string, end: string, sourceKeys?: string[]) {
    const params = new URLSearchParams({ start, end })
    if (sourceKeys?.length) params.set('source_keys', sourceKeys.join(','))
    return request<DataQualityCalendarResponse>(`/api/data/quality-calendar?${params.toString()}`)
  },
  generateDataQualityCalendar(payload: DataQualityCalendarGeneratePayload) {
    return request<{ generated_dates: number; rows: number }>('/api/data/quality-calendar/generate', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
```

- [ ] **步骤 5: 运行测试和类型检查**

执行:

```bash
pytest tests/test_frontend/test_data_center_page.py::test_data_center_client_exposes_quality_calendar_api -v
cd frontend && npm run build
```

预期: pytest 通过；`npm run build` 通过。

- [ ] **步骤 6: 提交**

```bash
git add frontend/src/api/client.ts tests/test_frontend/test_data_center_page.py
git commit -m "feat(frontend): add data quality calendar client"
```

---

### 任务 5: 数据中心新增数据日历模块

**文件:**
- 修改: `frontend/src/pages/DataCenter.vue`
- 修改: `tests/test_frontend/test_data_center_page.py`

- [ ] **步骤 1: 写失败测试，页面顺序和控件符合设计**

```python
def test_data_center_page_shows_quality_calendar_between_health_and_tasks() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")

    assert source.index("数据健康矩阵") < source.index("数据日历") < source.index("更新任务状态")
    assert "qualityCalendarRange" in source
    assert "qualityCalendarSourceKeys" in source
    assert "loadQualityCalendar" in source
    assert "generateQualityCalendar" in source
    assert "qualityCalendarRows" in source
    assert "qualityCalendarCellClass" in source
    assert "未检查" in source
    assert "生成质量统计" in source
```

- [ ] **步骤 2: 运行测试确认失败**

执行: `pytest tests/test_frontend/test_data_center_page.py::test_data_center_page_shows_quality_calendar_between_health_and_tasks -v`

预期: 失败。

- [ ] **步骤 3: 在模板中加入“数据日历”模块**

位置：放在健康矩阵 panel 之后，更新任务状态 panel 之前。

```vue
    <div class="panel data-quality-calendar-panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">数据日历</h2>
          <p class="section-subtitle">按交易日 × 数据源查看已沉淀的数据质量统计</p>
        </div>
        <div class="toolbar compact-toolbar">
          <el-date-picker
            v-model="qualityCalendarRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
          <el-select v-model="qualityCalendarSourceKeys" multiple collapse-tags collapse-tags-tooltip placeholder="数据源">
            <el-option
              v-for="source in qualityCalendarSources"
              :key="source.key"
              :label="source.name"
              :value="source.key"
            />
          </el-select>
          <el-button :loading="qualityCalendarLoading" @click="loadQualityCalendar">刷新</el-button>
          <el-button type="primary" plain :loading="qualityCalendarGenerating" @click="generateQualityCalendar">
            生成质量统计
          </el-button>
        </div>
      </div>

      <el-table
        :data="qualityCalendarRows"
        v-loading="qualityCalendarLoading"
        row-key="trade_date"
        empty-text="暂无数据日历统计"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="dataset-health-detail">
              <div v-for="cell in row.sources" :key="cell.source_key">
                <strong>{{ cell.source_name }}</strong>
                <span>{{ qualityCalendarCellDetail(cell) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="trade_date" label="交易日" width="130" />
        <el-table-column label="总体状态" width="120">
          <template #default="{ row }">
            <el-tag :type="qualityTagType(row.overall_status)" effect="plain">{{ qualityCalendarStatusText(row.overall_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column
          v-for="source in qualityCalendarSources"
          :key="source.key"
          :label="source.name"
          min-width="150"
        >
          <template #default="{ row }">
            <button
              class="quality-calendar-cell"
              :class="qualityCalendarCellClass(qualityCalendarCell(row, source.key)?.status)"
              type="button"
              @click="selectedQualityCalendarCell = qualityCalendarCell(row, source.key)"
            >
              <strong>{{ qualityCalendarStatusText(qualityCalendarCell(row, source.key)?.status ?? 'unchecked') }}</strong>
              <small>{{ qualityCalendarCell(row, source.key)?.summary ?? '未检查' }}</small>
            </button>
          </template>
        </el-table-column>
      </el-table>
    </div>
```

- [ ] **步骤 4: 在 script 中加入状态和方法**

```ts
const qualityCalendarRange = ref<[string, string]>(defaultQualityCalendarRange())
const qualityCalendarSourceKeys = ref<string[]>([])
const qualityCalendarLoading = ref(false)
const qualityCalendarGenerating = ref(false)
const qualityCalendarReport = ref<DataQualityCalendarResponse | null>(null)
const selectedQualityCalendarCell = ref<DataQualityCalendarCell | null>(null)

const qualityCalendarSources = computed(() => qualityCalendarReport.value?.sources ?? [])
const qualityCalendarRows = computed(() => qualityCalendarReport.value?.dates ?? [])

function defaultQualityCalendarRange(): [string, string] {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 30)
  return [formatDateInput(start), formatDateInput(end)]
}

function formatDateInput(value: Date): string {
  return value.toISOString().slice(0, 10)
}

function qualityCalendarCell(row: DataQualityCalendarDateRow, sourceKey: string) {
  return row.sources.find((cell) => cell.source_key === sourceKey) ?? null
}

function qualityCalendarStatusText(status: string) {
  if (status === 'ok') return '正常'
  if (status === 'warning') return '告警'
  if (status === 'failed') return '失败'
  if (status === 'catching_up') return '追赶中'
  if (status === 'unchecked') return '未检查'
  return status || '-'
}

async function loadQualityCalendar() {
  qualityCalendarLoading.value = true
  try {
    const [start, end] = qualityCalendarRange.value
    qualityCalendarReport.value = await api.getDataQualityCalendar(start, end, qualityCalendarSourceKeys.value)
  } finally {
    qualityCalendarLoading.value = false
  }
}

async function generateQualityCalendar() {
  qualityCalendarGenerating.value = true
  try {
    const [start, end] = qualityCalendarRange.value
    await api.generateDataQualityCalendar({
      start,
      end,
      source_keys: qualityCalendarSourceKeys.value.length ? qualityCalendarSourceKeys.value : null
    })
    await loadQualityCalendar()
  } finally {
    qualityCalendarGenerating.value = false
  }
}
```

- [ ] **步骤 5: 增加样式，保持控制台密度**

```css
.quality-calendar-cell {
  display: flex;
  width: 100%;
  min-height: 54px;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  text-align: left;
  padding: 8px;
  cursor: pointer;
}

.quality-calendar-cell small {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quality-calendar-cell.ok {
  border-color: var(--el-color-success-light-5);
  background: var(--el-color-success-light-9);
}

.quality-calendar-cell.warning,
.quality-calendar-cell.catching_up {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}

.quality-calendar-cell.failed {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}
```

- [ ] **步骤 6: 页面加载时同步加载数据日历**

在 `loadData()` 或 `onMounted()` 对应流程中调用 `loadQualityCalendar()`。失败时不要影响健康矩阵和任务状态：

```ts
const qualityCalendarResult = await Promise.allSettled([loadQualityCalendar()])
if (qualityCalendarResult[0].status === 'rejected') {
  qualityCalendarReport.value = null
}
```

- [ ] **步骤 7: 运行前端测试和构建**

执行:

```bash
pytest tests/test_frontend/test_data_center_page.py -v
cd frontend && npm run build
```

预期: 通过。

- [ ] **步骤 8: 提交**

```bash
git add frontend/src/pages/DataCenter.vue tests/test_frontend/test_data_center_page.py
git commit -m "feat(frontend): show data quality calendar"
```

---

### 任务 6: 端到端验证与真实数据抽查

**文件:**
- 只有验证暴露缺陷时才修改相关文件。

- [ ] **步骤 1: 运行后端和前端关键测试**

执行:

```bash
pytest tests/test_web/test_data_quality_calendar_api.py tests/test_frontend/test_data_center_page.py -v
cd frontend && npm run build
```

预期: 全部通过。

- [ ] **步骤 2: 启动项目**

执行:

```bash
./scripts/restart_web.sh
```

预期: 输出局域网可访问的前端和后端地址。

- [ ] **步骤 3: 生成最近 3 个交易日质量统计**

执行:

```bash
curl -sS -X POST http://127.0.0.1:5173/api/data/quality-calendar/generate \
  -H 'Content-Type: application/json' \
  -d '{"start":"2026-06-29","end":"2026-07-01"}'
```

预期: 返回类似：

```json
{"generated_dates":3,"rows":18}
```

- [ ] **步骤 4: 查询数据日历**

执行:

```bash
curl -sS 'http://127.0.0.1:5173/api/data/quality-calendar?start=2026-06-29&end=2026-07-01'
```

预期:

- `dates` 至少包含已生成的交易日。
- 每个交易日包含 6 个数据源单元。
- 存在问题的数据源显示 `warning` 或 `failed`，未统计日期显示 `unchecked`。
- 2026-07-01 如果存在盘中快照断档，应能在快照或聚合单元看到缺桶/断档摘要。

- [ ] **步骤 5: 浏览器人工验收**

打开数据中心页面，确认：

- “数据日历”位于“数据健康矩阵”和“更新任务状态”之间。
- 日期范围可选，不固定 30 个交易日。
- 未生成统计的日期显示“未检查”。
- 点击展开能看到每个数据源的覆盖率、缺桶、重复行、最大断档、可修复性。
- 点击“生成质量统计”后页面能刷新出结果。

- [ ] **步骤 6: 最终提交**

如果任务 6 产生修复：

```bash
git add src/web/backend/data_quality_calendar.py src/web/backend/app.py frontend/src/api/client.ts frontend/src/pages/DataCenter.vue tests/test_web/test_data_quality_calendar_api.py tests/test_frontend/test_data_center_page.py
git commit -m "fix(data): verify quality calendar workflow"
```

如果没有额外修复，不需要提交。

---

## 自查

- Spec coverage: 覆盖了设计稿里的 `data_quality_calendar` 表、查询 API、手动生成 API、数据中心数据日历模块、可选日期范围和核心链路数据源。
- Scope check: 没有纳入策略可用性、基金日历、模型样本日历、自动大范围回算和自动修复编排，符合第一版边界。
- Type consistency: 后端字段使用 snake_case，前端 TypeScript 保持同名消费；API 路径固定为 `/api/data/quality-calendar` 与 `/api/data/quality-calendar/generate`。
- Ambiguity resolved: “最近 30 个交易日”不作为固定限制，前端仅默认过去 30 个自然日范围，用户可改；后端根据 `trade_calendar` 返回实际交易日。
