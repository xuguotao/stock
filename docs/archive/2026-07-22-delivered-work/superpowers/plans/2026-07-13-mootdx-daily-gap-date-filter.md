# Mootdx 日线缺口按交易日查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在日线质量页面按交易日查看缺失标的和该日分类统计。

**Architecture:** 后端复用 `daily_quality` 已返回的逐日覆盖与缺口日期块，不新建查询接口。前端保存所选交易日，以该日期过滤缺口块、重算各分类数量，并将核验或回补请求限制到当前日期。

**Tech Stack:** FastAPI、ClickHouse、Vue 3、Element Plus、pytest、Vite。

---

### Task 1: 补充按交易日过滤行为测试

**Files:**
- Modify: `tests/test_web/test_mootdx_quality.py`
- Modify: `tests/test_frontend/test_mootdx_quality_pages.py`

- [ ] **Step 1: 写入失败的后端测试**

```python
def test_daily_quality_reports_gap_counts_for_each_trade_date() -> None:
    payload = MootdxQualityService(client=FakeDailyQualityClient()).daily_quality()
    assert payload["daily_coverage"][-1]["gap_counts"] == {"known_no_data": 1}
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest -q tests/test_web/test_mootdx_quality.py -k gap_counts_for_each_trade_date`

- [ ] **Step 3: 写入失败的前端静态测试**

```python
def test_daily_quality_page_filters_gap_queue_by_selected_trade_date() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text(encoding="utf-8")
    assert "selectedTradeDate" in source
    assert "missing_dates.includes(selectedTradeDate.value)" in source
```

- [ ] **Step 4: 运行测试并确认失败**

Run: `pytest -q tests/test_frontend/test_mootdx_quality_pages.py -k selected_trade_date`

### Task 2: 实现按交易日联动的工作队列

**Files:**
- Modify: `frontend/src/pages/DailyKlineQuality.vue`
- Modify: `frontend/src/api/client.ts`（仅在类型需要时）

- [ ] **Step 1: 添加交易日选择器与覆盖条**

```ts
const selectedTradeDate = ref('')
const selectedCoverage = computed(() => snapshot.value?.daily_coverage.find(item => item.trade_date === selectedTradeDate.value))
```

- [ ] **Step 2: 用选中日期过滤缺口块，并按日期截取提交 payload**

```ts
const dateGapDetails = computed(() => (snapshot.value?.missing_details ?? []).map(item => ({
  ...item,
  missing_dates: item.missing_dates.filter(value => value === selectedTradeDate.value),
})).filter(item => item.missing_dates.length > 0))
```

- [ ] **Step 3: 运行前端静态测试并确认通过**

Run: `pytest -q tests/test_frontend/test_mootdx_quality_pages.py`

### Task 3: 验证真实数据与构建

**Files:**
- Test: `tests/test_web/test_mootdx_quality.py`
- Test: `tests/test_frontend/test_mootdx_quality_pages.py`

- [ ] **Step 1: 运行质量服务和页面测试**

Run: `pytest -q tests/test_web/test_mootdx_quality.py tests/test_frontend/test_mootdx_quality_pages.py`

- [ ] **Step 2: 构建前端**

Run: `npm run build --prefix frontend`

- [ ] **Step 3: 使用最新交易日 API 抽验**

Run: `curl -fsS 'http://localhost:8000/api/data/mootdx/daily-quality?lookback_days=30&missing_limit=200'`

Expected: 选择 `2026-07-13` 后队列显示 61 条，且全部分类为 `known_no_data`。
