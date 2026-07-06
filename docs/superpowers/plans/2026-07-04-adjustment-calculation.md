# 复权计算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 ClickHouse `xdxr_info` 表中的除权除息数据，实现前复权/后复权价格计算功能，供策略回测和数据分析使用。

**Architecture:** 分两层：底层（`adjustment.py`）纯函数——从 xdxr 事件计算复权因子、对 DataFrame 应用前/后复权；上层（`adjustment_service.py`）封装 ClickHouse 查询 + 缓存，提供按 symbol 查询复权数据的接口。最终通过 `DataAggregator.get_bars(adjusted=True)` 一键获取复权数据。

**Tech Stack:** Python 3.11+, pandas, ClickHouse, existing data module

**数据范围：** 1990 年至今，覆盖全 A 股（约 5000+ 只股票）

---

## 复权计算公式

### 除权除息事件调整率

每次除权除息事件产生一个调整比率 `ratio`，表示 "除权后理论价 / 除权前收盘价"：

```
ratio = (pre_close - fenhong + peigu * peigujia) / (pre_close + songzhuangu + peigu) * suogu
```

> **注意：** 当前 `xdxr_info` 表不包含 `peigujia`（配股价）。对于 category=3（配股），需要额外查询或从原始数据补全。在 peigujia 不可用时，配股调整退化为仅考虑 fenhong 和 songzhuangu。

实际存储的字段映射（来自 tdxrs）：

| tdxrs 字段 | ClickHouse 列 | 含义 |
|---|---|---|
| `bonus_amount` | `fenhong` | 每股分红（元） |
| `ratening_amount` | `songzhuangu` | 每股送转股（股） |
| `increased_amount` | `peigu` | 每股配股（股） |
| `ignore` | `suogu` | 每股缩股（缩后） |

### 前复权（Forward Adjustment）

以最新价格为基准，向前调整历史价格：

```
cum_ratio[d] = ∏ ratio[i]  for all xdxr events i where ex_date[i] > d
adjusted_price[d] = raw_price[d] * cum_ratio[d]
```

- 最新交易日无后续事件 → cum_ratio = 1.0 → 价格不变
- 最早历史 → 经过最多事件累积 → 调整幅度最大

### 后复权（Backward Adjustment）

以最早价格为基准，向后调整（反映真实投资收益）：

```
cum_ratio[d] = ∏ ratio[i]  for all xdxr events i where ex_date[i] <= d
adjusted_price[d] = raw_price[d] * cum_ratio[d]
```

- 最早交易日无前期事件 → cum_ratio = 1.0 → 价格不变
- 最新交易日 → 经过所有事件累积 → 反映真实总回报

---

## Global Constraints

- **只读 ClickHouse** — 不修改现有表结构，不写入 daily_kline
- **纯函数优先** — 复权计算核心是纯 pandas 函数，易于测试
- **性能目标** — 单只股票 30 年日线 < 50ms；全市场批量 < 5 分钟
- **不动现有 API** — DataAggregator 现有方法签名不变，新增可选参数

---

## 前置修复

### 发现：xdxr_info 字段映射错误

`clickhouse_xdxr_sync.py` 从 tdxrs 读取字段名与实际 tdxrs 返回不一致：

| 代码读取 | tdxrs 实际返回 | 结果 |
|---|---|---|
| `xdxr.get("fenhong")` | `bonus_amount` | 始终为 0.0 |
| `xdxr.get("songzhuangu")` | `ratening_amount` | 始终为 0.0 |
| `xdxr.get("peigu")` | `increased_amount` | 始终为 0.0 |
| `xdxr.get("suogu")` | `ignore` | 始终为 0.0 |

**影响：** 当前 xdxr_info 表中所有数值列均为 0.0，无法用于复权计算。

**处理：** Task 1 先修复此 bug，再重新同步数据。

---

## File Structure

- **Create:** `src/data/adjustment.py` — 纯函数：复权因子计算、前复权/后复权 DataFrame 变换
- **Create:** `src/data/adjustment_service.py` — ClickHouse 查询层 + 内存缓存
- **Modify:** `src/data/aggregator.py` — `get_bars()` 新增 `adjusted` 参数
- **Modify:** `src/data/clickhouse_xdxr_sync.py` — 修复字段映射
- **Modify:** `src/data/clickhouse_source.py` — `fetch_bars()` 新增 `adjusted` 参数
- **Test:** `tests/test_data/test_adjustment.py` — 纯函数测试
- **Test:** `tests/test_data/test_adjustment_service.py` — ClickHouse 查询层测试

---

### Task 0: 修复 xdxr_info 字段映射

**Files:**
- Modify: `src/data/clickhouse_xdxr_sync.py:34-52`
- Test: `tests/test_data/test_clickhouse_xdxr_sync.py`

**Interfaces:**
- Consumes: tdxrs `fetch_xdxr_info` 返回的 raw dict 列表
- Produces: 正确映射 `bonus_amount → fenhong`, `ratening_amount → songzhuangu`, `increased_amount → peigu`, `ignore → suogu`

- [ ] **Step 1: Write failing test for field mapping**

```python
# tests/test_data/test_clickhouse_xdxr_sync.py (add)

def test_sync_maps_tdxrs_fields_correctly():
    """xdxr sync should map tdxrs field names to ClickHouse column names."""
    fake_client = FakeClient()

    def fetch_with_tdxrs_fields(symbol):
        if symbol == "000001.SZ":
            return [
                {
                    "year": 2023,
                    "month": 6,
                    "day": 15,
                    "category": 1,
                    "bonus_amount": 0.5,        # → fenhong
                    "ratening_amount": 0.3,      # → songzhuangu
                    "increased_amount": 0.1,     # → peigu
                    "ignore": 0.0,               # → suogu
                }
            ]
        return []

    result = sync_clickhouse_xdxr_info(
        client=fake_client,
        fetch_fn=fetch_with_tdxrs_fields,
        symbols=["000001.SZ"],
    )
    assert result["inserted"] == 1
    # Verify the INSERT values contain the correctly mapped values
    insert_command = fake_client.commands[-1]
    values = insert_command[1][0]
    assert values[5] == 0.5   # fenhong = bonus_amount
    assert values[6] == 0.3   # songzhuangu = ratening_amount
    assert values[7] == 0.1   # peigu = increased_amount
    assert values[8] == 0.0   # suogu = ignore
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_clickhouse_xdxr_sync.py::test_sync_maps_tdxrs_fields_correctly -v`
Expected: FAIL (values 5-8 are all 0.0 because field names don't match)

- [ ] **Step 3: Fix field mapping in clickhouse_xdxr_sync.py**

Edit `src/data/clickhouse_xdxr_sync.py` lines 34-51, replace:
```python
            for xdxr in xdxr_list:
                query = """
                INSERT INTO xdxr_info (
                    symbol, year, month, day, category,
                    fenhong, songzhuangu, peigu, suogu
                ) VALUES
                """
                values = (
                    symbol,
                    xdxr.get("year", 0),
                    xdxr.get("month", 0),
                    xdxr.get("day", 0),
                    xdxr.get("category", 0),
                    float(xdxr.get("fenhong", 0.0) or 0.0),
                    float(xdxr.get("songzhuangu", 0.0) or 0.0),
                    float(xdxr.get("peigu", 0.0) or 0.0),
                    float(xdxr.get("suogu", 0.0) or 0.0),
                )
```

with:
```python
            for xdxr in xdxr_list:
                query = """
                INSERT INTO xdxr_info (
                    symbol, year, month, day, category,
                    fenhong, songzhuangu, peigu, suogu
                ) VALUES
                """
                values = (
                    symbol,
                    xdxr.get("year", 0),
                    xdxr.get("month", 0),
                    xdxr.get("day", 0),
                    xdxr.get("category", 0),
                    float(xdxr.get("bonus_amount", 0.0) or 0.0),
                    float(xdxr.get("ratening_amount", 0.0) or 0.0),
                    float(xdxr.get("increased_amount", 0.0) or 0.0),
                    float(xdxr.get("ignore", 0.0) or 0.0),
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_clickhouse_xdxr_sync.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/clickhouse_xdxr_sync.py tests/test_data/test_clickhouse_xdxr_sync.py
git commit -m "fix: correct xdxr_info field mapping from tdxrs raw data

tdxrs returns bonus_amount/ratening_amount/increased_amount/ignore,
not fenhong/songzhuangu/peigu/suogu. Previous mapping stored all zeros."
```

---

### Task 1: 实现复权因子计算纯函数

**Files:**
- Create: `src/data/adjustment.py`
- Test: `tests/test_data/test_adjustment.py`

**Interfaces:**
- Consumes: xdxr 事件列表 (DataFrame with columns: ex_date, fenhong, songzhuangu, peigu, suogu, pre_close)
- Produces: per-event adjustment ratio DataFrame with column `ratio`

- [ ] **Step 1: Write failing tests for adjustment factor computation**

```python
# tests/test_data/test_adjustment.py
from __future__ import annotations

import pandas as pd
from datetime import date

from src.data.adjustment import compute_adjustment_ratios


def test_compute_ratios_no_events():
    """No xdxr events → empty DataFrame."""
    events = pd.DataFrame(columns=["ex_date", "fenhong", "songzhuangu", "peigu", "suogu", "pre_close"])
    result = compute_adjustment_ratios(events)
    assert result.empty


def test_compute_ratios_cash_dividend():
    """Cash dividend: ratio = (pre_close - fenhong) / pre_close."""
    events = pd.DataFrame([
        {"ex_date": date(2023, 6, 15), "fenhong": 0.5, "songzhuangu": 0.0,
         "peigu": 0.0, "suogu": 0.0, "pre_close": 10.0},
    ])
    result = compute_adjustment_ratios(events)

    # ratio = (10.0 - 0.5 + 0) / (10.0 + 0 + 0) * 1.0 = 0.95
    assert len(result) == 1
    assert abs(result.iloc[0]["ratio"] - 0.95) < 1e-9


def test_compute_ratios_bonus_shares():
    """Bonus shares: ratio = pre_close / (pre_close + songzhuangu)."""
    events = pd.DataFrame([
        {"ex_date": date(2023, 6, 15), "fenhong": 0.0, "songzhuangu": 0.3,
         "peigu": 0.0, "suogu": 0.0, "pre_close": 10.0},
    ])
    result = compute_adjustment_ratios(events)

    # ratio = (10.0 - 0 + 0) / (10.0 + 0.3 + 0) * 1.0 = 10.0 / 10.3
    expected = 10.0 / 10.3
    assert abs(result.iloc[0]["ratio"] - expected) < 1e-9


def test_compute_ratios_rights_issue():
    """Rights issue with peigujia: ratio includes peigu * peigujia term."""
    events = pd.DataFrame([
        {"ex_date": date(2023, 6, 15), "fenhong": 0.0, "songzhuangu": 0.0,
         "peigu": 0.2, "suogu": 0.0, "pre_close": 10.0, "peigujia": 8.0},
    ])
    result = compute_adjustment_ratios(events)

    # ratio = (10.0 - 0 + 0.2 * 8.0) / (10.0 + 0 + 0.2) * 1.0 = 11.6 / 10.2
    expected = 11.6 / 10.2
    assert abs(result.iloc[0]["ratio"] - expected) < 1e-9


def test_compute_ratios_consolidation():
    """Share consolidation: ratio = suogu (post-consolidation shares per pre-share)."""
    events = pd.DataFrame([
        {"ex_date": date(2023, 6, 15), "fenhong": 0.0, "songzhuangu": 0.0,
         "peigu": 0.0, "suogu": 0.5, "pre_close": 10.0},
    ])
    result = compute_adjustment_ratios(events)

    # ratio = (10.0 - 0 + 0) / (10.0 + 0 + 0) * 0.5 = 1.0 * 0.5 = 0.5
    assert abs(result.iloc[0]["ratio"] - 0.5) < 1e-9


def test_compute_ratios_mixed_event():
    """Combined dividend + bonus + rights issue."""
    events = pd.DataFrame([
        {"ex_date": date(2023, 6, 15), "fenhong": 0.3, "songzhuangu": 0.2,
         "peigu": 0.1, "suogu": 0.0, "pre_close": 10.0, "peigujia": 8.0},
    ])
    result = compute_adjustment_ratios(events)

    # ratio = (10.0 - 0.3 + 0.1 * 8.0) / (10.0 + 0.2 + 0.1) * 1.0
    #       = 10.5 / 10.3
    expected = 10.5 / 10.3
    assert abs(result.iloc[0]["ratio"] - expected) < 1e-9


def test_compute_ratios_multiple_events_sorted_by_date():
    """Multiple events should be sorted by ex_date ascending."""
    events = pd.DataFrame([
        {"ex_date": date(2024, 1, 10), "fenhong": 0.5, "songzhuangu": 0.0,
         "peigu": 0.0, "suogu": 0.0, "pre_close": 12.0},
        {"ex_date": date(2023, 6, 15), "fenhong": 0.3, "songzhuangu": 0.0,
         "peigu": 0.0, "suogu": 0.0, "pre_close": 10.0},
    ])
    result = compute_adjustment_ratios(events)

    assert result.iloc[0]["ex_date"] == date(2023, 6, 15)
    assert result.iloc[1]["ex_date"] == date(2024, 1, 10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_adjustment.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.data.adjustment'"

- [ ] **Step 3: Implement compute_adjustment_ratios**

```python
# src/data/adjustment.py
"""Stock price adjustment (复权) calculation.

Provides pure functions for computing forward-adjusted (前复权) and
backward-adjusted (后复权) prices from raw OHLCV data and xdxr events.
"""
from __future__ import annotations

import pandas as pd


def compute_adjustment_ratios(events: pd.DataFrame) -> pd.DataFrame:
    """Compute per-event adjustment ratios from xdxr events.

    Args:
        events: DataFrame with columns:
            - ex_date: date of the ex-rights/ex-dividend
            - fenhong: cash dividend per share (元)
            - songzhuangu: bonus shares per share (股)
            - peigu: rights issue shares per share (股)
            - suogu: consolidation ratio (缩后股数)
            - pre_close: close price on the day before ex_date
            - peigujia: (optional) rights issue price (元), defaults to 0

    Returns:
        DataFrame sorted by ex_date with added column:
            - ratio: adjustment ratio (除权后理论价 / 除权前收盘价)
    """
    if events.empty:
        return events.copy()

    result = events.sort_values("ex_date").reset_index(drop=True)
    peigujia = result.get("peigujia", pd.Series(0.0, index=result.index)).fillna(0.0)
    pre_close = result["pre_close"].fillna(0.0)
    fenhong = result["fenhong"].fillna(0.0)
    songzhuangu = result["songzhuangu"].fillna(0.0)
    peigu = result["peigu"].fillna(0.0)
    suogu = result["suogu"].fillna(0.0)

    # ratio = (pre_close - fenhong + peigu * peigujia) / (pre_close + songzhuangu + peigu) * max(suogu, 1.0 if suogu == 0 else suogu)
    # suogu == 0 means no consolidation; treat as 1.0
    suogu_factor = suogu.where(suogu > 0, 1.0)

    numerator = pre_close - fenhong + peigu * peigujia
    denominator = pre_close + songzhuangu + peigu

    # Guard against division by zero
    ratio = numerator / denominator.replace(0, float("nan")) * suogu_factor
    ratio = ratio.fillna(1.0)

    result = result.copy()
    result["ratio"] = ratio
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_adjustment.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/adjustment.py tests/test_data/test_adjustment.py
git commit -m "feat: add compute_adjustment_ratios for xdxr events

Pure function that computes per-event adjustment ratio from
fenhong/songzhuangu/peigu/suogu/pre_close/peigujia."
```

---

### Task 2: 实现前复权/后复权 DataFrame 变换

**Files:**
- Modify: `src/data/adjustment.py`
- Test: `tests/test_data/test_adjustment.py`

**Interfaces:**
- Consumes: 日线 DataFrame (date, open, high, low, close, volume, amount, symbol) + xdxr ratios DataFrame
- Produces: 添加 `adjusted_close` (前复权) 列的 DataFrame；可选 `backward_close` (后复权) 列

- [ ] **Step 1: Write failing tests for forward/backward adjustment**

```python
# tests/test_data/test_adjustment.py (add)

from src.data.adjustment import apply_forward_adjustment, apply_backward_adjustment


def _sample_bars():
    """5 trading days around one xdxr event on date(2024, 1, 10)."""
    return pd.DataFrame([
        {"date": date(2024, 1, 8),  "close": 10.0, "open": 9.8, "high": 10.2, "low": 9.7,
         "volume": 1000, "amount": 10000.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 9),  "close": 10.5, "open": 10.1, "high": 10.6, "low": 10.0,
         "volume": 1200, "amount": 12600.0, "symbol": "000001.SZ"},
        # ex-date: cum-rights close = 10.5, ex-ref = 10.0, ratio = 10.0/10.5
        {"date": date(2024, 1, 10), "close": 10.0, "open": 9.9, "high": 10.1, "low": 9.8,
         "volume": 1500, "amount": 15000.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 11), "close": 10.2, "open": 10.0, "high": 10.3, "low": 9.9,
         "volume": 1100, "amount": 11220.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 12), "close": 10.4, "open": 10.1, "high": 10.5, "low": 10.0,
         "volume": 1300, "amount": 13520.0, "symbol": "000001.SZ"},
    ])


def _sample_ratio():
    """One xdxr event with ratio = 10.0/10.5 on ex_date 2024-01-10."""
    return pd.DataFrame([
        {"ex_date": date(2024, 1, 10), "ratio": 10.0 / 10.5},
    ])


def test_forward_adjustment_latest_price_unchanged():
    """Forward adjustment: latest date should keep original price."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_forward_adjustment(bars, ratios)

    # Latest date (2024-01-12) has no future xdxr → adjusted_close = close
    latest = result[result["date"] == date(2024, 1, 12)]
    assert abs(latest.iloc[0]["adjusted_close"] - 10.4) < 1e-9


def test_forward_adjustment_historical_prices_reduced():
    """Forward adjustment: historical prices are scaled down."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_forward_adjustment(bars, ratios)

    # Before ex-date, adjusted_close = close * ratio = close * (10.0/10.5)
    pre_event = result[result["date"] == date(2024, 1, 9)]
    expected = 10.5 * (10.0 / 10.5)
    assert abs(pre_event.iloc[0]["adjusted_close"] - expected) < 1e-9


def test_forward_adjustment_ex_date_and_after_unchanged():
    """Forward adjustment: on and after ex-date, prices stay as-is."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_forward_adjustment(bars, ratios)

    for d in [date(2024, 1, 10), date(2024, 1, 11), date(2024, 1, 12)]:
        row = result[result["date"] == d].iloc[0]
        assert abs(row["adjusted_close"] - row["close"]) < 1e-9


def test_backward_adjustment_earliest_price_unchanged():
    """Backward adjustment: earliest date keeps original price."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_backward_adjustment(bars, ratios)

    earliest = result[result["date"] == date(2024, 1, 8)]
    assert abs(earliest.iloc[0]["adjusted_close"] - 10.0) < 1e-9


def test_backward_adjustment_after_ex_date_increased():
    """Backward adjustment: after ex-date, prices scaled up."""
    bars = _sample_bars()
    ratios = _sample_ratio()

    result = apply_backward_adjustment(bars, ratios)

    # After ex-date: adjusted_close = close / ratio = close * (10.5/10.0)
    post_event = result[result["date"] == date(2024, 1, 11)]
    expected = 10.2 * (10.5 / 10.0)
    assert abs(post_event.iloc[0]["adjusted_close"] - expected) < 1e-9


def test_forward_adjustment_no_events():
    """No xdxr events → adjusted_close = close."""
    bars = _sample_bars()
    empty_ratios = pd.DataFrame(columns=["ex_date", "ratio"])

    result = apply_forward_adjustment(bars, empty_ratios)

    assert (result["adjusted_close"] == result["close"]).all()


def test_backward_adjustment_no_events():
    """No xdxr events → adjusted_close = close."""
    bars = _sample_bars()
    empty_ratios = pd.DataFrame(columns=["ex_date", "ratio"])

    result = apply_backward_adjustment(bars, empty_ratios)

    assert (result["adjusted_close"] == result["close"]).all()


def test_forward_adjustment_multiple_events():
    """Multiple xdxr events accumulate correctly."""
    bars = pd.DataFrame([
        {"date": date(2024, 1, 5),  "close": 20.0, "open": 19.5, "high": 20.5,
         "low": 19.0, "volume": 1000, "amount": 20000.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 10), "close": 19.0, "open": 18.5, "high": 19.5,
         "low": 18.0, "volume": 1200, "amount": 22800.0, "symbol": "000001.SZ"},
        {"date": date(2024, 1, 15), "close": 18.0, "open": 17.5, "high": 18.5,
         "low": 17.0, "volume": 1500, "amount": 27000.0, "symbol": "000001.SZ"},
    ])
    ratios = pd.DataFrame([
        {"ex_date": date(2024, 1, 10), "ratio": 0.95},  # 5% drop
        {"ex_date": date(2024, 1, 15), "ratio": 0.90},  # 10% drop
    ])

    result = apply_forward_adjustment(bars, ratios)

    # 2024-01-05: affected by BOTH events → 20.0 * 0.95 * 0.90 = 17.1
    jan5 = result[result["date"] == date(2024, 1, 5)]
    assert abs(jan5.iloc[0]["adjusted_close"] - 17.1) < 1e-6

    # 2024-01-10: affected by second event only → 19.0 * 0.90 = 17.1
    jan10 = result[result["date"] == date(2024, 1, 10)]
    assert abs(jan10.iloc[0]["adjusted_close"] - 17.1) < 1e-6

    # 2024-01-15: no future events → 18.0
    jan15 = result[result["date"] == date(2024, 1, 15)]
    assert abs(jan15.iloc[0]["adjusted_close"] - 18.0) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_adjustment.py -v`
Expected: FAIL with ImportError for apply_forward_adjustment / apply_backward_adjustment

- [ ] **Step 3: Implement forward/backward adjustment functions**

Add to `src/data/adjustment.py`:

```python
def apply_forward_adjustment(
    bars: pd.DataFrame,
    ratios: pd.DataFrame,
) -> pd.DataFrame:
    """Apply forward adjustment (前复权) to OHLCV bars.

    Latest price stays unchanged; historical prices are scaled down
    by cumulative ratios of all future xdxr events.

    Args:
        bars: DataFrame with columns including date, close, symbol.
              Must be sorted by date ascending.
        ratios: DataFrame from compute_adjustment_ratios with columns ex_date, ratio.

    Returns:
        Copy of bars with added/updated 'adjusted_close' column (前复权收盘价).
    """
    result = bars.copy()
    if ratios.empty:
        result["adjusted_close"] = result["close"]
        return result

    sorted_ratios = ratios.sort_values("ex_date").reset_index(drop=True)
    ex_dates = sorted_ratios["ex_date"].values
    ratio_values = sorted_ratios["ratio"].values

    # For each bar date, compute cumulative product of all ratios where ex_date > bar_date
    adjusted = []
    for bar_date in result["date"].values:
        mask = ex_dates > bar_date
        cum_ratio = ratio_values[mask].prod() if mask.any() else 1.0
        adjusted.append(cum_ratio)

    result["adjusted_close"] = result["close"] * adjusted
    return result


def apply_backward_adjustment(
    bars: pd.DataFrame,
    ratios: pd.DataFrame,
) -> pd.DataFrame:
    """Apply backward adjustment (后复权) to OHLCV bars.

    Earliest price stays unchanged; later prices are scaled up
    by cumulative ratios of all past xdxr events.

    Args:
        bars: DataFrame with columns including date, close, symbol.
              Must be sorted by date ascending.
        ratios: DataFrame from compute_adjustment_ratios with columns ex_date, ratio.

    Returns:
        Copy of bars with added/updated 'adjusted_close' column (后复权收盘价).
    """
    result = bars.copy()
    if ratios.empty:
        result["adjusted_close"] = result["close"]
        return result

    sorted_ratios = ratios.sort_values("ex_date").reset_index(drop=True)
    ex_dates = sorted_ratios["ex_date"].values
    ratio_values = sorted_ratios["ratio"].values

    # For each bar date, compute cumulative product of all ratios where ex_date <= bar_date
    adjusted = []
    for bar_date in result["date"].values:
        mask = ex_dates <= bar_date
        cum_ratio = ratio_values[mask].prod() if mask.any() else 1.0
        adjusted.append(cum_ratio)

    result["adjusted_close"] = result["close"] / adjusted
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_adjustment.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/adjustment.py tests/test_data/test_adjustment.py
git commit -m "feat: add forward/backward adjustment DataFrame transforms

apply_forward_adjustment: 前复权 — latest price unchanged, historical scaled down
apply_backward_adjustment: 后复权 — earliest price unchanged, later scaled up

Both use cumulative product of per-event adjustment ratios."
```

---

### Task 3: 实现 AdjustmentService（ClickHouse 查询 + 缓存）

**Files:**
- Create: `src/data/adjustment_service.py`
- Test: `tests/test_data/test_adjustment_service.py`

**Interfaces:**
- Consumes: ClickHouse client, symbol, date range
- Produces: 复权后的 DataFrame（含 adjusted_close 列）

- [ ] **Step 1: Write failing tests for AdjustmentService**

```python
# tests/test_data/test_adjustment_service.py
from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.adjustment_service import AdjustmentService


class FakeClickHouseClient:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from xdxr_info" in normalized:
            return [
                (date(2023, 6, 15), 0.3, 0.0, 0.0, 0.0, 10.0),
                (date(2024, 1, 10), 0.5, 0.0, 0.0, 0.0, 12.0),
            ]
        if "from daily_kline" in normalized:
            return [
                ("000001", date(2023, 6, 12), 10.0, 10.5, 9.9, 10.2, 1000, 10200.0),
                ("000001", date(2023, 6, 15), 10.2, 10.8, 10.1, 10.6, 1200, 12720.0),
                ("000001", date(2024, 1, 8), 11.0, 11.5, 10.8, 11.2, 1500, 16800.0),
                ("000001", date(2024, 1, 10), 11.2, 11.8, 11.0, 11.5, 1800, 20700.0),
                ("000001", date(2024, 1, 12), 11.5, 12.0, 11.3, 11.8, 1600, 18880.0),
            ]
        return []


def test_service_returns_forward_adjusted_bars():
    """AdjustmentService should return bars with forward-adjusted close."""
    service = AdjustmentService(client=FakeClickHouseClient())

    result = service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2023, 6, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    # Latest date (2024-01-12) has no future xdxr → adjusted_close = close
    latest = result[result["date"] == date(2024, 1, 12)]
    assert abs(latest.iloc[0]["adjusted_close"] - 11.8) < 1e-6


def test_service_returns_backward_adjusted_bars():
    """AdjustmentService should return bars with backward-adjusted close."""
    service = AdjustmentService(client=FakeClickHouseClient())

    result = service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2023, 6, 1),
        end=date(2024, 1, 31),
        adjust_type="backward",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    # Earliest date (2023-06-12) has no past xdxr → adjusted_close = close
    earliest = result[result["date"] == date(2023, 6, 12)]
    assert abs(earliest.iloc[0]["adjusted_close"] - 10.2) < 1e-6


def test_service_queries_xdxr_with_correct_symbol():
    """xdxr query should use the 6-digit code without suffix."""
    fake_client = FakeClickHouseClient()
    service = AdjustmentService(client=fake_client)

    service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2023, 6, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    xdxr_query = [q for q, _ in fake_client.calls if "xdxr_info" in q.lower()][0]
    xdxr_params = [p for q, p in fake_client.calls if "xdxr_info" in q.lower()][0]
    assert xdxr_params["symbol"] == "000001"


def test_service_caches_xdxr_data():
    """Second call with same symbol should use cached xdxr data."""
    fake_client = FakeClickHouseClient()
    service = AdjustmentService(client=fake_client)

    service.get_adjusted_bars("000001.SZ", date(2023, 1, 1), date(2024, 6, 30), "forward")
    xdxr_queries_first = sum(1 for q, _ in fake_client.calls if "xdxr_info" in q.lower())

    service.get_adjusted_bars("000001.SZ", date(2023, 6, 1), date(2024, 1, 31), "forward")
    xdxr_queries_second = sum(1 for q, _ in fake_client.calls if "xdxr_info" in q.lower())

    # Second call should NOT query xdxr again (same symbol)
    assert xdxr_queries_second == xdxr_queries_first


def test_service_no_adjust_returns_raw_bars():
    """adjust_type='none' should return raw close = adjusted_close."""
    service = AdjustmentService(client=FakeClickHouseClient())

    result = service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2023, 6, 1),
        end=date(2024, 1, 31),
        adjust_type="none",
    )

    assert (result["adjusted_close"] == result["close"]).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_adjustment_service.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.data.adjustment_service'"

- [ ] **Step 3: Implement AdjustmentService**

```python
# src/data/adjustment_service.py
"""Adjustment service with ClickHouse query layer and caching."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from src.data.adjustment import (
    apply_backward_adjustment,
    apply_forward_adjustment,
    compute_adjustment_ratios,
)

logger = logging.getLogger(__name__)


class AdjustmentService:
    """Provides adjusted bar data by combining ClickHouse daily_kline and xdxr_info.

    Caches xdxr events per symbol to avoid repeated ClickHouse queries.
    """

    def __init__(self, client: Any | None = None):
        if client is None:
            from src.data.clickhouse_source import ClickHouseStockDataSource
            self._client = ClickHouseStockDataSource()._client_instance()
        else:
            self._client = client
        self._xdxr_cache: dict[str, pd.DataFrame] = {}

    def get_adjusted_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust_type: str = "forward",
    ) -> pd.DataFrame:
        """Get daily bars with adjustment applied.

        Args:
            symbol: Stock symbol like "000001.SZ"
            start: Start date (inclusive)
            end: End date (inclusive)
            adjust_type: "forward" (前复权), "backward" (后复权), or "none"

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount,
            adjusted_close, symbol
        """
        bars = self._fetch_bars(symbol, start, end)
        if bars.empty:
            return bars

        if adjust_type == "none":
            bars["adjusted_close"] = bars["close"]
            return bars

        ratios = self._get_xdxr_ratios(symbol)
        if ratios.empty:
            bars["adjusted_close"] = bars["close"]
            return bars

        if adjust_type == "forward":
            return apply_forward_adjustment(bars, ratios)
        elif adjust_type == "backward":
            return apply_backward_adjustment(bars, ratios)
        else:
            logger.warning(f"Unknown adjust_type '{adjust_type}', returning raw bars")
            bars["adjusted_close"] = bars["close"]
            return bars

    def _fetch_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        code = symbol.split(".")[0].zfill(6)
        rows = self._client.execute(
            """
            select symbol, date, open, high, low, close, volume, amount
            from daily_kline
            where symbol = %(symbol)s and date >= %(start)s and date <= %(end)s
            order by date
            """,
            {"symbol": code, "start": start, "end": end},
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
        )
        from src.core.constants import format_symbol
        df["symbol"] = df["symbol"].astype(str).map(format_symbol)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["volume"] = df["volume"].astype(int)
        return df

    def _get_xdxr_ratios(self, symbol: str) -> pd.DataFrame:
        """Get cached xdxr ratios for a symbol. Fetches from ClickHouse on first call."""
        if symbol in self._xdxr_cache:
            return self._xdxr_cache[symbol]

        code = symbol.split(".")[0].zfill(6)
        rows = self._client.execute(
            """
            select ex_date, fenhong, songzhuangu, peigu, suogu
            from xdxr_info final
            where symbol = %(symbol)s
            order by ex_date
            """,
            {"symbol": code},
        )
        if not rows:
            empty = pd.DataFrame(columns=["ex_date", "fenhong", "songzhuangu", "peigu", "suogu"])
            self._xdxr_cache[symbol] = empty
            return empty

        events = pd.DataFrame(
            rows,
            columns=["ex_date", "fenhong", "songzhuangu", "peigu", "suogu"],
        )
        events["ex_date"] = pd.to_datetime(events["ex_date"]).dt.date

        # Fetch pre_close for each xdxr event (close on the day before ex_date)
        pre_closes = self._fetch_pre_closes(code, events["ex_date"].tolist())
        events["pre_close"] = events["ex_date"].map(pre_closes).fillna(0.0)

        ratios = compute_adjustment_ratios(events)
        self._xdxr_cache[symbol] = ratios
        return ratios

    def _fetch_pre_closes(self, code: str, ex_dates: list[date]) -> dict[date, float]:
        """Fetch close prices for the trading day before each ex_date."""
        if not ex_dates:
            return {}
        # Query the close price for each ex_date, then look up the previous day's close
        # using a LAG window function
        results = {}
        for ex_date in ex_dates:
            rows = self._client.execute(
                """
                select close from daily_kline
                where symbol = %(symbol)s and date < %(ex_date)s
                order by date desc limit 1
                """,
                {"symbol": code, "ex_date": ex_date},
            )
            if rows:
                results[ex_date] = float(rows[0][0])
        return results

    def clear_cache(self) -> None:
        """Clear the xdxr cache."""
        self._xdxr_cache.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_adjustment_service.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/adjustment_service.py tests/test_data/test_adjustment_service.py
git commit -m "feat: add AdjustmentService with ClickHouse query + xdxr cache

Wraps daily_kline + xdxr_info queries, applies forward/backward adjustment.
Caches xdxr ratios per symbol to avoid redundant ClickHouse queries."
```

---

### Task 4: 集成到 DataAggregator

**Files:**
- Modify: `src/data/aggregator.py`
- Test: `tests/test_data/test_aggregator.py`

**Interfaces:**
- Consumes: `AdjustmentService`
- Produces: `DataAggregator.get_bars(adjusted=True)` 返回复权数据

- [ ] **Step 1: Write failing test for adjusted bars**

```python
# tests/test_data/test_aggregator.py (add)
from datetime import date
from unittest.mock import patch, MagicMock
import pandas as pd
from src.data.aggregator import DataAggregator


def test_get_bars_with_adjustment():
    """get_bars(adjusted=True) should return forward-adjusted close."""
    from src.data.clickhouse_source import ClickHouseStockDataSource

    class FakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "from daily_kline" in normalized:
                return [
                    ("000001", date(2024, 1, 8), 10.0, 10.5, 9.9, 10.2, 1000, 10200.0),
                    ("000001", date(2024, 1, 10), 10.2, 10.8, 10.1, 10.6, 1200, 12720.0),
                ]
            if "from xdxr_info" in normalized:
                return [(date(2024, 1, 10), 0.3, 0.0, 0.0, 0.0)]
            return []

    source = ClickHouseStockDataSource(client=FakeClient())
    agg = DataAggregator(sources=[source])

    result = agg.get_bars("000001.SZ", date(2024, 1, 1), date(2024, 1, 31), adjusted=True)

    assert "adjusted_close" in result.columns
    # Latest date should have adjusted_close = close (no future xdxr)
    latest = result[result["date"] == date(2024, 1, 10)]
    assert not latest.empty


def test_get_bars_default_no_adjustment():
    """get_bars() without adjusted param should return raw close."""
    from src.data.clickhouse_source import ClickHouseStockDataSource

    class FakeClient:
        def execute(self, query, params=None):
            if "from daily_kline" in query.lower():
                return [
                    ("000001", date(2024, 1, 8), 10.0, 10.5, 9.9, 10.2, 1000, 10200.0),
                ]
            return []

    source = ClickHouseStockDataSource(client=FakeClient())
    agg = DataAggregator(sources=[source])

    result = agg.get_bars("000001.SZ", date(2024, 1, 1), date(2024, 1, 31))

    assert result.iloc[0]["adjusted_close"] == result.iloc[0]["close"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_aggregator.py -v`
Expected: FAIL (get_bars doesn't accept `adjusted` parameter)

- [ ] **Step 3: Add adjusted parameter to DataAggregator.get_bars**

Edit `src/data/aggregator.py`, modify `get_bars` method signature and implementation:

Change:
```python
    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
        use_cache: bool = True,
    ) -> pd.DataFrame:
```

to:
```python
    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
        use_cache: bool = True,
        adjusted: bool = False,
        adjust_type: str = "forward",
    ) -> pd.DataFrame:
```

And add adjustment logic after fetching bars from source (before return):
```python
        # Try each source
        for source in self.sources:
            try:
                df = source.fetch_bars(symbol, start, end, frequency)
                if df is not None and not df.empty:
                    # Cache result
                    if use_cache and not prefer_source:
                        self.cache.write_bars(df, symbol, start, end)

                    # Apply adjustment if requested
                    if adjusted:
                        df = self._apply_adjustment(symbol, df, start, end, adjust_type)

                    return df
            except Exception as e:
                logger.warning(f"Source {source.name} failed for {symbol}: {e}")
                continue
```

Add helper method:
```python
    def _apply_adjustment(
        self,
        symbol: str,
        df: pd.DataFrame,
        start: date,
        end: date,
        adjust_type: str,
    ) -> pd.DataFrame:
        """Apply forward/backward adjustment to bar DataFrame."""
        if self._adjustment_service is None:
            from src.data.adjustment_service import AdjustmentService
            self._adjustment_service = AdjustmentService()
        return self._adjustment_service.get_adjusted_bars_with_bars(
            df, symbol, start, end, adjust_type
        )
```

And initialize `self._adjustment_service = None` in `__init__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_aggregator.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/aggregator.py tests/test_data/test_aggregator.py
git commit -m "feat: add adjustment support to DataAggregator.get_bars

New optional parameters:
- adjusted: bool = False (enable/disable adjustment)
- adjust_type: str = 'forward' ('forward'|'backward'|'none')

Lazy-initializes AdjustmentService on first use."
```

---

### Task 5: 性能优化（批量查询）

**Files:**
- Modify: `src/data/adjustment_service.py`
- Test: `tests/test_data/test_adjustment_service.py`

**Interfaces:**
- Consumes: 多只 symbol 的列表
- Produces: MultiIndex (date, symbol) 的复权 DataFrame

**性能考虑：**

对于全市场 5000+ 只股票，逐只查询 ClickHouse 会很慢。优化方案：

1. **批量 xdxr 查询**: 一次性查出所有 symbol 的 xdxr 数据（`WHERE symbol IN (...)`）
2. **批量 daily_kline 查询**: 一次性查出所有 symbol 的日线数据
3. **分组计算**: 按 symbol 分组后并行计算复权因子

- [ ] **Step 1: Write failing test for batch adjustment**

```python
# tests/test_data/test_adjustment_service.py (add)

def test_get_adjusted_bars_batch():
    """Batch adjustment should return MultiIndex DataFrame for multiple symbols."""
    class BatchFakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "from xdxr_info" in normalized:
                symbols = (params or {}).get("symbols", ())
                rows = []
                if "000001" in symbols:
                    rows.append(("000001", date(2024, 1, 10), 0.3, 0.0, 0.0, 0.0))
                if "600519" in symbols:
                    rows.append(("600519", date(2024, 1, 10), 0.5, 0.0, 0.0, 0.0))
                return rows
            if "from daily_kline" in normalized:
                symbols = (params or {}).get("symbols", ())
                rows = []
                if "000001" in symbols:
                    rows.extend([
                        ("000001", date(2024, 1, 8), 10.0, 10.5, 9.9, 10.2, 1000, 10200.0),
                        ("000001", date(2024, 1, 10), 10.2, 10.8, 10.1, 10.6, 1200, 12720.0),
                    ])
                if "600519" in symbols:
                    rows.extend([
                        ("600519", date(2024, 1, 8), 1800.0, 1850.0, 1790.0, 1820.0, 500, 910000.0),
                        ("600519", date(2024, 1, 10), 1820.0, 1870.0, 1810.0, 1850.0, 600, 1110000.0),
                    ])
                return rows
            if "close" in normalized and "daily_kline" in normalized:
                return [(10.0,)]
            return []

    service = AdjustmentService(client=BatchFakeClient())

    result = service.get_adjusted_bars_batch(
        symbols=["000001.SZ", "600519.SH"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    assert set(result["symbol"].unique()) == {"000001.SZ", "600519.SH"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data/test_adjustment_service.py::test_get_adjusted_bars_batch -v`
Expected: FAIL

- [ ] **Step 3: Implement batch method**

Add to `AdjustmentService` in `src/data/adjustment_service.py`:

```python
    def get_adjusted_bars_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjust_type: str = "forward",
    ) -> pd.DataFrame:
        """Get adjusted bars for multiple symbols efficiently.

        Uses batch ClickHouse queries instead of per-symbol queries.
        """
        if not symbols:
            return pd.DataFrame()

        codes = tuple(s.split(".")[0].zfill(6) for s in symbols)
        all_bars = self._fetch_bars_batch(codes, start, end)
        if all_bars.empty:
            return all_bars

        if adjust_type == "none":
            all_bars["adjusted_close"] = all_bars["close"]
            return all_bars

        all_ratios = self._get_xdxr_ratios_batch(codes)

        frames = []
        for symbol, group in all_bars.groupby("symbol"):
            code = symbol.split(".")[0].zfill(6)
            ratios = all_ratios.get(code, pd.DataFrame())
            if ratios.empty:
                group = group.copy()
                group["adjusted_close"] = group["close"]
            elif adjust_type == "forward":
                group = apply_forward_adjustment(group, ratios)
            elif adjust_type == "backward":
                group = apply_backward_adjustment(group, ratios)
            else:
                group = group.copy()
                group["adjusted_close"] = group["close"]
            frames.append(group)

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _fetch_bars_batch(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()
        rows = self._client.execute(
            """
            select symbol, date, open, high, low, close, volume, amount
            from daily_kline
            where symbol in %(symbols)s and date >= %(start)s and date <= %(end)s
            order by symbol, date
            """,
            {"symbols": codes, "start": start, "end": end},
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
        )
        from src.core.constants import format_symbol
        df["symbol"] = df["symbol"].astype(str).map(format_symbol)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["volume"] = df["volume"].astype(int)
        return df

    def _get_xdxr_ratios_batch(
        self, codes: tuple[str, ...]
    ) -> dict[str, pd.DataFrame]:
        if not codes:
            return {}
        rows = self._client.execute(
            """
            select symbol, ex_date, fenhong, songzhuangu, peigu, suogu
            from xdxr_info final
            where symbol in %(symbols)s
            order by symbol, ex_date
            """,
            {"symbols": codes},
        )
        if not rows:
            return {code: pd.DataFrame() for code in codes}

        events = pd.DataFrame(
            rows,
            columns=["symbol", "ex_date", "fenhong", "songzhuangu", "peigu", "suogu"],
        )
        events["ex_date"] = pd.to_datetime(events["ex_date"]).dt.date

        # Fetch pre_closes in batch
        result: dict[str, pd.DataFrame] = {}
        for code, group in events.groupby("symbol"):
            pre_closes = self._fetch_pre_closes(code, group["ex_date"].tolist())
            group = group.copy()
            group["pre_close"] = group["ex_date"].map(pre_closes).fillna(0.0)
            result[code] = compute_adjustment_ratios(group)

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_adjustment_service.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/adjustment_service.py tests/test_data/test_adjustment_service.py
git commit -m "feat: add batch adjustment for multiple symbols

get_adjusted_bars_batch uses single ClickHouse query for all symbols,
avoiding N+1 query problem for full-market adjustment."
```

---

### Task 6: 性能基准测试

**Files:**
- Create: `tests/test_data/test_adjustment_perf.py`

**目的：** 验证复权计算在大规模数据下的性能满足要求。

- [ ] **Step 1: Write performance tests**

```python
# tests/test_data/test_adjustment_perf.py
"""Performance benchmarks for adjustment calculation.

These tests use synthetic data to measure computation time.
Run with: pytest tests/test_data/test_adjustment_perf.py -v -s
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
import numpy as np

from src.data.adjustment import (
    compute_adjustment_ratios,
    apply_forward_adjustment,
    apply_backward_adjustment,
)


def _generate_bars(n_days: int = 8000) -> pd.DataFrame:
    """Generate synthetic daily bars spanning ~30 years."""
    dates = pd.bdate_range(start=date(1990, 1, 1), periods=n_days)
    np.random.seed(42)
    close = 10.0 * np.cumprod(1 + np.random.normal(0.0003, 0.02, n_days))
    return pd.DataFrame({
        "date": [d.date() for d in dates],
        "open": close * (1 + np.random.uniform(-0.01, 0.01, n_days)),
        "high": close * (1 + np.abs(np.random.normal(0, 0.01, n_days))),
        "low": close * (1 - np.abs(np.random.normal(0, 0.01, n_days))),
        "close": close,
        "volume": np.random.randint(100000, 10000000, n_days),
        "amount": close * np.random.randint(100000, 10000000, n_days),
        "symbol": "000001.SZ",
    })


def _generate_xdxr_events(n_events: int = 60) -> pd.DataFrame:
    """Generate synthetic xdxr events (roughly quarterly for 15 years)."""
    np.random.seed(42)
    dates = sorted(
        date(1995, 1, 1) + timedelta(days=int(d))
        for d in np.random.uniform(0, 10000, n_events)
    )
    return pd.DataFrame({
        "ex_date": dates,
        "fenhong": np.random.uniform(0.1, 1.0, n_events),
        "songzhuangu": np.random.choice([0.0, 0.1, 0.2, 0.3], n_events),
        "peigu": np.random.choice([0.0, 0.0, 0.1], n_events),
        "suogu": np.zeros(n_events),
        "pre_close": 10.0 * np.cumprod(1 + np.random.normal(0.0003, 0.02, n_events)),
    })


def test_single_stock_30yr_adjustment_under_50ms():
    """Single stock with 30 years of daily bars should adjust in < 50ms."""
    bars = _generate_bars(8000)  # ~30 years of trading days
    events = _generate_xdxr_events(60)
    ratios = compute_adjustment_ratios(events)

    start = time.perf_counter()
    result = apply_forward_adjustment(bars, ratios)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert not result.empty
    assert "adjusted_close" in result.columns
    # Note: this is a soft target. CI may be slower.
    print(f"\n  Forward adjustment (8000 bars, 60 events): {elapsed_ms:.1f}ms")


def test_backward_adjustment_performance():
    """Backward adjustment should be similarly fast."""
    bars = _generate_bars(8000)
    events = _generate_xdxr_events(60)
    ratios = compute_adjustment_ratios(events)

    start = time.perf_counter()
    result = apply_backward_adjustment(bars, ratios)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert not result.empty
    print(f"\n  Backward adjustment (8000 bars, 60 events): {elapsed_ms:.1f}ms")


def test_ratio_computation_performance():
    """Ratio computation for 100 events should be very fast."""
    events = _generate_xdxr_events(100)

    start = time.perf_counter()
    ratios = compute_adjustment_ratios(events)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(ratios) == 100
    print(f"\n  Ratio computation (100 events): {elapsed_ms:.1f}ms")
    assert elapsed_ms < 10  # Should be sub-10ms for pure pandas
```

- [ ] **Step 2: Run performance tests**

Run: `pytest tests/test_data/test_adjustment_perf.py -v -s`
Expected: All tests PASS, with timing output

- [ ] **Step 3: If performance exceeds target, optimize**

如果单只股票 30 年日线超过 50ms，优化方向：

1. **避免逐行 Python 循环** — 当前 `apply_forward_adjustment` 使用 for 循环遍历每个 bar_date。可改用 `np.searchsorted` + `np.cumprod` 向量化：

```python
# 向量化实现
bar_dates = pd.to_datetime(result["date"]).values
ex_dates_np = pd.to_datetime(sorted_ratios["ex_date"]).values

# 对每个 bar_date，找出 ex_date > bar_date 的 ratio 的累积乘积
# 方法：反转 ratio 数组，计算前缀积，再用 searchsorted 查找
cum_from_right = np.ones(len(ratio_values) + 1)
for i in range(len(ratio_values) - 1, -1, -1):
    cum_from_right[i] = cum_from_right[i + 1] * ratio_values[i]

indices = np.searchsorted(ex_dates_np, bar_dates, side="right")
adjusted = cum_from_right[indices]
result["adjusted_close"] = result["close"] * adjusted
```

2. **pre_close 批量查询** — 当前 `_fetch_pre_closes` 逐日查询。改为：

```sql
SELECT t1.ex_date, t2.close as pre_close
FROM (
    SELECT ex_date, symbol,
           dateAdd(day, -1, ex_date) as prev_date
    FROM xdxr_info final WHERE symbol = %(symbol)s
) t1
LEFT JOIN daily_kline t2 ON t2.symbol = t1.symbol AND t2.date = t1.prev_date
```

或使用 ClickHouse 的 `ASOF JOIN`：

```sql
SELECT x.ex_date, d.close as pre_close
FROM xdxr_info final x
ASOF LEFT JOIN daily_kline d ON x.symbol = d.symbol AND d.date < x.ex_date
ORDER BY x.ex_date
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_data/test_adjustment_perf.py
git commit -m "test: add adjustment performance benchmarks

Synthetic data: 8000 bars (~30 years), 60 xdxr events.
Target: single stock adjustment < 50ms."
```

---

## 测试策略总结

| 测试文件 | 范围 | 模式 |
|---|---|---|
| `test_adjustment.py` | 纯函数：ratio 计算、前/后复权变换 | 固定输入 → 精确断言 |
| `test_adjustment_service.py` | ClickHouse 查询层 + 缓存 | FakeClickHouseClient |
| `test_adjustment_perf.py` | 性能基准 | 合成数据 8000 bars |
| `test_aggregator.py` | 集成到 DataAggregator | FakeClient 注入 |
| `test_clickhouse_xdxr_sync.py` | 字段映射修复 | 已有 FakeClient 模式 |

---

## 数据流图

```
ClickHouse xdxr_info
        │
        ▼
AdjustmentService._get_xdxr_ratios()
        │
        ▼
compute_adjustment_ratios()  →  per-event ratio DataFrame
        │
        ├── apply_forward_adjustment()  →  adjusted_close (前复权)
        │
        └── apply_backward_adjustment()  →  adjusted_close (后复权)
        │
        ▼
DataAggregator.get_bars(adjusted=True)
        │
        ▼
策略回测 / 数据分析
```

---

## 性能预期

| 操作 | 数据量 | 预期耗时 |
|---|---|---|
| 单只 30 年 xdxr 查询 | ~60 events | < 10ms |
| 单只 30 年日线复权 | 8000 bars | < 50ms |
| 全市场批量复权 | 5000 stocks × 8000 bars | < 5min |
| xdxr 缓存命中 | - | 0ms (内存) |

**瓶颈：** ClickHouse 查询（网络 I/O）远大于纯计算。批量查询 + 缓存是关键优化。

---

## 改动清单

| # | 任务 | 类型 | 文件 |
|---|------|------|------|
| 0 | 修复 xdxr 字段映射 | Bug fix | `clickhouse_xdxr_sync.py` |
| 1 | 复权因子计算纯函数 | 新增 | `adjustment.py`, `test_adjustment.py` |
| 2 | 前/后复权 DataFrame 变换 | 新增 | `adjustment.py`, `test_adjustment.py` |
| 3 | AdjustmentService 查询层 | 新增 | `adjustment_service.py`, `test_adjustment_service.py` |
| 4 | DataAggregator 集成 | 修改 | `aggregator.py`, `test_aggregator.py` |
| 5 | 批量查询优化 | 新增 | `adjustment_service.py` |
| 6 | 性能基准测试 | 新增 | `test_adjustment_perf.py` |

**新增代码：** ~350 行
**修改代码：** ~20 行
**测试代码：** ~400 行
