from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pandas as pd

from src.monitoring.zijin import (
    ProductionInput,
    MonitorSnapshot,
    evaluate_production,
    evaluate_trend,
    render_markdown_report,
)


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
            "close": closes,
        }
    )


def test_evaluate_trend_marks_series_above_short_and_long_averages_as_strong() -> None:
    result = evaluate_trend("gold", _bars([100.0] * 60 + [120.0] * 5))

    assert result.status == "strong"
    assert result.latest_close == 120.0
    assert result.short_ma is not None
    assert result.long_ma is not None
    assert "above both" in result.reason


def test_evaluate_trend_marks_series_below_long_average_as_weak() -> None:
    result = evaluate_trend("copper", _bars([120.0] * 60 + [80.0] * 5))

    assert result.status == "weak"
    assert result.latest_close == 80.0
    assert "below 60-day" in result.reason


def test_evaluate_production_marks_materially_slow_progress_as_behind() -> None:
    result = evaluate_production(
        [
            ProductionInput(
                name="mined copper",
                annual_target=120.0,
                actual_ytd=18.0,
                unit="10k tonnes",
            )
        ],
        elapsed_ratio=0.25,
    )

    assert result[0].status == "behind"
    assert result[0].actual_ratio == 0.15
    assert result[0].expected_ratio == 0.25


def test_render_markdown_report_includes_monitor_sections() -> None:
    gold = evaluate_trend("gold", _bars([100.0] * 65))
    copper = evaluate_trend("copper", _bars([100.0] * 65))
    zijin = evaluate_trend("zijin", _bars([20.0] * 65))
    production = evaluate_production(
        [ProductionInput("mined gold", 105.0, 23.5, "tonnes")],
        elapsed_ratio=0.25,
    )
    snapshot = MonitorSnapshot(
        date="2026-06-08",
        stock_symbol="601899.SH",
        stock_price=28.13,
        stock_change_pct=-5.1,
        trends=[zijin, gold, copper],
        production=production,
    )

    report = render_markdown_report(snapshot)

    assert "# Zijin Mining Monitor - 2026-06-08" in report
    assert "## Price And Commodity Trends" in report
    assert "## Production Delivery" in report
    assert "## Triggers" in report


def test_monitor_script_can_be_invoked_from_project_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/monitor_zijin.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Generate a local Zijin Mining monitoring report" in result.stdout


def test_load_commodity_bars_uses_akshare_futures_when_csv_is_missing(monkeypatch) -> None:
    from scripts import monitor_zijin

    calls: list[str] = []

    def fake_futures_zh_daily_sina(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return pd.DataFrame({"date": ["2026-06-05"], "close": [105150.0]})

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(futures_zh_daily_sina=fake_futures_zh_daily_sina),
    )

    df = monitor_zijin._load_commodity_bars("copper", "missing.csv")

    assert calls == ["CU0"]
    assert df["close"].tolist() == [105150.0]
