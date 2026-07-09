#!/usr/bin/env python3
"""Probe mootdx data availability, latency, and practical request spacing."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.mootdx_source import MootdxSource  # noqa: E402


@dataclass(frozen=True)
class ProbeTask:
    data_type: str
    symbol: str = ""
    frequency: str = ""
    sleep_seconds: float = 0.0
    round_index: int = 1


def run_probe_task(source: Any, task: ProbeTask, *, trade_date: date | None = None) -> dict[str, Any]:
    if task.sleep_seconds > 0:
        time.sleep(task.sleep_seconds)
    started = time.perf_counter()
    try:
        payload = _run_task_payload(source, task, trade_date or date.today())
        latency_ms = (time.perf_counter() - started) * 1000
        record = {
            **asdict(task),
            "success": _row_count(payload) > 0,
            "row_count": _row_count(payload),
            "columns": _columns(payload),
            "first_datetime": _first_datetime(payload),
            "latest_datetime": _latest_datetime(payload),
            "latency_ms": round(latency_ms, 3),
            "error": "",
        }
        if not record["success"]:
            record["error"] = "empty_result"
        return record
    except Exception as exc:  # noqa: BLE001 - probe records failures instead of stopping.
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            **asdict(task),
            "success": False,
            "row_count": 0,
            "columns": [],
            "first_datetime": "",
            "latest_datetime": "",
            "latency_ms": round(latency_ms, 3),
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


def build_summary(results: list[dict[str, Any]], *, min_success_rate: float = 0.95) -> dict[str, Any]:
    return {
        "total_tasks": len(results),
        "success_count": sum(1 for item in results if item.get("success")),
        "by_data_type": _group_stats(results, ["data_type"]),
        "by_data_type_frequency": _group_stats(results, ["data_type", "frequency"]),
        "recommendations": _recommendations(results, min_success_rate=min_success_rate),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="000001.SZ,600519.SH,300750.SZ", help="Comma-separated symbols")
    parser.add_argument("--frequencies", default="1m,5m,15m,30m,60m,daily", help="Comma-separated K-line frequencies")
    parser.add_argument("--rounds", type=int, default=2, help="Probe rounds per task")
    parser.add_argument("--sleep-grid", default="0,0.2,0.5", help="Comma-separated sleep seconds before each request")
    parser.add_argument("--trade-date", default=date.today().isoformat(), help="Trade date for intraday/minutes probes")
    parser.add_argument("--output-dir", default="reports/mootdx_probe", help="Directory for latest.json/latest.csv")
    parser.add_argument("--bestip", action="store_true", help="Ask mootdx to retest the fastest quote server")
    parser.add_argument("--server", default="", help="Pinned quote server, for example 202.108.253.131:7709")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--include-heavy", action="store_true", help="Also probe F10 and finance-like endpoints")
    args = parser.parse_args(argv)

    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    frequencies = [item.strip() for item in args.frequencies.split(",") if item.strip()]
    sleep_grid = [float(item) for item in args.sleep_grid.split(",") if item.strip()]
    trade_date = date.fromisoformat(args.trade_date)
    source = MootdxSource(bestip=args.bestip, server=_parse_server(args.server), timeout=args.timeout)
    tasks = build_tasks(
        symbols=symbols,
        frequencies=frequencies,
        sleep_grid=sleep_grid,
        rounds=max(1, args.rounds),
        include_heavy=args.include_heavy,
    )

    results = []
    for index, task in enumerate(tasks, start=1):
        result = run_probe_task(source, task, trade_date=trade_date)
        results.append(result)
        status = "ok" if result["success"] else "fail"
        print(
            f"[{index}/{len(tasks)}] {status} {task.data_type} {task.symbol or '-'} "
            f"{task.frequency or '-'} sleep={task.sleep_seconds}s rows={result['row_count']} "
            f"latency={result['latency_ms']:.1f}ms {result['error']}"
        )

    summary = build_summary(results)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "latest.json", {"results": results, "summary": summary})
    _write_csv(output_dir / "latest.csv", results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_tasks(
    *,
    symbols: list[str],
    frequencies: list[str],
    sleep_grid: list[float],
    rounds: int,
    include_heavy: bool,
) -> list[ProbeTask]:
    tasks: list[ProbeTask] = []
    for round_index in range(1, rounds + 1):
        for sleep_seconds in sleep_grid:
            tasks.append(ProbeTask("stock_list", sleep_seconds=sleep_seconds, round_index=round_index))
            for symbol in symbols:
                tasks.append(ProbeTask("realtime_quotes", symbol=symbol, sleep_seconds=sleep_seconds, round_index=round_index))
                tasks.append(ProbeTask("minutes", symbol=symbol, sleep_seconds=sleep_seconds, round_index=round_index))
                tasks.append(ProbeTask("realtime_minute", symbol=symbol, sleep_seconds=sleep_seconds, round_index=round_index))
                tasks.append(ProbeTask("transaction", symbol=symbol, sleep_seconds=sleep_seconds, round_index=round_index))
                tasks.append(ProbeTask("xdxr", symbol=symbol, sleep_seconds=sleep_seconds, round_index=round_index))
                if include_heavy:
                    tasks.append(ProbeTask("finance", symbol=symbol, sleep_seconds=sleep_seconds, round_index=round_index))
                for frequency in frequencies:
                    data_type = "daily_bars" if frequency in {"daily", "day"} else "intraday_bars"
                    tasks.append(ProbeTask(data_type, symbol=symbol, frequency=frequency, sleep_seconds=sleep_seconds, round_index=round_index))
            for frequency in frequencies:
                if frequency in {"daily", "day", "5m", "15m", "30m", "60m"}:
                    tasks.append(ProbeTask("index_bars", symbol="000001.SH", frequency=frequency, sleep_seconds=sleep_seconds, round_index=round_index))
    return tasks


def _run_task_payload(source: Any, task: ProbeTask, trade_date: date) -> Any:
    if task.data_type == "stock_list":
        return source.fetch_stock_list()
    if task.data_type == "realtime_quotes":
        return source.fetch_realtime_quotes([task.symbol])
    if task.data_type == "daily_bars":
        return source.fetch_bars(task.symbol, trade_date, trade_date, "daily")
    if task.data_type == "intraday_bars":
        return source.fetch_intraday_bars(task.symbol, trade_date, task.frequency)
    if task.data_type == "minutes":
        return source.fetch_minutes(task.symbol, trade_date)
    if task.data_type == "realtime_minute":
        return source.fetch_realtime_minute(task.symbol)
    if task.data_type == "transaction":
        return source.fetch_transactions(task.symbol, trade_date=None, offset=80)
    if task.data_type == "xdxr":
        return source.fetch_xdxr(task.symbol)
    if task.data_type == "finance":
        return source.fetch_finance_frame(task.symbol)
    if task.data_type == "index_bars":
        return source.fetch_index_bars(task.symbol, task.frequency)
    raise ValueError(f"unknown probe data_type: {task.data_type}")


def _group_stats(results: list[dict[str, Any]], keys: list[str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        key = ":".join(str(item.get(part) or "-") for part in keys)
        groups.setdefault(key, []).append(item)
    return {key: _stats(values) for key, values in sorted(groups.items())}


def _stats(values: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item["latency_ms"]) for item in values if item.get("success")]
    row_counts = [int(item.get("row_count") or 0) for item in values]
    return {
        "tasks": len(values),
        "success": sum(1 for item in values if item.get("success")),
        "success_rate": sum(1 for item in values if item.get("success")) / len(values) if values else 0.0,
        "empty_or_error": sum(1 for item in values if not item.get("success")),
        "avg_rows": sum(row_counts) / len(row_counts) if row_counts else 0.0,
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
    }


def _recommendations(results: list[dict[str, Any]], *, min_success_rate: float) -> dict[str, dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        if item.get("data_type") not in {"realtime_quotes", "daily_bars", "intraday_bars", "minutes", "realtime_minute", "transaction"}:
            continue
        key = f"{item.get('data_type')}:{item.get('frequency') or '-'}"
        candidates.setdefault(key, []).append(item)

    recommended: dict[str, dict[str, Any]] = {}
    for key, values in sorted(candidates.items()):
        by_sleep: dict[float, list[dict[str, Any]]] = {}
        for item in values:
            by_sleep.setdefault(float(item.get("sleep_seconds") or 0.0), []).append(item)
        for sleep_seconds in sorted(by_sleep):
            stats = _stats(by_sleep[sleep_seconds])
            if stats["success_rate"] >= min_success_rate and stats["avg_rows"] > 0:
                recommended[key] = {"sleep_seconds": sleep_seconds, **stats}
                break
    return recommended


def _row_count(payload: Any) -> int:
    if isinstance(payload, pd.DataFrame):
        return int(len(payload))
    if isinstance(payload, list):
        return len(payload)
    return 0


def _columns(payload: Any) -> list[str]:
    if isinstance(payload, pd.DataFrame):
        return [str(item) for item in payload.columns]
    return []


def _first_datetime(payload: Any) -> str:
    return _datetime_value(payload, first=True)


def _latest_datetime(payload: Any) -> str:
    return _datetime_value(payload, first=False)


def _datetime_value(payload: Any, *, first: bool) -> str:
    if not isinstance(payload, pd.DataFrame) or payload.empty:
        return ""
    for column in ("datetime", "date", "timestamp", "servertime"):
        if column not in payload.columns:
            continue
        values = payload[column].dropna()
        if values.empty:
            continue
        value = values.iloc[0] if first else values.iloc[-1]
        if isinstance(value, pd.Timestamp):
            return str(value.isoformat(sep=" "))
        if hasattr(value, "isoformat"):
            return str(value.isoformat())
        return str(value)
    if isinstance(payload.index, pd.DatetimeIndex) and len(payload.index):
        value = payload.index[0] if first else payload.index[-1]
        return str(value.isoformat(sep=" "))
    return ""


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if percentile == 50:
        return round(float(median(ordered)), 3)
    index = min(len(ordered) - 1, max(0, int(round((percentile / 100) * (len(ordered) - 1)))))
    return round(float(ordered[index]), 3)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value for key, value in row.items()})


def _parse_server(value: str) -> tuple[str, int] | None:
    if not value:
        return None
    host, _, port = value.partition(":")
    if not host or not port:
        raise ValueError("--server must be host:port")
    return host, int(port)


if __name__ == "__main__":
    raise SystemExit(main())
