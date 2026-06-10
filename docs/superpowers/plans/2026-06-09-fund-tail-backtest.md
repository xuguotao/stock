# Fund Tail Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested research script that backtests the fund tail-session advice rules using proxy signal data and fund NAV return data.

**Architecture:** Add a small research module under `src/research/fund_tail_backtest.py` for pure, testable calculations. Add `scripts/backtest_fund_tail_advice.py` as the CLI wrapper that reads CSV files, runs the engine, prints a table, and writes a report. Tests cover signal classification and forward-return summary logic with deterministic sample data.

**Tech Stack:** Python 3.12, pandas, pytest, existing project layout.

---

## File Structure

- Create `src/research/fund_tail_backtest.py`: pure functions and dataclasses for loading series, classifying signals, computing forward returns, and summarizing results.
- Create `scripts/backtest_fund_tail_advice.py`: CLI entrypoint for CSV inputs and report output.
- Create `tests/test_research/test_fund_tail_backtest.py`: focused unit tests for rule behavior and metrics.

## Task 1: Signal Classification

**Files:**
- Create: `src/research/fund_tail_backtest.py`
- Test: `tests/test_research/test_fund_tail_backtest.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd

from src.research.fund_tail_backtest import classify_tail_signals


def test_classifies_add_when_trend_positive_and_not_overextended():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    proxy = pd.DataFrame(
        {
            "date": dates,
            "close": [100, 101, 102, 103, 104, 105, 106, 106.8],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": dates,
            "close": [100, 100.5, 101, 101.5, 102, 102.4, 102.8, 103.0],
        }
    )

    signals = classify_tail_signals(proxy, benchmark=benchmark, lookback=5)

    assert signals.iloc[-1]["signal"] == "add"
    assert signals.iloc[-1]["reason"] == "trend_positive_relative_strength"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research/test_fund_tail_backtest.py::test_classifies_add_when_trend_positive_and_not_overextended -v`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` because `src.research.fund_tail_backtest` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/research/fund_tail_backtest.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SignalConfig:
    pullback_floor: float = -0.03
    chase_limit: float = 0.025
    weak_day_limit: float = -0.01
    relative_strength_margin: float = 0.0


def _prepare_series(df: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["close"])
    return out.reset_index(drop=True)


def classify_tail_signals(
    proxy: pd.DataFrame,
    *,
    benchmark: pd.DataFrame | None = None,
    lookback: int = 5,
    config: SignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or SignalConfig()
    px = _prepare_series(proxy)
    px["daily_return"] = px["close"].pct_change()
    px["ma"] = px["close"].rolling(lookback, min_periods=lookback).mean()
    px["lookback_return"] = px["close"].pct_change(lookback - 1)

    if benchmark is not None:
        bm = _prepare_series(benchmark)[["date", "close"]].rename(columns={"close": "benchmark_close"})
        px = px.merge(bm, on="date", how="left")
        px["benchmark_return"] = px["benchmark_close"].pct_change(lookback - 1)
    else:
        px["benchmark_return"] = 0.0

    signals = []
    reasons = []
    for row in px.itertuples(index=False):
        daily = row.daily_return
        ma = row.ma
        lb_ret = row.lookback_return
        bm_ret = row.benchmark_return
        if pd.isna(daily) or pd.isna(ma) or pd.isna(lb_ret):
            signals.append("watch")
            reasons.append("insufficient_history")
        elif daily > cfg.chase_limit:
            signals.append("watch")
            reasons.append("overextended_do_not_chase")
        elif daily < cfg.pullback_floor:
            signals.append("avoid")
            reasons.append("sharp_selloff")
        elif daily < cfg.weak_day_limit and row.close < ma:
            signals.append("avoid")
            reasons.append("weak_below_trend")
        elif row.close >= ma and lb_ret >= bm_ret + cfg.relative_strength_margin:
            signals.append("add")
            reasons.append("trend_positive_relative_strength")
        else:
            signals.append("watch")
            reasons.append("mixed_signal")

    px["signal"] = signals
    px["reason"] = reasons
    return px[["date", "close", "daily_return", "lookback_return", "benchmark_return", "signal", "reason"]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_research/test_fund_tail_backtest.py::test_classifies_add_when_trend_positive_and_not_overextended -v`

Expected: PASS.

## Task 2: Forward Return Evaluation

**Files:**
- Modify: `src/research/fund_tail_backtest.py`
- Modify: `tests/test_research/test_fund_tail_backtest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research/test_fund_tail_backtest.py`:

```python
from src.research.fund_tail_backtest import evaluate_forward_returns


def test_evaluates_forward_returns_only_on_add_signals():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    signals = pd.DataFrame(
        {
            "date": dates,
            "signal": ["watch", "add", "avoid", "add", "watch", "watch"],
        }
    )
    nav = pd.DataFrame(
        {
            "date": dates,
            "close": [1.00, 1.00, 1.02, 1.01, 1.03, 1.04],
        }
    )

    result = evaluate_forward_returns(signals, nav, horizons=(1, 2))

    assert result.loc[1, "count"] == 2
    assert round(result.loc[1, "avg_return"], 4) == 0.0199
    assert round(result.loc[1, "win_rate"], 4) == 1.0
    assert round(result.loc[2, "avg_return"], 4) == 0.0299
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research/test_fund_tail_backtest.py::test_evaluates_forward_returns_only_on_add_signals -v`

Expected: FAIL with `ImportError` for `evaluate_forward_returns`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/research/fund_tail_backtest.py`:

```python
def evaluate_forward_returns(
    signals: pd.DataFrame,
    nav: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    signal_name: str = "add",
) -> pd.DataFrame:
    if "date" not in signals or "signal" not in signals:
        raise ValueError("signals must contain date and signal columns")
    nav_px = _prepare_series(nav)[["date", "close"]].rename(columns={"close": "nav_close"})
    events = signals.copy()
    events["date"] = pd.to_datetime(events["date"])
    events = events.merge(nav_px, on="date", how="inner")
    events = events[events["signal"] == signal_name].copy()

    rows = []
    nav_px = nav_px.reset_index(drop=True)
    date_to_pos = {d: i for i, d in enumerate(nav_px["date"])}
    for horizon in horizons:
        forward = []
        for event in events.itertuples(index=False):
            pos = date_to_pos.get(event.date)
            if pos is None:
                continue
            target = pos + horizon
            if target >= len(nav_px):
                continue
            start = float(event.nav_close)
            end = float(nav_px.iloc[target]["nav_close"])
            if start > 0:
                forward.append(end / start - 1)
        series = pd.Series(forward, dtype="float64")
        rows.append(
            {
                "horizon": horizon,
                "count": int(series.count()),
                "avg_return": float(series.mean()) if not series.empty else 0.0,
                "win_rate": float((series > 0).mean()) if not series.empty else 0.0,
                "worst_return": float(series.min()) if not series.empty else 0.0,
            }
        )

    return pd.DataFrame(rows).set_index("horizon")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_research/test_fund_tail_backtest.py::test_evaluates_forward_returns_only_on_add_signals -v`

Expected: PASS.

## Task 3: CLI Script

**Files:**
- Create: `scripts/backtest_fund_tail_advice.py`
- Modify: `tests/test_research/test_fund_tail_backtest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research/test_fund_tail_backtest.py`:

```python
from src.research.fund_tail_backtest import summarize_latest_signal


def test_summarizes_latest_signal_with_metrics():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "signal": ["watch", "add"],
            "reason": ["mixed_signal", "trend_positive_relative_strength"],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [1],
            "count": [3],
            "avg_return": [0.0123],
            "win_rate": [0.6667],
            "worst_return": [-0.01],
        }
    ).set_index("horizon")

    row = summarize_latest_signal("华夏中证500指数增强C", "007995", signals, metrics)

    assert row["fund_name"] == "华夏中证500指数增强C"
    assert row["latest_signal"] == "add"
    assert row["latest_reason"] == "trend_positive_relative_strength"
    assert row["h1_avg_return"] == 0.0123
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research/test_fund_tail_backtest.py::test_summarizes_latest_signal_with_metrics -v`

Expected: FAIL with `ImportError` for `summarize_latest_signal`.

- [ ] **Step 3: Implement summary helper**

Append to `src/research/fund_tail_backtest.py`:

```python
def summarize_latest_signal(
    fund_name: str,
    fund_code: str,
    signals: pd.DataFrame,
    metrics: pd.DataFrame,
) -> dict[str, object]:
    if signals.empty:
        raise ValueError("signals cannot be empty")
    latest = signals.sort_values("date").iloc[-1]
    row: dict[str, object] = {
        "fund_name": fund_name,
        "fund_code": fund_code,
        "latest_date": latest["date"],
        "latest_signal": latest["signal"],
        "latest_reason": latest["reason"],
    }
    for horizon, metric in metrics.iterrows():
        prefix = f"h{horizon}"
        row[f"{prefix}_count"] = int(metric["count"])
        row[f"{prefix}_avg_return"] = float(metric["avg_return"])
        row[f"{prefix}_win_rate"] = float(metric["win_rate"])
        row[f"{prefix}_worst_return"] = float(metric["worst_return"])
    return row
```

- [ ] **Step 4: Create CLI wrapper**

Create `scripts/backtest_fund_tail_advice.py`:

```python
#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.research.fund_tail_backtest import (
    classify_tail_signals,
    evaluate_forward_returns,
    summarize_latest_signal,
)


FUNDS = {
    "001632": "天弘中证食品饮料ETF联接C",
    "017437": "华宝纳斯达克精选股票(QDII)C",
    "007995": "华夏中证500指数增强C",
    "005827": "易方达蓝筹精选混合",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest fund tail-session advice rules.")
    parser.add_argument("--data-dir", default="data/fund_tail", help="Directory containing CSV files.")
    parser.add_argument("--report", default="reports/fund_tail_backtest.csv", help="Output CSV report path.")
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing input file: {path}")
    return pd.read_csv(path)


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    rows = []
    for code, name in FUNDS.items():
        proxy = read_csv(data_dir / f"{code}_proxy.csv")
        nav_path = data_dir / f"{code}_nav.csv"
        nav = read_csv(nav_path) if nav_path.exists() else proxy
        benchmark_path = data_dir / "benchmark.csv"
        benchmark = read_csv(benchmark_path) if benchmark_path.exists() else None

        signals = classify_tail_signals(proxy, benchmark=benchmark)
        metrics = evaluate_forward_returns(signals, nav)
        rows.append(summarize_latest_signal(name, code, signals, metrics))

    report = pd.DataFrame(rows)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(report_path, index=False)
    print(report.to_string(index=False))
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research/test_fund_tail_backtest.py -v`

Expected: PASS.

## Task 4: Final Verification

**Files:**
- Verify: `src/research/fund_tail_backtest.py`
- Verify: `scripts/backtest_fund_tail_advice.py`
- Verify: `tests/test_research/test_fund_tail_backtest.py`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_research/test_fund_tail_backtest.py -v`

Expected: all tests pass.

- [ ] **Step 2: Run broader research tests**

Run: `pytest tests/test_research -v`

Expected: all research tests pass.

- [ ] **Step 3: Show usage**

Run: `python scripts/backtest_fund_tail_advice.py --help`

Expected: help text shows `--data-dir` and `--report`.

## Self-Review

- Spec coverage: The plan implements CSV-based signal generation, fund/proxy evaluation, latest-signal summary, and a CSV report.
- Placeholder scan: No task relies on unresolved placeholders.
- Type consistency: Function names and return shapes are consistent across tests, implementation, and CLI.
