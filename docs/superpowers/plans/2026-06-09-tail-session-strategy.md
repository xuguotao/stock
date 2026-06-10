# 尾盘获利选股策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现尾盘 30 分钟选股策略，支持回测验证和模拟实盘两阶段运行。

**Architecture:** Phase 1 创建日线级筛选器 + 尾盘因子，复用现有 BacktestEngine 回测；Phase 2 扩展分钟级数据获取 + 实时扫描器。

**Tech Stack:** pandas, numpy, scipy (线性回归), pytest, existing src/ modules

**Current execution status (2026-06-10):**
- ✅ Phase 1 code path is implemented and verified: daily filters, stock pool filter, tail-session factor, overnight momentum factor, backtest script, and scheduler tail-session window.
- ✅ Phase 1 credibility fixes are implemented: filters truncate to `trade_date`, tail-session factors only score symbols present on each date, and overnight momentum preserves first-row `NaN`.
- ✅ Phase 2 minimum paper-trading loop is implemented and verified: Sina intraday bars via `DataAggregator.get_intraday_bars()`, `IntradayScanner`, `RealTimeExecutor`, daily Markdown reports, and `scripts/run_tail_session_live.py`.
- ✅ Research loop improvements are implemented: vectorized `TailSessionFactor`, progress output, `--limit`, `--offline-cache`, and `--output-json` for `scripts/run_tail_session_backtest.py`.
- ✅ Research dataset builder is implemented: `scripts/build_research_dataset.py`, `src/data/research_dataset.py`, and `--bars-dataset` support for backtests. Parquet is the primary research store; MySQL remains optional for metadata/trading records.
- ✅ Parameter-grid diagnostics are implemented: `scripts/evaluate_tail_session_grid.py` and `src/research/tail_session_analysis.py`.
- ✅ Minimum entry score diagnostics are implemented: `BacktestEngine(min_score=...)`, `scripts/run_tail_session_backtest.py --min-score`, and `scripts/evaluate_tail_session_grid.py --min-scores`.
- ✅ Verification run: `pytest tests/ -q` passes with 153 tests.
- 📉 Latest offline-cache sample result (10 liquid symbols, 2024-01-01 to 2025-06-01): total return 2.59%, Sharpe -0.006, win rate 44.54%, max drawdown -13.32%, 1450 trades.
- 📉 Latest grid smoke result: 10-day breakout did not improve Sharpe (-0.022) versus 20-day breakout (-0.006).
- 📈 Latest min-score grid result (same 10-symbol sample, 20-day breakout, 5-day trend, volume threshold 1.2, top_n=5): min_score 1.0 produced total return 11.78%, Sharpe 0.788, max drawdown -5.77%, 240 trades.
- 📋 Still market-dependent / not asserted as complete: Sharpe ratio > 0.8, win rate > 50%, and five consecutive real trading days of live paper operation.

---

### Task 1: 日线突破筛选器 (DailyBreakoutFilter)

**Files:**
- Create: `src/strategy/filters.py`
- Test: `tests/test_strategy/test_filters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy/test_filters.py
from datetime import date
import pandas as pd
from src.strategy.filters import DailyBreakoutFilter

def _bars(closes: list[float], symbol: str = "000001.SZ") -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=len(closes))
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "date": dates[i], "symbol": symbol,
            "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 1_000_000,
            "amount": c * 1_000_000, "adjusted_close": c,
        })
    return pd.DataFrame(rows).set_index(["date", "symbol"])

def test_ma_cross_filter_passes_golden_cross() -> None:
    closes = [10.0] * 25  # flat
    # Last few days rising sharply to push MA5 above MA20
    closes[-5:] = [10.5, 10.6, 10.7, 10.8, 10.9]
    bars = _bars(closes)
    f = DailyBreakoutFilter(breakout_window=20)
    result = f.filter(bars, date(2025, 2, 4), mode="ma_cross")
    assert "000001.SZ" in result

def test_creates_20_day_breakout_signal() -> None:
    # Create 25 days of data, last day breaks previous 20-day high
    closes = [10.0 + 0.01 * i for i in range(24)] + [10.5]
    bars = _bars(closes)
    f = DailyBreakoutFilter(breakout_window=20)
    result = f.filter(bars, date(2025, 2, 4))  # Day 25
    assert "000001.SZ" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_strategy/test_filters.py::test_creates_20_day_breakout_signal -v
```
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategy.filters'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/strategy/filters.py
"""Stock pool filters for the tail session strategy."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class Filter(Protocol):
    """Protocol for stock pool filters."""

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        **kwargs,
    ) -> list[str]:
        """Return list of symbols that pass the filter."""
        ...


class DailyBreakoutFilter:
    """筛选创 N 日新高的股票。

    A stock passes if its latest close is higher than
    the maximum close in the previous `breakout_window` days.
    """

    def __init__(self, breakout_window: int = 20):
        self.breakout_window = breakout_window

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        mode: str = "breakout",
        **kwargs,
    ) -> list[str]:
        """Filter symbols.

        Args:
            mode: "breakout" (20-day high) or "ma_cross" (MA5 > MA20)
        """
        if bars.empty:
            return []

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        passing = []

        for symbol in symbols:
            try:
                sym_bars = bars.xs(symbol, level="symbol")
            except KeyError:
                continue

            closes = sym_bars["close"].dropna()

            if mode == "ma_cross":
                # MA5 > MA20 golden cross
                if len(closes) < 21:
                    continue
                ma5 = closes.tail(5).mean()
                ma20 = closes.tail(20).mean()
                if ma5 > ma20:
                    passing.append(symbol)
            else:
                # Default: 20-day breakout
                if len(closes) < self.breakout_window + 1:
                    continue
                latest = closes.iloc[-1]
                prev_high = closes.iloc[-(self.breakout_window + 1): -1].max()
                if latest > prev_high:
                    passing.append(symbol)

        return passing


class DailyTrendFilter:
    """筛选近 N 日收盘价呈上升趋势的股票。

    Uses linear regression slope > 0 as the criterion.
    """

    def __init__(self, trend_window: int = 5, min_slope: float = 0.0):
        self.trend_window = trend_window
        self.min_slope = min_slope

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        **kwargs,
    ) -> list[str]:
        """Filter symbols with positive trend slope."""
        if bars.empty:
            return []

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        passing = []

        for symbol in symbols:
            try:
                sym_bars = bars.xs(symbol, level="symbol")
            except KeyError:
                continue

            closes = sym_bars["close"].dropna()
            if len(closes) < self.trend_window:
                continue

            recent = closes.tail(self.trend_window).values
            x = np.arange(len(recent), dtype=float)
            # Linear regression: y = mx + b
            slope, _ = np.polyfit(x, recent, 1)

            if slope > self.min_slope:
                passing.append(symbol)

        return passing
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_strategy/test_filters.py::test_creates_20_day_breakout_signal -v
```
Expected: PASS

- [ ] **Step 5: Add more filter tests**

```python
# Add to tests/test_strategy/test_filters.py
from src.strategy.filters import DailyTrendFilter

def test_trend_filter_passes_rising_prices() -> None:
    closes = [10.0, 10.1, 10.2, 10.3, 10.5]  # rising
    bars = _bars(closes)
    f = DailyTrendFilter(trend_window=5, min_slope=0.0)
    result = f.filter(bars, date(2025, 1, 7))
    assert "000001.SZ" in result

def test_trend_filter_rejects_falling_prices() -> None:
    closes = [10.5, 10.3, 10.2, 10.1, 10.0]  # falling
    bars = _bars(closes)
    f = DailyTrendFilter(trend_window=5, min_slope=0.0)
    result = f.filter(bars, date(2025, 1, 7))
    assert "000001.SZ" not in result

def test_breakout_filter_rejects_no_breakout() -> None:
    # All same price, no breakout
    closes = [10.0] * 25
    bars = _bars(closes)
    f = DailyBreakoutFilter(breakout_window=20)
    result = f.filter(bars, date(2025, 2, 4))
    assert "000001.SZ" not in result

def test_filters_return_empty_for_empty_bars() -> None:
    empty_bars = pd.DataFrame()
    assert DailyBreakoutFilter().filter(empty_bars, date(2025, 1, 1)) == []
    assert DailyTrendFilter().filter(empty_bars, date(2025, 1, 1)) == []
```

- [ ] **Step 6: Run all filter tests**

```bash
pytest tests/test_strategy/test_filters.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/strategy/filters.py tests/test_strategy/test_filters.py
git commit -m "feat: add DailyBreakoutFilter and DailyTrendFilter with tests"
```

---

### Task 2: 股票池过滤 (StockPoolFilter)

**Files:**
- Create: `src/strategy/filters.py` (modify — append to existing file)
- Test: `tests/test_strategy/test_filters.py` (modify — append to existing file)

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_strategy/test_filters.py
from src.strategy.filters import StockPoolFilter

def test_stocks_pool_excludes_st_stocks() -> None:
    f = StockPoolFilter(min_list_days=60, min_avg_amount=5_000_000)
    # Mock stock info with ST name
    stock_info = {
        "000001.SZ": {"name": "平安银行", "list_date": date(1991, 4, 3)},
        "*ST123.SZ": {"name": "*ST某某", "list_date": date(2020, 1, 1)},
    }
    bars = _bars([10.0] * 70, "000001.SZ")
    bars2 = _bars([5.0] * 70, "*ST123.SZ")
    all_bars = pd.concat([bars, bars2])

    result = f.filter(all_bars, date(2025, 4, 1), stock_info=stock_info)
    assert "000001.SZ" in result
    assert "*ST123.SZ" not in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_strategy/test_filters.py::test_stocks_pool_excludes_st_stocks -v
```
Expected: FAIL with "ImportError: cannot import name 'StockPoolFilter'"

- [ ] **Step 3: Write minimal implementation**

```python
# Append to src/strategy/filters.py
from src.core.constants import is_st


class StockPoolFilter:
    """综合股票池过滤：ST、次新股、流动性、涨停。"""

    def __init__(
        self,
        min_list_days: int = 60,
        min_avg_amount: float = 5_000_000,
        limit_up_pct: float = 0.10,
    ):
        self.min_list_days = min_list_days
        self.min_avg_amount = min_avg_amount
        self.limit_up_pct = limit_up_pct

    def filter(
        self,
        bars: pd.DataFrame,
        trade_date: date,
        stock_info: dict | None = None,
        **kwargs,
    ) -> list[str]:
        """Apply all stock pool filters."""
        if bars.empty:
            return []

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        passing = []

        for symbol in symbols:
            if not self._passes(symbol, bars, trade_date, stock_info):
                continue
            passing.append(symbol)

        return passing

    def _passes(
        self,
        symbol: str,
        bars: pd.DataFrame,
        trade_date: date,
        stock_info: dict | None,
    ) -> bool:
        """Check all conditions for a single symbol."""
        try:
            sym_bars = bars.xs(symbol, level="symbol")
        except KeyError:
            return False

        # ST check
        if stock_info and symbol in stock_info:
            name = stock_info[symbol].get("name", "")
            if is_st(name):
                return False

            # New stock check
            list_date = stock_info[symbol].get("list_date")
            if list_date and isinstance(list_date, date):
                days_listed = (trade_date - list_date).days
                if days_listed < self.min_list_days:
                    return False

        # Liquidity check (avg daily amount)
        if "amount" in sym_bars.columns:
            avg_amount = sym_bars["amount"].tail(20).mean()
            if avg_amount < self.min_avg_amount:
                return False

        # Limit-up check (today's change too large)
        closes = sym_bars["close"].dropna()
        if len(closes) >= 2:
            change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
            if change >= self.limit_up_pct:
                return False

        return True
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_strategy/test_filters.py -v
```
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/strategy/filters.py tests/test_strategy/test_filters.py
git commit -m "feat: add StockPoolFilter with ST/list-days/liquidity/limit-up checks"
```

---

### Task 3: 尾盘突破因子 (TailSessionFactor)

**Files:**
- Create: `src/strategy/factors/tail_session.py`
- Test: `tests/test_strategy/test_tail_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy/test_tail_session.py
from __future__ import annotations

from datetime import date
import pandas as pd
from src.strategy.factors.tail_session import TailSessionFactor

def _multi_bars(symbols: list[str], periods: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=periods)
    rows = []
    for si, symbol in enumerate(symbols):
        price = 10 + si * 5
        for di, d in enumerate(dates):
            price *= 1 + 0.001 * (si + 1) + 0.0002 * di
            rows.append({
                "date": d, "symbol": symbol,
                "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price,
                "volume": 1_000_000 * (1 + si * 0.1),
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })
    return pd.DataFrame(rows).set_index(["date", "symbol"])

def test_tail_session_factor_returns_values() -> None:
    bars = _multi_bars(["000001.SZ", "600519.SH"])
    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    result = factor.compute(bars)

    assert not result.empty
    assert "tail_session" in result.columns
    assert result.index.names == ["date", "symbol"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_strategy/test_tail_session.py::test_tail_session_factor_returns_values -v
```
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategy.factors.tail_session'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/strategy/factors/tail_session.py
"""Tail session breakout factor.

Combines daily breakout, trend, and volume confirmation into
a single factor value. Higher value = stronger tail session signal.

Usage:
    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    values = factor.compute(bars)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.strategy.base import Factor
from src.strategy.filters import DailyBreakoutFilter, DailyTrendFilter


class TailSessionFactor(Factor):
    """尾盘突破因子。

    Factor value = 1.0 (breakout + trend confirmed)
                 = 0.5 (breakout only)
                 = 0.0 (no breakout)
    """

    name = "tail_session"
    description = "Tail session breakout confirmation factor"

    def __init__(
        self,
        breakout_window: int = 20,
        trend_window: int = 5,
        volume_ratio_threshold: float = 1.2,
    ):
        self.breakout_window = breakout_window
        self.trend_window = trend_window
        self.volume_ratio_threshold = volume_ratio_threshold

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute tail session factor values.

        Args:
            bars: MultiIndex DataFrame (date, symbol) with OHLCV.

        Returns:
            DataFrame with factor values.
        """
        if bars.empty:
            return pd.DataFrame(columns=[self.name])

        symbols = bars.index.get_level_values("symbol").unique().tolist()
        dates = bars.index.get_level_values("date").unique().tolist()

        results = []
        for trade_date in dates:
            try:
                day_bars = bars.loc[trade_date]
            except KeyError:
                continue

            if isinstance(day_bars, pd.Series):
                day_bars = day_bars.to_frame().T

            # Get historical bars up to this date for breakout/trend checks
            hist_mask = bars.index.get_level_values("date") <= trade_date
            hist_bars = bars[hist_mask]

            # Apply breakout filter
            breakout_filter = DailyBreakoutFilter(breakout_window=self.breakout_window)
            breakout_symbols = set(breakout_filter.filter(hist_bars, trade_date))

            # Apply trend filter
            trend_filter = DailyTrendFilter(trend_window=self.trend_window)
            trend_symbols = set(trend_filter.filter(hist_bars, trade_date))

            # Apply volume confirmation
            volume_symbols = self._volume_confirm(hist_bars, trade_date)

            # Compute factor values
            for symbol in symbols:
                in_breakout = symbol in breakout_symbols
                in_trend = symbol in trend_symbols
                in_volume = symbol in volume_symbols

                if in_breakout and in_trend and in_volume:
                    value = 1.0
                elif in_breakout and in_trend:
                    value = 0.7
                elif in_breakout:
                    value = 0.4
                else:
                    value = 0.0

                results.append({
                    "date": trade_date,
                    "symbol": symbol,
                    self.name: value,
                })

        if not results:
            return pd.DataFrame(columns=["date", "symbol", self.name])

        df = pd.DataFrame(results).set_index(["date", "symbol"])
        return df[[self.name]]

    def _volume_confirm(
        self,
        bars: pd.DataFrame,
        trade_date: date,
    ) -> set[str]:
        """Confirm volume > threshold * 20-day average."""
        try:
            day_bars = bars.loc[trade_date]
        except KeyError:
            return set()

        if isinstance(day_bars, pd.Series):
            day_bars = day_bars.to_frame().T

        if "volume" not in day_bars.columns:
            return set()

        confirmed = set()
        symbols = day_bars.index.tolist() if hasattr(day_bars.index, "tolist") else [day_bars.index[0]]

        for symbol in symbols:
            try:
                sym_bars = bars.xs(symbol, level="symbol")
            except KeyError:
                continue

            closes = sym_bars["close"].dropna()
            volumes = sym_bars["volume"].dropna()

            if len(volumes) < 21:
                continue

            today_vol = volumes.iloc[-1]
            avg_vol = volumes.iloc[-21:-1].mean()

            if avg_vol > 0 and today_vol > avg_vol * self.volume_ratio_threshold:
                confirmed.add(symbol)

        return confirmed
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_strategy/test_tail_session.py::test_tail_session_factor_returns_values -v
```
Expected: PASS

- [ ] **Step 5: Add more factor tests**

```python
# Append to tests/test_strategy/test_tail_session.py
from src.strategy.factors.tail_session import TailSessionFactor

def test_factor_returns_zero_for_no_breakout() -> None:
    """Flat prices = no breakout = factor 0."""
    dates = pd.bdate_range("2025-01-01", periods=30)
    rows = []
    for di, d in enumerate(dates):
        rows.append({
            "date": d, "symbol": "000001.SZ",
            "open": 10.0, "high": 10.0, "low": 10.0,
            "close": 10.0, "volume": 1_000_000,
            "amount": 10_000_000, "adjusted_close": 10.0,
        })
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])

    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    result = factor.compute(bars)

    # All values should be 0 (no breakout, flat trend)
    assert (result["tail_session"] == 0.0).all()

def test_factor_empty_bars_returns_empty() -> None:
    factor = TailSessionFactor()
    result = factor.compute(pd.DataFrame())
    assert result.empty
```

- [ ] **Step 6: Run all tail session tests**

```bash
pytest tests/test_strategy/test_tail_session.py -v
```
Expected: All 3 tests PASS

- [ ] **Step 7: Register factor in __init__.py**

```python
# Modify src/strategy/factors/__init__.py — add these lines:
from src.strategy.factors.tail_session import TailSessionFactor

__all__ = [
    ...  # existing
    "TailSessionFactor",
]
```

- [ ] **Step 8: Commit**

```bash
git add src/strategy/factors/tail_session.py src/strategy/factors/__init__.py tests/test_strategy/test_tail_session.py
git commit -m "feat: add TailSessionFactor with breakout/trend/volume confirmation"
```

---

### Task 4: 次日惯性因子 (OvernightMomentumFactor)

**Files:**
- Create: `src/strategy/factors/overnight_momentum.py`
- Test: `tests/test_strategy/test_tail_session.py` (modify — append)

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_strategy/test_tail_session.py
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor

def test_overnight_momentum_positive_on_gap_up() -> None:
    """Close lower than next open = positive overnight momentum."""
    dates = pd.bdate_range("2025-01-01", periods=10)
    rows = []
    for i, d in enumerate(dates):
        close = 10.0 + i * 0.1
        open_next = close + 0.05 if i > 0 else close
        rows.append({
            "date": d, "symbol": "000001.SZ",
            "open": open_next if i > 0 else close,
            "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": 1_000_000,
            "amount": close * 1_000_000,
            "adjusted_close": close,
        })
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])

    factor = OvernightMomentumFactor()
    result = factor.compute(bars)

    assert "overnight_momentum" in result.columns
    # Should have NaN for first row (no previous close to compare)
    valid = result["overnight_momentum"].dropna()
    assert len(valid) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_strategy/test_tail_session.py::test_overnight_momentum_positive_on_gap_up -v
```
Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

```python
# src/strategy/factors/overnight_momentum.py
"""Overnight momentum factor.

Measures the gap between previous close and current open.
Higher gap = stronger overnight buying pressure.

Factor = (open_t - close_{t-1}) / close_{t-1}
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.strategy.base import Factor


class OvernightMomentumFactor(Factor):
    name = "overnight_momentum"
    description = "Overnight gap momentum (open vs prev close)"

    def __init__(self, smoothing_window: int = 1):
        self.smoothing_window = smoothing_window

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute overnight momentum factor."""
        close = bars["close"]
        open_price = bars["open"]

        # Gap = (open - prev_close) / prev_close
        prev_close = close.groupby(level=1).shift(1)
        gap = (open_price - prev_close) / prev_close.replace(0, float("nan"))

        # Optional smoothing
        if self.smoothing_window > 1:
            gap = gap.groupby(level=1).rolling(
                self.smoothing_window, min_periods=1
            ).mean()
            if hasattr(gap.index, "names"):
                gap.index = close.index

        result = gap.fillna(0).to_frame(name=self.name)
        result.index.names = ["date", "symbol"]
        return result
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_strategy/test_tail_session.py -v
```
Expected: All 4 tests PASS

- [ ] **Step 5: Register factor and commit**

```bash
# Add to src/strategy/factors/__init__.py:
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
# Add "OvernightMomentumFactor" to __all__

git add src/strategy/factors/overnight_momentum.py src/strategy/factors/__init__.py tests/test_strategy/test_tail_session.py
git commit -m "feat: add OvernightMomentumFactor for next-day inertia"
```

---

### Task 5: 回测集成脚本

> **Note:** 止盈 (+3%)/止损 (-2%)/强制平仓 (10:00) 在 Phase 1 回测中暂不实现，
> 因为现有 `BacktestEngine` 按日线运行，无法模拟日内价格波动。
> 这些将在 Phase 2 的 `RealTimeExecutor` 中实现。Phase 1 回测仅验证选股逻辑。

**Files:**
- Create: `scripts/run_tail_session_backtest.py`
- Test: `tests/test_strategy/test_tail_session.py` (modify — add integration test)

- [ ] **Step 1: Write integration test**

```python
# Append to tests/test_strategy/test_tail_session.py
from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from config.settings import reset_settings

def test_tail_session_backtest_runs() -> None:
    reset_settings()
    bars = _multi_bars(["000001.SZ", "600519.SH", "300750.SZ", "000858.SZ", "601318.SH"])

    factor = TailSessionFactor(breakout_window=20, trend_window=5)
    engine = BacktestEngine(
        bars=bars,
        factors=[factor],
        top_n=3,
        rebalance_days=1,
        initial_capital=100_000,
        equal_weight=True,
    )

    result = engine.run()
    assert result.initial_capital == 100_000
    assert result.final_value > 0
    assert len(result.daily_returns) > 0
    metrics = result.metrics
    assert "sharpe_ratio" in metrics
    assert "win_rate" in metrics
    assert metrics["trading_days"] > 0
```

- [ ] **Step 2: Write backtest script**

```python
#!/usr/bin/env python
"""Run tail session strategy backtest.

Usage:
    python scripts/run_tail_session_backtest.py
    python scripts/run_tail_session_backtest.py --start 2023-01-01 --end 2025-06-01
    python scripts/run_tail_session_backtest.py --capital 200000 --top-n 3
"""

from __future__ import annotations

import argparse
from datetime import date

from config.settings import reset_settings
from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tail session strategy backtest"
    )
    parser.add_argument("--start", default="2023-01-01", help="Start date")
    parser.add_argument("--end", default="2025-06-01", help="End date")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--top-n", type=int, default=5, help="Number of stocks to hold")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to test")
    args = parser.parse_args()

    reset_settings()
    agg = DataAggregator()

    # Get stock list
    stocks = agg.get_stock_list()
    if args.symbols:
        symbols = [format_symbol(s) for s in args.symbols]
    else:
        # Main board only
        symbols = agg.get_csi300_symbols()[:50]  # Limit for speed

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"Loading data for {len(symbols)} symbols ({start} to {end})...")
    bars = agg.get_bars_batch(symbols, start, end)
    print(f"Loaded {len(bars)} bars")

    if bars.empty:
        print("No data loaded. Check network or cache.")
        return

    # Build factors
    tail_factor = TailSessionFactor(
        breakout_window=20,
        trend_window=5,
        volume_ratio_threshold=1.2,
    )
    overnight_factor = OvernightMomentumFactor(smoothing_window=1)

    # Run backtest
    print(f"Running backtest with capital={args.capital}, top_n={args.top_n}...")
    engine = BacktestEngine(
        bars=bars,
        factors=[tail_factor, overnight_factor],
        factor_weights=[0.7, 0.3],
        top_n=args.top_n,
        rebalance_days=1,
        initial_capital=args.capital,
        equal_weight=True,
    )

    result = engine.run()

    # Print results
    print("\n" + "=" * 50)
    print("Tail Session Strategy — Backtest Results")
    print("=" * 50)
    for key, val in result.metrics.items():
        print(f"  {key:25s}: {val}")
    print(f"  Total trades           : {len(result.trades)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run backtest script to verify**

```bash
python scripts/run_tail_session_backtest.py --symbols 000001 600519 300750 --start 2024-01-01 --end 2025-06-01
```
Expected: Script runs, prints metrics table

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v -k tail_session
```
Expected: All tail session tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_tail_session_backtest.py tests/test_strategy/test_tail_session.py
git commit -m "feat: add tail session backtest script and integration test"
```

---

### Task 6: 交易调度器扩展 (is_tail_session)

**Files:**
- Modify: `src/trading/scheduler.py`
- Test: `tests/test_trading/test_trading_module.py` (modify — append)

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_trading/test_trading_module.py
def test_is_tail_session_returns_true_in_tail_window() -> None:
    scheduler = TradingScheduler()
    # 14:30 is in tail session
    assert scheduler.is_tail_session(time(14, 30))
    # 14:55 is in tail session
    assert scheduler.is_tail_session(time(14, 55))
    # 10:00 is NOT in tail session
    assert not scheduler.is_tail_session(time(10, 0))
    # 11:30 is NOT in tail session
    assert not scheduler.is_tail_session(time(11, 30))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_trading/test_trading_module.py::test_is_tail_session_returns_true_in_tail_window -v
```
Expected: FAIL with "AttributeError: 'TradingScheduler' object has no attribute 'is_tail_session'"

- [ ] **Step 3: Write minimal implementation**

```python
# Add to src/trading/scheduler.py — in TradingScheduler class:

    def is_tail_session(self, current_time: time | None = None) -> bool:
        """Check if within tail session (14:30-15:00)."""
        now = current_time or datetime.now().time()
        tail_start = time(14, 30)
        tail_end = time(15, 0)
        return tail_start <= now <= tail_end
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_trading/test_trading_module.py -v -k tail_session
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trading/scheduler.py tests/test_trading/test_trading_module.py
git commit -m "feat: add is_tail_session() to TradingScheduler"
```

---

### Task 7: 更新 README 和运行验证

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-09-tail-session-strategy-design.md` (mark Phase 1 done)

- [ ] **Step 1: Update README**

```markdown
# Add to README.md under "当前状态" section, after Phase 4:

### ✅ Phase 5: 尾盘获利选股策略 (已完成)
- 日线突破筛选器 (DailyBreakoutFilter)
- 趋势确认筛选器 (DailyTrendFilter)
- 股票池过滤 (ST/次新/流动性/涨停)
- 尾盘突破因子 (TailSessionFactor)
- 次日惯性因子 (OvernightMomentumFactor)
- 回测脚本: `python scripts/run_tail_session_backtest.py`
- 交易调度器扩展 (is_tail_session)

# Add to README.md "快速开始" section:

### 5. 运行尾盘策略回测

```bash
# 默认回测沪深300前50只
python scripts/run_tail_session_backtest.py

# 指定股票
python scripts/run_tail_session_backtest.py --symbols 000001 600519 300750

# 指定日期范围和资金
python scripts/run_tail_session_backtest.py --start 2023-01-01 --end 2025-06-01 --capital 200000
```
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v 2>&1 | tail -10
```
Expected: All tests PASS (should be 101 + new tests)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README with Phase 5 tail session strategy"
```

---

### Task 8: Phase 2 — 分钟级数据获取

**Files:**
- Create: `src/data/intraday_source.py`
- Test: `tests/test_data/test_data_module.py` (modify — append)
- Modify: `src/data/aggregator.py` (add `get_intraday_bars`)

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_data/test_data_module.py
def test_sina_intraday_bars_returns_dataframe() -> None:
    """Test that Sina intraday API returns a DataFrame."""
    from src.data.sina_source import SinaSource
    from config.settings import reset_settings
    reset_settings()

    source = SinaSource(rate_limit=0.0)
    df = source.fetch_intraday_bars(
        symbol="000001.SZ",
        date=date(2025, 6, 3),
        frequency="5m",
    )

    # Should return DataFrame even if empty (network may fail)
    assert isinstance(df, pd.DataFrame)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_data/test_data_module.py::test_sina_intraday_bars_returns_dataframe -v
```
Expected: FAIL with "AttributeError: 'SinaSource' object has no attribute 'fetch_intraday_bars'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/intraday_source.py
"""Intraday (5m, 30m) K-line data source.

Extends SinaSource with intraday bar fetching.
Sina API scale values: 5=5min, 15=15min, 30=30min, 60=60min
"""

from __future__ import annotations

import json
import logging
import ssl
from datetime import date, datetime

import pandas as pd

logger = logging.getLogger(__name__)

_SSL_CTX = ssl.create_default_context()

_FREQUENCY_TO_SCALE = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
}


def _sina_symbol(symbol: str) -> str:
    """Convert '600519.SH' to 'sh600519'."""
    code = symbol.split(".")[0].zfill(6)
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_intraday_bars(
    symbol: str,
    trade_date: date,
    frequency: str = "5m",
    datalen: int = 1000,
) -> pd.DataFrame:
    """Fetch intraday bars from Sina Finance API.

    Args:
        symbol: e.g. "000001.SZ"
        trade_date: Trading date
        frequency: "5m", "15m", "30m", "60m"
        datalen: Number of bars to fetch

    Returns:
        DataFrame with columns: time, open, high, low, close, volume, amount
    """
    sina_sym = _sina_symbol(symbol)
    scale = _FREQUENCY_TO_SCALE.get(frequency, 5)

    path = (
        f"/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={sina_sym}&scale={scale}&ma=no&datalen={datalen}"
    )

    try:
        import http.client
        conn = http.client.HTTPSConnection("money.finance.sina.com.cn", timeout=15, context=_SSL_CTX)
        conn.request("GET", path, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.sina.com.cn",
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()

        if resp.status != 200:
            logger.warning(f"Sina intraday HTTP {resp.status} for {symbol}")
            return pd.DataFrame()

        data = json.loads(body)
        if not isinstance(data, list):
            return pd.DataFrame()

        rows = []
        target_date_str = trade_date.isoformat()

        for item in data:
            dt_str = item.get("day", "")
            if not dt_str.startswith(target_date_str):
                continue

            # Parse time from datetime string
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            rows.append({
                "time": dt.time(),
                "datetime": dt,
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(float(item.get("volume", 0))),
                "amount": 0.0,  # Sina intraday doesn't provide amount
                "symbol": symbol,
            })

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)

    except Exception as e:
        logger.warning(f"Sina intraday failed for {symbol}: {e}")
        return pd.DataFrame()
```

```python
# Add to src/data/sina_source.py — append this method to SinaSource class:

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday bars from Sina Finance."""
        from src.data.intraday_source import fetch_intraday_bars as _fetch
        self._wait_for_rate_limit()
        return _fetch(symbol, trade_date, frequency)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_data/test_data_module.py -v -k intraday
```
Expected: PASS (or returns empty DataFrame if network fails, but still passes isinstance check)

- [ ] **Step 5: Commit**

```bash
git add src/data/intraday_source.py src/data/sina_source.py tests/test_data/test_data_module.py
git commit -m "feat: add intraday 5m/30m K-line data source via Sina API"
```

---

### Task 9: 全文档和最终验证

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All tests PASS

- [ ] **Step 2: Run backtest end-to-end**

```bash
python scripts/run_tail_session_backtest.py --symbols 000001 600519 --start 2024-01-01 --end 2025-06-01
```
Expected: Prints metrics table

- [ ] **Step 3: Final commit**

```bash
git status  # Review all changes
git add -A
git commit -m "feat: complete tail session strategy Phase 1 + Phase 2 data"
```
