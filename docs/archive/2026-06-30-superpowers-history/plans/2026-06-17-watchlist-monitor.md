# Watchlist Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dashboard page that shows the configured stock watchlist, current analysis state, entry zones, and rule reasons.

**Architecture:** Add a pure Python monitoring core that loads YAML config and classifies each stock from quote and daily-bar inputs. Expose the report through a small FastAPI endpoint and render it in a Vue page with status cards, a table, and selected-stock details.

**Tech Stack:** Python 3.12, pandas, PyYAML, FastAPI, pytest, Vue 3, Element Plus, Vitest-style frontend tests already present in the repo.

---

## File Structure

- Create `config/watchlist_monitor.yaml`: first-version stock list and manual price levels.
- Create `src/monitoring/watchlist.py`: config dataclasses, metric calculation, status classification, report rendering payload.
- Create `src/web/backend/watchlist_monitor.py`: API adapter that loads config and delegates to monitor core.
- Modify `src/web/backend/app.py`: inject a watchlist runner and expose `/api/watchlist-monitor/config` and `/api/watchlist-monitor/report`.
- Modify `frontend/src/api/client.ts`: add watchlist monitor response types and API helpers.
- Create `frontend/src/pages/WatchlistMonitor.vue`: dashboard page for summary cards, table, and details.
- Modify `frontend/src/App.vue`: add menu entry and page routing.
- Create `tests/test_monitoring/test_watchlist.py`: pure-rule tests.
- Create `tests/test_web/test_watchlist_monitor_api.py`: API shape tests.
- Create `tests/test_frontend/test_watchlist_monitor_page.py`: static page test for expected labels.

## Task 1: Monitoring Core and Config

**Files:**
- Create: `config/watchlist_monitor.yaml`
- Create: `src/monitoring/watchlist.py`
- Create: `tests/test_monitoring/test_watchlist.py`

- [ ] **Step 1: Write failing monitoring tests**

Create `tests/test_monitoring/test_watchlist.py`:

```python
from __future__ import annotations

import pandas as pd

from src.monitoring.watchlist import (
    WatchlistLevels,
    WatchlistStockConfig,
    classify_watchlist_stock,
    compute_stock_metrics,
    load_watchlist_config,
)


def test_load_watchlist_config_reads_stock_levels(tmp_path) -> None:
    config_path = tmp_path / "watchlist.yaml"
    config_path.write_text(
        """
stocks:
  - symbol: "601899"
    name: "紫金矿业"
    theme: "金铜资源"
    notes: "关注金铜价格。"
    levels:
      observe: [30.0, 30.5]
      entry: [29.5, 29.8]
      add: [28.5, 29.0]
      invalid: 27.0
      breakout: 32.0
""".strip(),
        encoding="utf-8",
    )

    config = load_watchlist_config(config_path)

    assert len(config.stocks) == 1
    assert config.stocks[0].symbol == "601899"
    assert config.stocks[0].levels.entry == (29.5, 29.8)


def test_classify_entry_zone_takes_precedence_over_hot_return() -> None:
    stock = WatchlistStockConfig(
        symbol="601899",
        name="紫金矿业",
        theme="金铜资源",
        notes="",
        levels=WatchlistLevels(
            observe=(30.0, 30.5),
            entry=(29.5, 29.8),
            add=(28.5, 29.0),
            invalid=27.0,
            breakout=32.0,
        ),
    )

    result = classify_watchlist_stock(
        stock,
        latest_price=29.7,
        daily_change_pct=2.0,
        return_5d=0.22,
        return_20d=0.4,
        volume_ratio=1.4,
    )

    assert result.status == "entry_zone"
    assert "试仓区" in " ".join(result.reasons)


def test_classify_hot_wait_after_large_recent_gain() -> None:
    stock = WatchlistStockConfig(
        symbol="000636",
        name="风华高科",
        theme="MLCC",
        notes="",
        levels=WatchlistLevels(
            observe=(68.0, 70.0),
            entry=(64.0, 66.0),
            add=(58.0, 60.0),
            invalid=54.0,
            breakout=72.0,
        ),
    )

    result = classify_watchlist_stock(
        stock,
        latest_price=73.0,
        daily_change_pct=5.0,
        return_5d=0.18,
        return_20d=0.6,
        volume_ratio=1.0,
    )

    assert result.status == "hot_wait"
    assert any("涨幅过大" in reason for reason in result.reasons)


def test_compute_stock_metrics_calculates_returns_and_volume_ratio() -> None:
    bars = pd.DataFrame({
        "close": [10, 11, 12, 13, 14, 15],
        "volume": [100, 100, 100, 100, 100, 250],
    })

    metrics = compute_stock_metrics(bars)

    assert metrics["return_5d"] == 0.5
    assert metrics["ma5"] == 13.0
    assert metrics["volume_ratio"] == 2.5
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_monitoring/test_watchlist.py -q`

Expected: fails because `src.monitoring.watchlist` does not exist.

- [ ] **Step 3: Add config**

Create `config/watchlist_monitor.yaml` with:

```yaml
stocks:
  - symbol: "000636"
    name: "风华高科"
    theme: "MLCC / 被动元件"
    notes: "MLCC主线龙头之一，短线涨幅大，优先等待回踩。"
    levels:
      observe: [68.0, 70.0]
      entry: [64.0, 66.0]
      add: [58.0, 60.0]
      invalid: 54.0
      breakout: 72.0
  - symbol: "002859"
    name: "洁美科技"
    theme: "MLCC耗材 / 载带"
    notes: "关注MLCC耗材需求，等待回踩到前压力区附近。"
    levels:
      observe: [85.0, 87.0]
      entry: [82.0, 85.0]
      add: [75.0, 78.0]
      invalid: 74.0
      breakout: 94.0
  - symbol: "300285"
    name: "国瓷材料"
    theme: "MLCC上游材料"
    notes: "陶瓷粉体材料逻辑强，短线高位波动大。"
    levels:
      observe: [66.0, 68.0]
      entry: [63.0, 65.0]
      add: [57.0, 60.0]
      invalid: 54.0
      breakout: 70.0
  - symbol: "300408"
    name: "三环集团"
    theme: "MLCC / 陶瓷元件"
    notes: "相对稳健的MLCC链标的，关注150附近承接。"
    levels:
      observe: [145.0, 150.0]
      entry: [138.0, 142.0]
      add: [125.0, 130.0]
      invalid: 120.0
      breakout: 157.0
  - symbol: "300014"
    name: "亿纬锂能"
    theme: "电池 / 储能"
    notes: "等待大涨后回踩确认，关注储能与动力电池利润兑现。"
    levels:
      observe: [63.0, 65.0]
      entry: [60.0, 62.0]
      add: [55.0, 58.0]
      invalid: 53.0
      breakout: 68.0
  - symbol: "688017"
    name: "绿的谐波"
    theme: "机器人 / 减速器"
    notes: "机器人高弹性标的，高位波动大，等待回踩或突破确认。"
    levels:
      observe: [350.0, 360.0]
      entry: [330.0, 345.0]
      add: [300.0, 315.0]
      invalid: 287.0
      breakout: 390.0
  - symbol: "601899"
    name: "紫金矿业"
    theme: "金铜资源"
    notes: "关注金铜价格、Q2利润和现金流延续性。"
    levels:
      observe: [30.0, 30.5]
      entry: [29.5, 29.8]
      add: [28.5, 29.0]
      invalid: 27.0
      breakout: 32.0
```

- [ ] **Step 4: Implement monitoring core**

Create `src/monitoring/watchlist.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass(frozen=True)
class WatchlistLevels:
    observe: tuple[float, float]
    entry: tuple[float, float]
    add: tuple[float, float]
    invalid: float
    breakout: float | None = None


@dataclass(frozen=True)
class WatchlistStockConfig:
    symbol: str
    name: str
    theme: str
    notes: str
    levels: WatchlistLevels


@dataclass(frozen=True)
class WatchlistConfig:
    stocks: list[WatchlistStockConfig]


@dataclass(frozen=True)
class WatchlistStockAnalysis:
    symbol: str
    name: str
    theme: str
    notes: str
    latest_price: float | None
    daily_change_pct: float | None
    return_5d: float | None
    return_20d: float | None
    ma5: float | None
    ma20: float | None
    volume_ratio: float | None
    status: str
    reasons: list[str]
    levels: WatchlistLevels
    data_status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "theme": self.theme,
            "notes": self.notes,
            "latest_price": self.latest_price,
            "daily_change_pct": self.daily_change_pct,
            "return_5d": self.return_5d,
            "return_20d": self.return_20d,
            "ma5": self.ma5,
            "ma20": self.ma20,
            "volume_ratio": self.volume_ratio,
            "status": self.status,
            "reasons": self.reasons,
            "levels": {
                "observe": list(self.levels.observe),
                "entry": list(self.levels.entry),
                "add": list(self.levels.add),
                "invalid": self.levels.invalid,
                "breakout": self.levels.breakout,
            },
            "data_status": self.data_status,
        }


@dataclass(frozen=True)
class WatchlistReport:
    trade_date: str
    items: list[WatchlistStockAnalysis]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "summary": summarize_statuses(self.items),
            "items": [item.to_dict() for item in self.items],
        }


def load_watchlist_config(path: str | Path) -> WatchlistConfig:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    stocks = []
    for raw in payload.get("stocks", []):
        levels = raw["levels"]
        stocks.append(
            WatchlistStockConfig(
                symbol=str(raw["symbol"]),
                name=str(raw["name"]),
                theme=str(raw.get("theme", "")),
                notes=str(raw.get("notes", "")),
                levels=WatchlistLevels(
                    observe=_range(levels["observe"], "observe"),
                    entry=_range(levels["entry"], "entry"),
                    add=_range(levels["add"], "add"),
                    invalid=float(levels["invalid"]),
                    breakout=float(levels["breakout"]) if levels.get("breakout") is not None else None,
                ),
            )
        )
    if not stocks:
        raise ValueError(f"{config_path} must contain at least one stock")
    return WatchlistConfig(stocks=stocks)


def compute_stock_metrics(bars: pd.DataFrame) -> dict[str, float | None]:
    if bars is None or bars.empty:
        return {"return_5d": None, "return_20d": None, "ma5": None, "ma20": None, "volume_ratio": None}
    df = bars.copy()
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    volumes = pd.to_numeric(df.get("volume", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "return_5d": _period_return(closes, 5),
        "return_20d": _period_return(closes, 20),
        "ma5": _mean_tail(closes, 5),
        "ma20": _mean_tail(closes, 20),
        "volume_ratio": _volume_ratio(volumes, 5),
    }


def classify_watchlist_stock(
    stock: WatchlistStockConfig,
    *,
    latest_price: float | None,
    daily_change_pct: float | None,
    return_5d: float | None,
    return_20d: float | None,
    volume_ratio: float | None,
    ma5: float | None = None,
    ma20: float | None = None,
    data_status: str = "ok",
) -> WatchlistStockAnalysis:
    reasons: list[str] = []
    status = "neutral"
    levels = stock.levels

    if latest_price is None:
        return WatchlistStockAnalysis(
            symbol=stock.symbol,
            name=stock.name,
            theme=stock.theme,
            notes=stock.notes,
            latest_price=None,
            daily_change_pct=daily_change_pct,
            return_5d=return_5d,
            return_20d=return_20d,
            ma5=ma5,
            ma20=ma20,
            volume_ratio=volume_ratio,
            status="neutral",
            reasons=["最新行情不可用，仅展示配置区间。"],
            levels=levels,
            data_status=data_status,
        )

    if latest_price <= levels.invalid:
        status = "risk_off"
        reasons.append(f"价格 {latest_price:.2f} 已低于失效位 {levels.invalid:.2f}。")
    elif _inside(latest_price, levels.add):
        status = "add_zone"
        reasons.append(f"价格 {latest_price:.2f} 进入加仓区 {levels.add[0]:.2f}-{levels.add[1]:.2f}。")
    elif _inside(latest_price, levels.entry):
        status = "entry_zone"
        reasons.append(f"价格 {latest_price:.2f} 进入试仓区 {levels.entry[0]:.2f}-{levels.entry[1]:.2f}。")
    elif _inside(latest_price, levels.observe) or latest_price <= levels.observe[1] * 1.02:
        status = "watch_pullback"
        reasons.append(f"价格 {latest_price:.2f} 接近观察区 {levels.observe[0]:.2f}-{levels.observe[1]:.2f}。")
    elif levels.breakout is not None and latest_price >= levels.breakout and (volume_ratio or 0) >= 1.2:
        status = "breakout_confirm"
        reasons.append(f"价格突破 {levels.breakout:.2f} 且量能达到近5日均量的 {volume_ratio:.2f} 倍。")
    elif (return_5d is not None and return_5d > 0.15) or (return_20d is not None and return_20d > 0.35):
        status = "hot_wait"
        reasons.append("近期涨幅过大，优先等待回踩或缩量企稳。")
    else:
        reasons.append("未触发明确买点或风险条件。")

    if daily_change_pct is not None:
        reasons.append(f"当日涨跌幅 {daily_change_pct:.2f}%。")
    if return_5d is not None:
        reasons.append(f"近5日涨幅 {return_5d * 100:.2f}%。")
    if return_20d is not None:
        reasons.append(f"近20日涨幅 {return_20d * 100:.2f}%。")

    return WatchlistStockAnalysis(
        symbol=stock.symbol,
        name=stock.name,
        theme=stock.theme,
        notes=stock.notes,
        latest_price=round(float(latest_price), 4),
        daily_change_pct=daily_change_pct,
        return_5d=return_5d,
        return_20d=return_20d,
        ma5=ma5,
        ma20=ma20,
        volume_ratio=volume_ratio,
        status=status,
        reasons=reasons,
        levels=levels,
        data_status=data_status,
    )


def summarize_statuses(items: list[WatchlistStockAnalysis]) -> dict[str, int]:
    summary = {status: 0 for status in ["entry_zone", "add_zone", "watch_pullback", "hot_wait", "breakout_confirm", "risk_off", "neutral"]}
    for item in items:
        summary[item.status] = summary.get(item.status, 0) + 1
    return summary


def build_watchlist_report(
    config: WatchlistConfig,
    *,
    trade_date: date,
    quote_lookup,
    bars_lookup,
) -> WatchlistReport:
    items: list[WatchlistStockAnalysis] = []
    for stock in config.stocks:
        quote = quote_lookup(stock.symbol) or {}
        bars = bars_lookup(stock.symbol)
        metrics = compute_stock_metrics(bars) if bars is not None else compute_stock_metrics(pd.DataFrame())
        items.append(
            classify_watchlist_stock(
                stock,
                latest_price=quote.get("latest_price"),
                daily_change_pct=quote.get("daily_change_pct"),
                return_5d=metrics.get("return_5d"),
                return_20d=metrics.get("return_20d"),
                ma5=metrics.get("ma5"),
                ma20=metrics.get("ma20"),
                volume_ratio=metrics.get("volume_ratio"),
                data_status=quote.get("data_status", "ok"),
            )
        )
    return WatchlistReport(trade_date=trade_date.isoformat(), items=items)


def _range(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{name} must contain exactly two values")
    low, high = float(value[0]), float(value[1])
    return (min(low, high), max(low, high))


def _period_return(values: pd.Series, periods: int) -> float | None:
    if len(values) <= periods:
        return None
    base = float(values.iloc[-periods - 1])
    if base == 0:
        return None
    return round(float(values.iloc[-1]) / base - 1, 6)


def _mean_tail(values: pd.Series, window: int) -> float | None:
    if len(values) < window:
        return None
    return round(float(values.tail(window).mean()), 6)


def _volume_ratio(values: pd.Series, window: int) -> float | None:
    if len(values) <= window:
        return None
    recent_average = float(values.iloc[-window - 1:-1].mean())
    if recent_average == 0:
        return None
    return round(float(values.iloc[-1]) / recent_average, 6)


def _inside(price: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= price <= bounds[1]
```

- [ ] **Step 5: Run core tests**

Run: `pytest tests/test_monitoring/test_watchlist.py -q`

Expected: all tests pass.

## Task 2: Backend API Adapter

**Files:**
- Create: `src/web/backend/watchlist_monitor.py`
- Modify: `src/web/backend/app.py`
- Create: `tests/test_web/test_watchlist_monitor_api.py`

- [ ] **Step 1: Write failing API test**

Create `tests/test_web/test_watchlist_monitor_api.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_watchlist_monitor_report_api_returns_items(tmp_path) -> None:
    def fake_runner(trade_date: date | None = None) -> dict[str, Any]:
        return {
            "trade_date": (trade_date or date(2026, 6, 17)).isoformat(),
            "summary": {"entry_zone": 1, "hot_wait": 1},
            "items": [
                {
                    "symbol": "601899",
                    "name": "紫金矿业",
                    "theme": "金铜资源",
                    "notes": "关注金铜。",
                    "latest_price": 29.7,
                    "daily_change_pct": -1.2,
                    "return_5d": -0.03,
                    "return_20d": -0.1,
                    "ma5": 30.1,
                    "ma20": 31.2,
                    "volume_ratio": 1.1,
                    "status": "entry_zone",
                    "reasons": ["价格进入试仓区。"],
                    "levels": {
                        "observe": [30.0, 30.5],
                        "entry": [29.5, 29.8],
                        "add": [28.5, 29.0],
                        "invalid": 27.0,
                        "breakout": 32.0,
                    },
                    "data_status": "ok",
                }
            ],
        }

    app = create_app(db_path=tmp_path / "jobs.sqlite3", watchlist_monitor_runner=fake_runner)
    client = TestClient(app)

    response = client.get("/api/watchlist-monitor/report?trade_date=2026-06-17")

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "2026-06-17"
    assert payload["items"][0]["symbol"] == "601899"
    assert payload["items"][0]["status"] == "entry_zone"
```

- [ ] **Step 2: Run API test and verify it fails**

Run: `pytest tests/test_web/test_watchlist_monitor_api.py -q`

Expected: fails because `create_app` does not accept `watchlist_monitor_runner`.

- [ ] **Step 3: Implement API adapter**

Create `src/web/backend/watchlist_monitor.py` with:

```python
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.monitoring.watchlist import build_watchlist_report, load_watchlist_config


DEFAULT_WATCHLIST_CONFIG = Path("config/watchlist_monitor.yaml")


def get_watchlist_report(
    trade_date: date | None = None,
    *,
    config_path: str | Path = DEFAULT_WATCHLIST_CONFIG,
    aggregator: DataAggregator | None = None,
) -> dict[str, Any]:
    end = trade_date or date.today()
    source = aggregator or DataAggregator()
    config = load_watchlist_config(config_path)

    def quote_lookup(symbol: str) -> dict[str, Any]:
        normalized = format_symbol(symbol)
        start = end - timedelta(days=90)
        bars = source.get_bars(normalized, start, end, "daily")
        if bars is None or bars.empty:
            return {"latest_price": None, "daily_change_pct": None, "data_status": "quote_unavailable"}
        df = bars.copy().sort_values("date")
        closes = pd.to_numeric(df["close"], errors="coerce").dropna()
        if closes.empty:
            return {"latest_price": None, "daily_change_pct": None, "data_status": "quote_unavailable"}
        latest = float(closes.iloc[-1])
        previous = float(closes.iloc[-2]) if len(closes) > 1 else None
        daily_change_pct = round((latest / previous - 1) * 100, 4) if previous else None
        return {"latest_price": latest, "daily_change_pct": daily_change_pct, "data_status": "ok"}

    def bars_lookup(symbol: str):
        normalized = format_symbol(symbol)
        return source.get_bars(normalized, end - timedelta(days=120), end, "daily")

    return build_watchlist_report(
        config,
        trade_date=end,
        quote_lookup=quote_lookup,
        bars_lookup=bars_lookup,
    ).to_dict()


def get_watchlist_config(
    *,
    config_path: str | Path = DEFAULT_WATCHLIST_CONFIG,
) -> dict[str, Any]:
    config = load_watchlist_config(config_path)
    return {
        "items": [
            {
                "symbol": stock.symbol,
                "name": stock.name,
                "theme": stock.theme,
                "notes": stock.notes,
                "levels": {
                    "observe": list(stock.levels.observe),
                    "entry": list(stock.levels.entry),
                    "add": list(stock.levels.add),
                    "invalid": stock.levels.invalid,
                    "breakout": stock.levels.breakout,
                },
            }
            for stock in config.stocks
        ]
    }
```

- [ ] **Step 4: Wire routes into app**

Modify `src/web/backend/app.py`:

```python
from src.web.backend.watchlist_monitor import get_watchlist_config, get_watchlist_report
```

Add parameter to `create_app`:

```python
    watchlist_monitor_runner=get_watchlist_report,
    watchlist_config_runner=get_watchlist_config,
```

Set state:

```python
    app.state.watchlist_monitor_runner = watchlist_monitor_runner
    app.state.watchlist_config_runner = watchlist_config_runner
```

Add routes near stock trend route:

```python
    @app.get("/api/watchlist-monitor/report")
    def get_watchlist_monitor_report(trade_date: date | None = None) -> dict[str, Any]:
        return app.state.watchlist_monitor_runner(trade_date=trade_date)

    @app.get("/api/watchlist-monitor/config")
    def get_watchlist_monitor_config() -> dict[str, Any]:
        return app.state.watchlist_config_runner()
```

- [ ] **Step 5: Run API tests**

Run: `pytest tests/test_web/test_watchlist_monitor_api.py tests/test_monitoring/test_watchlist.py -q`

Expected: all tests pass.

## Task 3: Frontend API Types and Page

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/WatchlistMonitor.vue`
- Modify: `frontend/src/App.vue`
- Create: `tests/test_frontend/test_watchlist_monitor_page.py`

- [ ] **Step 1: Write failing frontend static test**

Create `tests/test_frontend/test_watchlist_monitor_page.py`:

```python
from pathlib import Path


def test_watchlist_monitor_page_contains_status_sections() -> None:
    page = Path("frontend/src/pages/WatchlistMonitor.vue").read_text(encoding="utf-8")

    assert "观察池监控" in page
    assert "试仓区" in page
    assert "等待回踩" in page
    assert "watchlist-monitor/report" in page


def test_app_registers_watchlist_monitor_page() -> None:
    app = Path("frontend/src/App.vue").read_text(encoding="utf-8")

    assert 'index="watchlist-monitor"' in app
    assert "WatchlistMonitor" in app
```

- [ ] **Step 2: Run frontend static test and verify it fails**

Run: `pytest tests/test_frontend/test_watchlist_monitor_page.py -q`

Expected: fails because the page is not created and App is not wired.

- [ ] **Step 3: Add frontend API types and helper**

Append to `frontend/src/api/client.ts`:

```ts
export type WatchlistStatus =
  | 'hot_wait'
  | 'watch_pullback'
  | 'entry_zone'
  | 'add_zone'
  | 'breakout_confirm'
  | 'risk_off'
  | 'neutral'

export interface WatchlistLevels {
  observe: number[]
  entry: number[]
  add: number[]
  invalid: number
  breakout: number | null
}

export interface WatchlistMonitorItem {
  symbol: string
  name: string
  theme: string
  notes: string
  latest_price: number | null
  daily_change_pct: number | null
  return_5d: number | null
  return_20d: number | null
  ma5: number | null
  ma20: number | null
  volume_ratio: number | null
  status: WatchlistStatus
  reasons: string[]
  levels: WatchlistLevels
  data_status: string
}

export interface WatchlistMonitorReport {
  trade_date: string
  summary: Record<string, number>
  items: WatchlistMonitorItem[]
}

export async function fetchWatchlistMonitorReport(tradeDate?: string): Promise<WatchlistMonitorReport> {
  const params = new URLSearchParams()
  if (tradeDate) params.set('trade_date', tradeDate)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  const response = await fetch(`/api/watchlist-monitor/report${suffix}`)
  if (!response.ok) throw new Error(`Failed to load watchlist monitor report: ${response.status}`)
  return response.json()
}
```

- [ ] **Step 4: Create watchlist page**

Create `frontend/src/pages/WatchlistMonitor.vue` with:

```vue
<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1>观察池监控</h1>
        <p>每日分析关注标的的买点状态、趋势强弱和触发原因。</p>
      </div>
      <el-button :loading="loading" type="primary" @click="loadReport">刷新</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon />

    <div class="summary-grid">
      <el-card v-for="card in summaryCards" :key="card.key" shadow="never">
        <div class="summary-value">{{ card.value }}</div>
        <div class="summary-label">{{ card.label }}</div>
      </el-card>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>标的状态</span>
          <el-tag effect="plain">{{ report?.trade_date || '未加载' }}</el-tag>
        </div>
      </template>
      <el-table :data="report?.items || []" stripe @row-click="selectItem">
        <el-table-column prop="symbol" label="代码" width="96" />
        <el-table-column prop="name" label="名称" width="110" />
        <el-table-column prop="theme" label="主题" min-width="160" />
        <el-table-column label="现价" width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.latest_price) }}</template>
        </el-table-column>
        <el-table-column label="日涨跌" width="100" align="right">
          <template #default="{ row }">{{ formatPctValue(row.daily_change_pct) }}</template>
        </el-table-column>
        <el-table-column label="5日" width="90" align="right">
          <template #default="{ row }">{{ formatRatio(row.return_5d) }}</template>
        </el-table-column>
        <el-table-column label="20日" width="90" align="right">
          <template #default="{ row }">{{ formatRatio(row.return_20d) }}</template>
        </el-table-column>
        <el-table-column label="量能" width="90" align="right">
          <template #default="{ row }">{{ formatTimes(row.volume_ratio) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="selected" shadow="never" class="detail-card">
      <template #header>
        <div class="card-header">
          <span>{{ selected.name }} 分析</span>
          <el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag>
        </div>
      </template>
      <div class="detail-grid">
        <div>
          <h3>买点区间</h3>
          <p>观察区：{{ levelText(selected.levels.observe) }}</p>
          <p>试仓区：{{ levelText(selected.levels.entry) }}</p>
          <p>加仓区：{{ levelText(selected.levels.add) }}</p>
          <p>失效位：{{ formatNumber(selected.levels.invalid) }}</p>
          <p>突破位：{{ formatNumber(selected.levels.breakout) }}</p>
        </div>
        <div>
          <h3>触发原因</h3>
          <ul>
            <li v-for="reason in selected.reasons" :key="reason">{{ reason }}</li>
          </ul>
          <p class="notes">{{ selected.notes }}</p>
        </div>
      </div>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchWatchlistMonitorReport, type WatchlistMonitorItem, type WatchlistMonitorReport, type WatchlistStatus } from '../api/client'

const report = ref<WatchlistMonitorReport | null>(null)
const selected = ref<WatchlistMonitorItem | null>(null)
const loading = ref(false)
const error = ref('')

const summaryCards = computed(() => {
  const summary = report.value?.summary || {}
  return [
    { key: 'entry_zone', label: '进入试仓区', value: summary.entry_zone || 0 },
    { key: 'watch_pullback', label: '等待回踩', value: summary.watch_pullback || 0 },
    { key: 'hot_wait', label: '短线过热', value: summary.hot_wait || 0 },
    { key: 'risk_off', label: '风险回避', value: summary.risk_off || 0 },
  ]
})

async function loadReport() {
  loading.value = true
  error.value = ''
  try {
    report.value = await fetchWatchlistMonitorReport()
    selected.value = report.value.items[0] || null
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载观察池报告失败'
  } finally {
    loading.value = false
  }
}

function selectItem(row: WatchlistMonitorItem) {
  selected.value = row
}

function statusLabel(status: WatchlistStatus) {
  return {
    hot_wait: '等待回踩',
    watch_pullback: '接近观察',
    entry_zone: '试仓区',
    add_zone: '加仓区',
    breakout_confirm: '突破确认',
    risk_off: '风险回避',
    neutral: '中性',
  }[status]
}

function statusType(status: WatchlistStatus) {
  if (status === 'entry_zone' || status === 'add_zone') return 'success'
  if (status === 'watch_pullback' || status === 'breakout_confirm') return 'warning'
  if (status === 'risk_off') return 'danger'
  return 'info'
}

function formatNumber(value: number | null) {
  return value === null || value === undefined ? 'n/a' : value.toFixed(2)
}

function formatRatio(value: number | null) {
  return value === null || value === undefined ? 'n/a' : `${(value * 100).toFixed(2)}%`
}

function formatPctValue(value: number | null) {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(2)}%`
}

function formatTimes(value: number | null) {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(2)}x`
}

function levelText(values: number[]) {
  return `${formatNumber(values[0])}-${formatNumber(values[1])}`
}

onMounted(loadReport)
</script>

<style scoped>
.page {
  display: grid;
  gap: 16px;
}

.page-header,
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.page-header h1 {
  margin: 0 0 6px;
  font-size: 22px;
}

.page-header p,
.notes {
  margin: 0;
  color: #667085;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
}

.summary-label {
  margin-top: 4px;
  color: #667085;
}

.detail-card {
  margin-top: 2px;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(220px, 320px) 1fr;
  gap: 24px;
}

.detail-grid h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.detail-grid p {
  margin: 6px 0;
}

.detail-grid ul {
  margin: 0 0 12px;
  padding-left: 18px;
}
</style>
```

- [ ] **Step 5: Wire page into app**

Modify `frontend/src/App.vue`:

```vue
<el-menu-item index="watchlist-monitor">观察池监控</el-menu-item>
```

Add import:

```ts
import WatchlistMonitor from './pages/WatchlistMonitor.vue'
```

Add route branch:

```vue
<WatchlistMonitor v-else-if="activePage === 'watchlist-monitor'" />
```

- [ ] **Step 6: Run frontend static test**

Run: `pytest tests/test_frontend/test_watchlist_monitor_page.py -q`

Expected: all tests pass.

## Task 4: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
pytest tests/test_monitoring/test_watchlist.py tests/test_web/test_watchlist_monitor_api.py tests/test_frontend/test_watchlist_monitor_page.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Run API smoke test**

Run:

```bash
python - <<'PY'
from src.web.backend.watchlist_monitor import get_watchlist_report
report = get_watchlist_report()
print(report["trade_date"], len(report["items"]))
print([item["symbol"] for item in report["items"]])
PY
```

Expected: prints a date, `7`, and the configured symbols.

- [ ] **Step 4: Review git diff**

Run: `git diff -- config/watchlist_monitor.yaml src/monitoring/watchlist.py src/web/backend/watchlist_monitor.py src/web/backend/app.py frontend/src/api/client.ts frontend/src/pages/WatchlistMonitor.vue frontend/src/App.vue tests/test_monitoring/test_watchlist.py tests/test_web/test_watchlist_monitor_api.py tests/test_frontend/test_watchlist_monitor_page.py`

Expected: diff only contains watchlist monitor changes.

