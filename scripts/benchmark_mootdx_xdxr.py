#!/usr/bin/env python3
"""Benchmark Mootdx XDXR reads without writing to ClickHouse by default."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data  # noqa: E402
from src.data.mootdx_source import MootdxSource  # noqa: E402


BUCKET_ORDER = ("sh_main", "sz_main", "chi_next", "st", "other")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=_positive_int, default=300, help="Maximum number of catalog symbols to request.")
    parser.add_argument("--rate-limit", type=_non_negative_float, default=0.02, help="Minimum seconds between Mootdx requests.")
    parser.add_argument("--timeout", type=_positive_int, default=10, help="Mootdx socket timeout in seconds.")
    parser.add_argument("--write", action="store_true", help="Explicitly sync the selected sample into ClickHouse.")
    parser.add_argument("--bestip", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.bestip:
        parser.error("--bestip is disabled for reproducible XDXR benchmarks")
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    source_factory: Callable[..., Any] = MootdxSource,
    sync_fn: Callable[..., dict[str, Any]] = sync_mootdx_offline_data,
) -> int:
    args = parse_args(argv)
    source = source_factory(bestip=False, timeout=args.timeout, rate_limit=args.rate_limit)
    catalog = list(source.fetch_stock_list())
    symbols, bucket_counts = select_benchmark_symbols(catalog, sample_size=args.sample_size)
    result: dict[str, Any] = {
        "mode": "write" if args.write else "read_only",
        "catalog_size": len(catalog),
        "bucket_counts": bucket_counts,
        "sample_count": len(symbols),
        "bestip": False,
    }

    if args.write:
        sync_result = sync_fn(source=source, symbols=symbols, tasks=["xdxr"], ensure_tables=True)
        # The sync path exposes aggregate XDXR diagnostics, not each request's
        # latency samples. Keep its benchmark counters at the top level and
        # make unavailable percentile metrics explicit JSON null values.
        result.update(_write_diagnostics(sync_result))
        result["sync"] = sync_result
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1 if sync_result.get("failed") else 0

    result.update(_read_only_diagnostics(source, symbols))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def select_benchmark_symbols(catalog: Iterable[Any], *, sample_size: int) -> tuple[list[str], dict[str, int]]:
    """Select a stable, round-robin sample across board and ST buckets."""
    buckets: dict[str, list[str]] = {name: [] for name in BUCKET_ORDER}
    for stock in catalog:
        symbol = str(getattr(stock, "symbol", "")).strip().upper()
        if not symbol:
            continue
        buckets[_symbol_bucket(symbol, is_st_flag=bool(getattr(stock, "is_st", False)))].append(symbol)
    for values in buckets.values():
        values.sort()
    bucket_counts = {name: len(buckets[name]) for name in BUCKET_ORDER if buckets[name]}

    selected: list[str] = []
    while len(selected) < sample_size:
        added = False
        for name in BUCKET_ORDER:
            if buckets[name]:
                selected.append(buckets[name].pop(0))
                added = True
                if len(selected) >= sample_size:
                    break
        if not added:
            break
    return selected, bucket_counts


def _read_only_diagnostics(source: Any, symbols: list[str]) -> dict[str, Any]:
    latencies_ms: list[float] = []
    success_count = empty_count = error_count = event_rows = 0
    started = time.perf_counter()
    for symbol in symbols:
        request_started = time.perf_counter()
        try:
            payload = source.fetch_xdxr(symbol)
            row_count = _row_count(payload)
            if row_count:
                success_count += 1
                event_rows += row_count
            else:
                empty_count += 1
        except Exception:  # noqa: BLE001 - a benchmark must retain per-symbol failures.
            error_count += 1
        finally:
            latencies_ms.append((time.perf_counter() - request_started) * 1000)
    request_seconds = round(time.perf_counter() - started, 3)
    p50 = _percentile(latencies_ms, 50)
    p95 = _percentile(latencies_ms, 95)
    p99 = _percentile(latencies_ms, 99)
    return {
        "success_count": success_count,
        "empty_count": empty_count,
        "error_count": error_count,
        "event_rows": event_rows,
        "request_seconds": request_seconds,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
    }


def _write_diagnostics(sync_result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = sync_result.get("diagnostics") or {}
    xdxr = diagnostics.get("xdxr") or {}
    return {
        "success_count": int(xdxr.get("success_symbols") or 0),
        "empty_count": int(xdxr.get("empty_symbols_count") or 0),
        "error_count": int(xdxr.get("failed_symbols_count") or 0),
        "event_rows": int(xdxr.get("event_rows") or 0),
        "request_seconds": float(xdxr.get("request_seconds") or 0.0),
        "p50": None,
        "p95": None,
        "p99": None,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
    }


def _symbol_bucket(symbol: str, *, is_st_flag: bool) -> str:
    code, _, market = symbol.partition(".")
    if is_st_flag:
        return "st"
    if market == "SZ" and code.startswith(("300", "301")):
        return "chi_next"
    if market == "SH":
        return "sh_main"
    if market == "SZ":
        return "sz_main"
    return "other"


def _row_count(payload: Any) -> int:
    if isinstance(payload, pd.DataFrame):
        return len(payload)
    if isinstance(payload, (list, tuple)):
        return len(payload)
    return 0


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if percentile == 50:
        return round(float(median(ordered)), 3)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return round(float(ordered[index]), 3)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
