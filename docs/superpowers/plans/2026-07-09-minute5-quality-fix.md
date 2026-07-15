# 5m 分钟线质量巡检修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 5m 质量巡检页面的数据层 bug 和信息架构问题，使页面准确反映数据质量并支撑"修复缺口"工作流。

**Architecture:** 后端 `Minute5QualityService` 增加 incomplete symbol 检测和 amount zero 统计；`backfill_plan` 扩展缺口分类；前端 `Minute5Quality.vue` 更新类型和布局，新增最新交易日覆盖卡片，重构信息层级。

**Tech Stack:** Python (FastAPI, clickhouse_driver), Vue 3 + TypeScript + Element Plus

## Global Constraints

- Python 运行环境：`uv run python`，禁止直接 `python`
- 编辑已有代码时：只动该动的，匹配既有风格，不重构没坏的东西
- 改动产生孤儿时：删除因**本次改动**而变得无用的 import/变量/函数，不删除既有的死代码
- 所有改动必须有对应测试，TDD 流程
- 后端新增字段是向后兼容的（只追加，不改已有字段语义），前端类型需同步更新

---

## 涉及文件

### 后端
- **Modify:** `src/web/backend/minute5_quality.py` — 核心质量服务，所有修复在此
- **Test:** `tests/test_web/test_minute5_quality_service.py` — FakeMinute5Client 需同步更新

### 前端
- **Modify:** `frontend/src/api/client.ts` — 类型定义和 API 方法
- **Modify:** `frontend/src/pages/Minute5Quality.vue` — 页面布局和展示

### API 路由
- **Modify:** `src/web/backend/app.py` — 如需新增接口（当前计划不需要）

---

### Task 1: 后端 — summary() 状态修复 + 最新交易日覆盖

**Files:**
- Modify: `src/web/backend/minute5_quality.py`
- Test: `tests/test_web/test_minute5_quality_service.py`

**问题:** `summary()` 的 `status` 判定不考虑标的 bar 数缺口。2026-07-08 有 4,959/4,987 只标的不满 48 bar，但 `status` 仍为 `ok`。

**接口变更:**
- 新增方法 `_incomplete_symbols_on_latest_date() -> dict[str, int]`，返回 `{complete, partial, missing}`
- `summary()` 返回值新增 `latest_day` 字段
- `summary()` 的 `status` 判定新增 `incomplete_symbols > 0` 条件

- [ ] **Step 1: 写 `_incomplete_symbols_on_latest_date` 方法**

在 `Minute5QualityService` 类中，`_expected_symbols()` 方法之后添加：

```python
    def _incomplete_symbols_on_latest_date(self, trade_date: date | None = None) -> dict[str, int]:
        target = trade_date or self._latest_date()
        if target is None:
            return {"complete": 0, "partial": 0, "missing": 0}
        rows = self._execute(
            f"""
            select
                countIf(bars >= %(expected)s) as complete,
                countIf(bars > 0 and bars < %(expected)s) as partial,
                countIf(bars = 0) as missing
            from (
                select e.symbol, ifNull(o.bars, 0) as bars
                from (
                    select s.symbol
                    from stocks AS s
                    inner join daily_kline AS d
                        on d.symbol = s.symbol and d.date = (select max(date) from daily_kline)
                    where upper(s.market) in ('SH', 'SZ')
                        and {NON_ST_STOCK_PREDICATE}
                    group by s.symbol
                ) e
                left join (
                    select symbol, uniqExact(datetime) as bars
                    from minute5_kline
                    where toDate(datetime) = %(trade_date)s
                    group by symbol
                ) o on o.symbol = e.symbol
            )
            """,
            {"trade_date": target, "expected": EXPECTED_FULL_DAY_BUCKETS},
        )
        row = rows[0] if rows else (0, 0, 0)
        return {
            "complete": int(row[0] or 0),
            "partial": int(row[1] or 0),
            "missing": int(row[2] or 0),
        }
```

- [ ] **Step 2: 修改 `summary()` 方法**

在 `summary()` 方法中：

1. 在 `non_market_session = ...` 之后添加：
```python
        latest_day_coverage = self._incomplete_symbols_on_latest_date(latest_date)
        incomplete_symbols = latest_day_coverage["partial"] + latest_day_coverage["missing"]
```

2. 修改 status 判定行（原 line 71）：
```python
        status = (
            "ok"
            if duplicate_groups == 0
            and invalid_ohlc == 0
            and non_5m_boundary == 0
            and non_market_session == 0
            and incomplete_symbols == 0
            else "warning"
        )
```

3. 在 return dict 的 `"latest"` 字段之后、`"issues"` 字段之前添加：
```python
            "latest_day": {
                "trade_date": _format_date(latest_date),
                "complete_symbols": latest_day_coverage["complete"],
                "partial_symbols": latest_day_coverage["partial"],
                "missing_symbols": latest_day_coverage["missing"],
                "expected_symbols": expected_symbols,
            },
```

- [ ] **Step 3: 更新 FakeMinute5Client 测试桩**

在 `tests/test_web/test_minute5_quality_service.py` 的 `FakeMinute5Client.execute()` 中，在 `return []` 之前添加对 `_incomplete_symbols_on_latest_date` 查询的匹配：

```python
        if "countif(bars >= " in normalized and "countif(bars > 0 and bars < " in normalized:
            return [(2, 1, 0)]  # 2 complete, 1 partial (000002 has 46 bars), 0 missing
```

- [ ] **Step 4: 更新现有测试**

修改 `test_minute5_quality_summary_rolls_up_core_integrity_signals` 的 assertion：

```python
    # 原来: assert payload["status"] == "warning"  (因为 invalid_ohlc=1)
    # 现在 still "warning" 但需验证 latest_day 字段存在
    assert payload["status"] == "warning"
    assert "latest_day" in payload
    assert payload["latest_day"]["complete_symbols"] == 2
    assert payload["latest_day"]["partial_symbols"] == 1
    assert payload["latest_day"]["missing_symbols"] == 0
    assert payload["latest_day"]["expected_symbols"] == 3
```

- [ ] **Step 5: 新增测试 — 全部完成时 status 为 ok**

```python
def test_minute5_quality_summary_ok_when_all_symbols_complete() -> None:
    class AllCompleteClient(FakeMinute5Client):
        def execute(self, query, params=None):
            result = super().execute(query, params)
            if "countif(bars >= " in " ".join(query.lower().split()):
                return [(3, 0, 0)]  # all 3 complete
            return result

    service = Minute5QualityService(client=AllCompleteClient())
    # 注意: FakeMinute5Client 返回 invalid_ohlc=1, 所以 status 仍为 warning
    # 我们只验证 latest_day 字段
    payload = service.summary()
    assert payload["latest_day"]["complete_symbols"] == 3
```

另外新增一个隔离测试，专门验证 incomplete_symbols 对 status 的影响：

```python
def test_minute5_quality_summary_status_reflects_incomplete_symbols() -> None:
    class CleanClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "count(), uniqexact(symbol), min(datetime), max(datetime)" in normalized:
                return [(120, 3, datetime(2026, 7, 1, 9, 35), datetime(2026, 7, 8, 15, 0))]
            if "group by symbol, datetime" in normalized and "having count() > 1" in normalized:
                return [(0, 0)]
            if "countif(open <= 0" in normalized:
                return [(0, 0, 0, 0, 0)]  # no invalid
            if "tominute(datetime) % 5" in normalized:
                return [(0,)]
            if "not ((tohour(datetime)" in normalized:
                return [(0,)]
            if "max(todate(datetime))" in normalized:
                return [(date(2026, 7, 8),)]
            if "covered >= greatest" in normalized:
                return [(datetime(2026, 7, 8, 15, 0), 3)]
            if "group by datetime" in normalized and "order by datetime desc" in normalized and "limit 1" in normalized:
                return [(datetime(2026, 7, 8, 15, 0), 3)]
            if "from ( select s.symbol" in normalized and "inner join daily_kline" in normalized:
                return [(3,)]
            if "countif(bars >= " in normalized:
                return [(2, 1, 0)]  # 1 incomplete
            return []

    service = Minute5QualityService(client=CleanClient())
    payload = service.summary()
    # invalid_ohlc=0, duplicates=0, boundary=0, session=0, but incomplete=1
    assert payload["status"] == "warning"
    assert payload["latest_day"]["partial_symbols"] == 1
```

- [ ] **Step 6: 运行测试并确认全部通过**

```bash
uv run pytest tests/test_web/test_minute5_quality_service.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/web/backend/minute5_quality.py tests/test_web/test_minute5_quality_service.py
git commit -m "fix: summary() status accounts for incomplete symbol bar counts

- Add _incomplete_symbols_on_latest_date() returning complete/partial/missing counts
- Include incomplete_symbols > 0 in status == 'ok' check
- Add latest_day field to summary response
- Update tests for new field and status logic

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 后端 — `_invalid_stats()` 增加 `zero_amount` 统计

**Files:**
- Modify: `src/web/backend/minute5_quality.py`
- Test: `tests/test_web/test_minute5_quality_service.py`

**问题:** 80.5% 的 amount 字段为零（新浪 API 不返回 amount），但 `summary()` 的 `issues` 中没有体现。

**接口变更:**
- `_invalid_stats()` 新增 `countIf(amount = 0) as zero_amount`
- `summary()` 的 `issues` dict 自动包含 `zero_amount`（通过 `**invalid` 展开）
- `summary()` status 判定**不变** — amount 零值是已知源端限制，不应使 status 变 warning

- [ ] **Step 1: 修改 `_invalid_stats()` SQL**

在 `_invalid_stats()` 方法的 SQL 中，`countIf(amount < 0) as negative_amount` 之后添加：

```python
            select
                countIf(open <= 0 or high <= 0 or low <= 0 or close <= 0) as non_positive_ohlc,
                countIf(high < greatest(open, close, low)) as high_invalid,
                countIf(low > least(open, close, high)) as low_invalid,
                countIf(volume < 0) as negative_volume,
                countIf(amount < 0) as negative_amount,
                countIf(amount = 0) as zero_amount
            from minute5_kline
```

在 return dict 中添加：
```python
        return {
            "non_positive_ohlc": int(row[0] or 0),
            "high_invalid": int(row[1] or 0),
            "low_invalid": int(row[2] or 0),
            "negative_volume": int(row[3] or 0),
            "negative_amount": int(row[4] or 0),
            "zero_amount": int(row[5] or 0),
        }
```

- [ ] **Step 2: 更新 FakeMinute5Client**

修改 `FakeMinute5Client` 中 `countif(open <= 0` 的匹配返回，从 5 元组改为 6 元组：

```python
        if "countif(open <= 0" in normalized:
            return [(0, 1, 0, 0, 0, 80)]  # 最后一个是 zero_amount
```

注意：`invalid_ohlc = sum(invalid.values())` 会把 zero_amount 加进去！需要修改 `summary()` 中的计算：

在 `summary()` 方法中，把：
```python
        invalid_ohlc = sum(invalid.values())
```
改为只汇总真正的 OHLC 异常：
```python
        invalid_ohlc = (
            invalid.get("non_positive_ohlc", 0)
            + invalid.get("high_invalid", 0)
            + invalid.get("low_invalid", 0)
        )
```

这样 `invalid_ohlc` 保持原来的语义（OHLC 逻辑异常），`zero_amount` 作为独立的 issues 字段存在但不影响 `invalid_ohlc` 计数。

- [ ] **Step 3: 运行测试确认**

```bash
uv run pytest tests/test_web/test_minute5_quality_service.py -v
```

验证 `payload["issues"]["zero_amount"] == 80` 且 `payload["issues"]["invalid_ohlc"] == 1`（不变）。

- [ ] **Step 4: Commit**

```bash
git add src/web/backend/minute5_quality.py tests/test_web/test_minute5_quality_service.py
git commit -m "fix: add zero_amount count to _invalid_stats for amount=0 visibility

- Add countIf(amount = 0) to _invalid_stats SQL
- Fix invalid_ohlc to only sum actual OHLC anomalies (not zero_amount)
- zero_amount appears in issues dict but does not affect status

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 后端 — `backfill_plan` 增加缺口分类

**Files:**
- Modify: `src/web/backend/minute5_quality.py`
- Test: `tests/test_web/test_minute5_quality_service.py`

**问题:** `missing_symbols` 是一个总数，无法区分"可回补"（有部分 bar，差尾部几根）和"不可回补"（0 bar，可能停牌/退市）。

**接口变更:**
- `backfill_plan` SQL 的 CTE 新增 `missing_symbol_detail` 子查询
- 返回新增 `missing_symbol_detail` 字段: `{partial, complete_missing}`
- 向后兼容：原有 `missing_symbols` 字段保留不变

- [ ] **Step 1: 修改 `backfill_plan` SQL**

在 `symbol_coverage as (...)` 之后、最终 `select` 之前，添加新的 CTE：

```python
            missing_symbol_detail as (
                select
                    e.trade_date,
                    countIf(ifNull(o.bars, 0) > 0 and ifNull(o.bars, 0) < %(expected_buckets)s) as partial,
                    countIf(ifNull(o.bars, 0) = 0) as complete_missing
                from expected_symbol_rows e
                left join (
                    select toDate(datetime) as trade_date, symbol, uniqExact(datetime) as bars
                    from minute5_kline
                    where toDate(datetime) >= %(start)s and toDate(datetime) <= %(end)s
                    group by trade_date, symbol
                ) o on o.trade_date = e.trade_date and o.symbol = e.symbol
                group by e.trade_date
            )
```

在最终 `select` 中添加 `ifNull(d.partial, 0) as partial_missing, ifNull(d.complete_missing, 0) as complete_missing`，并添加 `left join missing_symbol_detail d on d.trade_date = e.trade_date`。

- [ ] **Step 2: 修改返回 dict**

在 `backfill_plan` 方法的 items 构建中，添加：

```python
            items.append(
                {
                    "trade_date": _format_date(row[0]),
                    "expected_symbols": int(row[1] or 0),
                    "expected_buckets": int(row[2] or 0),
                    "actual_buckets": int(row[3] or 0),
                    "missing_buckets": missing_buckets,
                    "missing_symbols": missing_symbols,
                    "invalid_rows": invalid_rows,
                    "latest_bucket": _format_datetime(row[7]),
                    "partial_missing": int(row[8] or 0),
                    "complete_missing": int(row[9] or 0),
                    "status": status,
                }
            )
```

在 summary 中也加入：
```python
            "summary": {
                "days": len(items),
                "needs_backfill_days": len(needs),
                "missing_buckets": sum(int(item["missing_buckets"]) for item in items),
                "missing_symbols": sum(int(item["missing_symbols"]) for item in items),
                "invalid_rows": sum(int(item["invalid_rows"]) for item in items),
                "partial_missing": sum(int(item["partial_missing"]) for item in items),
                "complete_missing": sum(int(item["complete_missing"]) for item in items),
            },
```

- [ ] **Step 3: 更新 FakeMinute5Client**

修改 backfill_plan 相关的返回。在 `FakeMinute5Client` 中：

```python
        if "with candidate_dates as" in normalized and "latest_daily as" in normalized:
            return [
                (date(2026, 7, 8), 3, 48, 46, 2, 1, 1, datetime(2026, 7, 8, 14, 50), 1, 0),
                # partial=1 (000002 has 46 bars), complete_missing=0
                (date(2026, 7, 7), 3, 48, 48, 0, 0, 0, datetime(2026, 7, 7, 15, 0), 0, 0),
            ]
```

注意：现在 `missing_symbol_detail` 需要单独的查询匹配。在 FakeMinute5Client 中需要添加对 `missing_symbol_detail` CTE 的匹配。但由于这是同一个大查询，实际上 FakeMinute5Client 只需要返回正确的列数即可。

需要检查 FakeMinute5Client 的匹配逻辑 — `missing_symbol_detail` 是在同一个大 SQL 里的 CTE，不会单独执行。所以只需要调整返回值的列数。

- [ ] **Step 4: 更新测试 assertion**

修改 `test_minute5_quality_builds_backfill_plan_summary`：

```python
    assert payload["items"][0] == {
        "trade_date": "2026-07-08",
        "expected_symbols": 3,
        "expected_buckets": 48,
        "actual_buckets": 46,
        "missing_buckets": 2,
        "missing_symbols": 1,
        "invalid_rows": 1,
        "latest_bucket": "2026-07-08 14:50:00",
        "partial_missing": 1,
        "complete_missing": 0,
        "status": "needs_backfill",
    }
    assert payload["summary"] == {
        "days": 2,
        "needs_backfill_days": 1,
        "missing_buckets": 2,
        "missing_symbols": 1,
        "invalid_rows": 1,
        "partial_missing": 1,
        "complete_missing": 0,
    }
```

- [ ] **Step 5: 运行测试并确认**

```bash
uv run pytest tests/test_web/test_minute5_quality_service.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/web/backend/minute5_quality.py tests/test_web/test_minute5_quality_service.py
git commit -m "feat: backfill_plan adds missing_symbol_detail (partial vs complete_missing)

- Add missing_symbol_detail CTE to classify gaps as partial or complete_missing
- Add partial_missing and complete_missing to items and summary
- Backward compatible: existing missing_symbols field preserved

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 前端 — 类型更新 + 新增最新交易日覆盖卡片 + 数据污染显示 zero_amount

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Minute5Quality.vue`
- Test: `tests/test_web/test_minute5_quality_api.py`（更新 FakeMinute5QualityService）

**问题:** 前端类型不包含新增字段；页面不展示最新交易日覆盖和 amount 零值。

**接口变更:**
- `Minute5QualitySummary` 新增 `latest_day` 字段
- `Minute5QualitySummary.issues` 新增 `zero_amount` 键
- `Minute5QualityBackfillPlanItem` 新增 `partial_missing`, `complete_missing`
- `Minute5QualityBackfillPlan.summary` 新增 `partial_missing`, `complete_missing`

- [ ] **Step 1: 更新 TypeScript 类型**

在 `frontend/src/api/client.ts` 中：

`Minute5QualitySummary` 接口新增：
```typescript
  latest_day: {
    trade_date: string | null
    complete_symbols: number
    partial_symbols: number
    missing_symbols: number
    expected_symbols: number
  }
```

`Minute5QualityBackfillPlanItem` 接口新增：
```typescript
  partial_missing: number
  complete_missing: number
```

`Minute5QualityBackfillPlan` 的 `summary` 新增：
```typescript
  partial_missing: number
  complete_missing: number
```

- [ ] **Step 2: 更新页面 — 新增最新交易日覆盖卡片**

在 `Minute5Quality.vue` 的 `quality-grid` 中，在"最新完整桶"卡片之后添加新卡片：

```html
<div class="quality-card">
  <div class="quality-title"><span>最新交易日覆盖</span></div>
  <strong>{{ minute5QualitySummary?.latest_day?.trade_date ?? '-' }}</strong>
  <small>完整：{{ formatNumber(minute5QualitySummary?.latest_day?.complete_symbols ?? 0) }}</small>
  <small>部分：{{ formatNumber(minute5QualitySummary?.latest_day?.partial_symbols ?? 0) }}</small>
  <small>缺失：{{ formatNumber(minute5QualitySummary?.latest_day?.missing_symbols ?? 0) }}</small>
</div>
```

- [ ] **Step 3: 更新数据污染卡片 — 添加 zero_amount**

把数据污染卡片的 `<small>` 行：
```html
<small>异常 OHLC：{{ formatNumber(minute5QualitySummary?.issues.invalid_ohlc ?? 0) }}</small>
```
改为：
```html
<small>异常 OHLC：{{ formatNumber(minute5QualitySummary?.issues.invalid_ohlc ?? 0) }}</small>
<small>零成交额：{{ formatNumber(minute5QualitySummary?.issues.zero_amount ?? 0) }}</small>
```

- [ ] **Step 4: 更新 grid 布局**

原来 `quality-grid` 是 3 列 (`repeat(3, minmax(0, 1fr))`)。现在有 5 个卡片（整体状态、当前任务、最新完整桶、最新交易日覆盖、数据污染）。改为 3 列但允许 wrap：

```css
.quality-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
```
保持不变，第 4、5 个卡片会自动换行到第二行。

- [ ] **Step 5: 更新缺口标的表 — 显示分类**

在"缺口标的"的 `el-table` 中，添加两列：

```html
<el-table-column label="可回补" width="78" align="right">
  <template #default="{ row }">{{ formatNumber(row.bars > 0 ? 1 : 0) }}</template>
</el-table-column>
<el-table-column label="完全缺失" width="78" align="right">
  <template #default="{ row }">{{ formatNumber(row.bars === 0 ? 1 : 0) }}</template>
</el-table-column>
```

注意：这里用 `row.bars` 判断，因为 `missing_symbols` 列表里每条记录有 `bars` 字段（已有 bar 数）。`bars === 0` 表示完全缺失，`bars > 0` 表示部分缺口可回补。

或者更好的做法：在表头用 `minute5BackfillPlan?.summary.partial_missing` 和 `minute5BackfillPlan?.summary.complete_missing` 显示总数，不在每行显示。

在回补计划的 `plan-summary` 区域添加：
```html
<span>可回补 {{ formatNumber(minute5BackfillPlan?.summary.partial_missing ?? 0) }}</span>
<span>完全缺失 {{ formatNumber(minute5BackfillPlan?.summary.complete_missing ?? 0) }}</span>
```

- [ ] **Step 6: 更新 FakeMinute5QualityService**

在 `tests/test_web/test_minute5_quality_api.py` 的 `FakeMinute5QualityService.summary()` 返回中添加：

```python
"latest_day": {
    "trade_date": "2026-07-08",
    "complete_symbols": 2,
    "partial_symbols": 1,
    "missing_symbols": 0,
    "expected_symbols": 3,
},
"issues": {
    "duplicate_groups": 0,
    "extra_rows": 0,
    "invalid_ohlc": 1,
    "non_5m_boundary": 0,
    "non_market_session": 0,
    "zero_amount": 80,
},
```

在 `backfill_plan()` 返回的 item 中添加：
```python
"partial_missing": 1,
"complete_missing": 0,
```

在 `summary` 中添加：
```python
"partial_missing": 1,
"complete_missing": 0,
```

- [ ] **Step 7: 运行测试**

```bash
uv run pytest tests/test_web/test_minute5_quality_api.py tests/test_web/test_minute5_quality_service.py -v
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Minute5Quality.vue tests/test_web/test_minute5_quality_api.py
git commit -m "feat: frontend displays latest_day coverage and zero_amount in quality page

- Add latest_day field to Minute5QualitySummary type
- Add zero_amount to issues display
- Add partial_missing/complete_missing to backfill plan
- Add latest trading day coverage card to quality-grid
- Update fake service for API tests

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 前端 — 信息架构重构

**Files:**
- Modify: `frontend/src/pages/Minute5Quality.vue`

**问题:** 页面信息层级过平，首屏展示全表统计而非当前日期结论。

**本次范围:** 重构布局为"当前日期结论 → 修复计划 → 详情排查 → 全表健康"四层，将全表摘要卡片下沉。

**谨慎说明:** 本次不修改后端 API，不改变任何数据流。只调整 Vue 模板的 DOM 顺序和 CSS 布局。`quality-grid` 从首屏移到页面底部作为"全表累计健康"折叠区。

- [ ] **Step 1: 添加当前日期结论横幅**

在 `<section class="page">` 开头、`<div class="page-header">` 之后添加：

```html
<div class="date-conclusion-banner" :class="dateConclusionClass">
  <div class="date-conclusion-main">
    <h2 class="date-conclusion-title">{{ minute5QualityDate }} 5m 数据</h2>
    <el-tag :type="qualityTagType(dateConclusionStatus)" effect="plain" size="large">
      {{ dateConclusionLabel }}
    </el-tag>
  </div>
  <div class="date-conclusion-stats">
    <div class="stat-item">
      <span class="stat-label">完整</span>
      <span class="stat-value">{{ formatNumber(dateConclusionComplete) }}</span>
    </div>
    <div class="stat-item">
      <span class="stat-label">部分</span>
      <span class="stat-value">{{ formatNumber(dateConclusionPartial) }}</span>
    </div>
    <div class="stat-item">
      <span class="stat-label">缺失</span>
      <span class="stat-value">{{ formatNumber(dateConclusionMissing) }}</span>
    </div>
    <div class="stat-item">
      <span class="stat-label">异常</span>
      <span class="stat-value">{{ formatNumber(dateConclusionInvalid) }}</span>
    </div>
  </div>
</div>
```

- [ ] **Step 2: 添加 computed 属性**

在 `<script setup>` 中添加：

```typescript
const dateConclusionStatus = computed(() => {
  const plan = minute5BackfillPlan.value
  const items = plan?.items ?? []
  const todayItem = items.find((i) => i.trade_date === minute5QualityDate.value)
  if (!todayItem) return 'info'
  return todayItem.status
})

const dateConclusionLabel = computed(() => {
  const status = dateConclusionStatus.value
  if (status === 'ok') return '可用'
  if (status === 'needs_backfill') return '需要回补'
  return status
})

const dateConclusionClass = computed(() => {
  const status = dateConclusionStatus.value
  if (status === 'ok') return 'conclusion-ok'
  if (status === 'needs_backfill') return 'conclusion-needs-backfill'
  return 'conclusion-unknown'
})

const dateConclusionComplete = computed(() => minute5QualitySummary.value?.latest_day?.complete_symbols ?? 0)
const dateConclusionPartial = computed(() => minute5QualitySummary.value?.latest_day?.partial_symbols ?? 0)
const dateConclusionMissing = computed(() => minute5QualitySummary.value?.latest_day?.missing_symbols ?? 0)
const dateConclusionInvalid = computed(() => {
  const plan = minute5BackfillPlan.value
  const items = plan?.items ?? []
  const todayItem = items.find((i) => i.trade_date === minute5QualityDate.value)
  return todayItem?.invalid_rows ?? 0
})
```

- [ ] **Step 3: 添加 CSS**

```css
.date-conclusion-banner {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-left: 4px solid #909399;
  border-radius: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  margin-bottom: 16px;
}

.date-conclusion-banner.conclusion-ok {
  border-left-color: #67c23a;
}

.date-conclusion-banner.conclusion-needs-backfill {
  border-left-color: #e6a23c;
}

.date-conclusion-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.date-conclusion-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.date-conclusion-stats {
  display: flex;
  gap: 24px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-label {
  color: #909399;
  font-size: 12px;
}

.stat-value {
  color: #20242a;
  font-size: 20px;
  font-weight: 600;
}
```

- [ ] **Step 4: 将 quality-grid 移到底部并重命名**

把 `<div class="panel">` 包裹的 `quality-grid` 整个块从当前位置（紧接 page-header 之后）移动到 `sample-layout` 之后。

把 section 标题从"整体状态"改为"全表累计健康"。在 `quality-grid` 外面的 `.panel` 上添加一个折叠功能，或者简单地改标题：

```html
<div class="panel full-table-health">
  <div class="section-header no-top-margin">
    <div>
      <h2 class="section-title">全表累计健康</h2>
      <p class="section-subtitle">minute5_kline 全表统计，供参考。</p>
    </div>
  </div>
  <div class="quality-grid">
    <!-- 原有 4 个卡片 -->
  </div>
</div>
```

- [ ] **Step 5: 运行前端构建确认无 TS 错误**

```bash
cd frontend && npm run build 2>&1 | head -30
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Minute5Quality.vue
git commit -m "refactor: reorganize quality page info hierarchy

- Add date conclusion banner as first screen element
- Move full-table summary cards to bottom as '全表累计健康'
- Date conclusion shows complete/partial/missing/invalid counts
- No backend API changes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 前端 — 回补按钮上下文增强

**Files:**
- Modify: `frontend/src/pages/Minute5Quality.vue`

**问题:** "回补当前日期缺口"按钮没有行动前解释和行动后闭环。

**本次范围:** 点击回补按钮前显示确认对话框（说明将处理哪些标的），回补完成后显示结果摘要。

**谨慎说明:** 不修改后端 API。使用现有的 `repairMissingRows` 和 `repairInvalidRows` API，在现有 job polling 基础上增加 UI 提示。

- [ ] **Step 1: 修改 `repairMissingRows` 添加确认对话框**

把当前的 `repairMissingRows` 函数改为：

```typescript
async function repairMissingRows() {
  if (!minute5QualityDate.value || !hasMinute5MissingRows.value) return
  const count = minute5MissingSymbols.value.length
  const partialCount = minute5MissingSymbols.value.filter((s) => s.bars > 0).length
  const missingCount = minute5MissingSymbols.value.filter((s) => s.bars === 0).length

  // Use ElMessageBox for confirmation
  const { ElMessageBox } = await import('element-plus')
  try {
    await ElMessageBox.confirm(
      `将对 ${minute5QualityDate.value} 执行缺口回补：\n` +
      `- 共 ${count} 只标的缺口\n` +
      `- 部分缺口（可回补）：${partialCount} 只\n` +
      `- 完全缺失：${missingCount} 只`,
      '确认回补',
      { confirmButtonText: '开始回补', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return // user cancelled
  }

  repairingMissingRows.value = true
  try {
    const response = await api.repairMinute5MissingRows({
      trade_date: minute5QualityDate.value,
      symbols: null,
      limit: 10000
    })
    const completed = await pollMissingRepairJob(response.job_id)
    if (completed) {
      ElMessage.success(`${minute5QualityDate.value} 缺口回补完成`)
      await loadMinute5Quality()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '缺口分钟线回补失败')
  } finally {
    repairingMissingRows.value = false
  }
}
```

- [ ] **Step 2: 同样修改 `repairInvalidRows`**

```typescript
async function repairInvalidRows() {
  if (!minute5QualityDate.value || !minute5InvalidRows.value.length) return
  const count = minute5InvalidRows.value.length
  const symbols = Array.from(new Set(minute5InvalidRows.value.map((row) => row.symbol)))

  const { ElMessageBox } = await import('element-plus')
  try {
    await ElMessageBox.confirm(
      `将对 ${minute5QualityDate.value} 修复 ${count} 条异常记录（${symbols.length} 只标的）：\n` +
      `方式：删除异常行并重新拉取`,
      '确认修复',
      { confirmButtonText: '开始修复', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  repairingInvalidRows.value = true
  try {
    const response = await api.repairMinute5InvalidRows({
      trade_date: minute5QualityDate.value,
      symbols,
      mode: 'delete_and_refetch',
      limit: 1000
    })
    const completed = await pollInvalidRepairJob(response.job_id)
    if (completed) {
      ElMessage.success(`${minute5QualityDate.value} 异常修复完成`)
      await loadMinute5Quality()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '异常分钟线修复失败')
  } finally {
    repairingInvalidRows.value = false
  }
}
```

- [ ] **Step 3: 运行前端构建**

```bash
cd frontend && npm run build 2>&1 | head -30
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Minute5Quality.vue
git commit -m "feat: add confirmation dialogs to backfill and repair buttons

- Show target date, symbol count, partial vs complete breakdown before repair
- Use ElMessageBox.confirm for user confirmation
- No backend changes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 任务依赖关系

```
Task 1 (summary status + latest_day) ─┐
Task 2 (zero_amount)                   ├──→ Task 4 (frontend types + display) ──→ Task 5 (layout refactor)
Task 3 (backfill detail) ──────────────┘                                              │
                                                                                      └──→ Task 6 (backfill button)
```

Task 1/2/3 互相独立可并行。Task 4 依赖 1/2/3 完成。Task 5 依赖 Task 4。Task 6 依赖 Task 4。

---

## Self-Review

### Spec coverage
- [x] summary() status 修复（发现 #2）→ Task 1
- [x] 最新交易日覆盖信息 → Task 1 + Task 4
- [x] amount 零值统计 → Task 2 + Task 4
- [x] 缺口分类 → Task 3 + Task 4
- [x] 信息架构重构 → Task 5
- [x] 回补按钮上下文 → Task 6

### Placeholder scan
- 无 TBD/TODO
- 所有步骤有具体代码
- 类型名和方法名在各 Task 间一致

### Type consistency
- `latest_day` 字段在 Task 1 后端和 Task 4 前端类型中一致
- `zero_amount` 在 Task 2 后端和 Task 4 前端中一致
- `partial_missing`/`complete_missing` 在 Task 3 后端和 Task 4 前端中一致
- `_incomplete_symbols_on_latest_date` 方法名在各处一致
