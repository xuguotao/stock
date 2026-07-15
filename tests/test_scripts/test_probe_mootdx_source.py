from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.probe_mootdx_source import ProbeTask, build_summary, run_probe_task


class FakeProbeSource:
    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        return pd.DataFrame([{"symbol": symbols[0], "price": 10.0}])

    def fetch_intraday_bars(self, symbol: str, trade_date, frequency: str) -> pd.DataFrame:
        if frequency == "bad":
            return pd.DataFrame()
        return pd.DataFrame([
            {"datetime": pd.Timestamp("2026-07-09 14:30"), "close": 10.0},
            {"datetime": pd.Timestamp("2026-07-09 14:35"), "close": 10.1},
        ])

    def fetch_stock_list(self):
        return [object(), object()]

    def fetch_bars(self, symbol: str, start, end, frequency: str) -> pd.DataFrame:
        return pd.DataFrame([{"date": start, "close": 10.0}])

    def fetch_xdxr(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame([{"category": 1}])


class FailingProbeSource(FakeProbeSource):
    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        raise ValueError("network down")


def test_run_probe_task_records_success_metadata() -> None:
    task = ProbeTask(data_type="intraday_bars", symbol="000001.SZ", frequency="5m", sleep_seconds=0.2, round_index=1)

    result = run_probe_task(FakeProbeSource(), task)

    assert result["data_type"] == "intraday_bars"
    assert result["symbol"] == "000001.SZ"
    assert result["frequency"] == "5m"
    assert result["success"] is True
    assert result["row_count"] == 2
    assert result["latest_datetime"] == "2026-07-09 14:35:00"
    assert result["latency_ms"] >= 0
    assert result["error"] == ""


def test_run_probe_task_serializes_daily_date_metadata() -> None:
    task = ProbeTask(data_type="daily_bars", symbol="000001.SZ", frequency="daily", sleep_seconds=0.0, round_index=1)

    result = run_probe_task(FakeProbeSource(), task, trade_date=date(2026, 7, 9))

    assert result["success"] is True
    assert result["first_datetime"] == "2026-07-09"
    assert result["latest_datetime"] == "2026-07-09"


def test_run_probe_task_records_empty_and_error_results() -> None:
    empty = run_probe_task(
        FakeProbeSource(),
        ProbeTask(data_type="intraday_bars", symbol="000001.SZ", frequency="bad", sleep_seconds=0.0, round_index=1),
    )
    error = run_probe_task(
        FailingProbeSource(),
        ProbeTask(data_type="realtime_quotes", symbol="000001.SZ", frequency="", sleep_seconds=0.0, round_index=1),
    )

    assert empty["success"] is False
    assert empty["error"] == "empty_result"
    assert error["success"] is False
    assert "network down" in error["error"]


def test_build_summary_recommends_lowest_successful_sleep_per_frequency() -> None:
    results = [
        {"data_type": "intraday_bars", "frequency": "5m", "sleep_seconds": 0.0, "success": False, "latency_ms": 100, "row_count": 0},
        {"data_type": "intraday_bars", "frequency": "5m", "sleep_seconds": 0.2, "success": True, "latency_ms": 300, "row_count": 48},
        {"data_type": "intraday_bars", "frequency": "5m", "sleep_seconds": 0.2, "success": True, "latency_ms": 500, "row_count": 48},
        {"data_type": "intraday_bars", "frequency": "1m", "sleep_seconds": 0.5, "success": True, "latency_ms": 700, "row_count": 240},
    ]

    summary = build_summary(results, min_success_rate=1.0)

    assert summary["total_tasks"] == 4
    assert summary["by_data_type"]["intraday_bars"]["success_rate"] == 0.75
    assert summary["recommendations"]["intraday_bars:5m"]["sleep_seconds"] == 0.2
    assert summary["recommendations"]["intraday_bars:5m"]["success_rate"] == 1.0
    assert summary["recommendations"]["intraday_bars:1m"]["sleep_seconds"] == 0.5
