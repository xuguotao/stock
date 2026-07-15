from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts import benchmark_mootdx_xdxr
from src.data.models import StockInfo


class FakeSource:
    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch_stock_list(self) -> list[StockInfo]:
        return [
            StockInfo(symbol="600002.SH", code="600002", name="沪主二", is_st=False),
            StockInfo(symbol="600001.SH", code="600001", name="沪主一", is_st=False),
            StockInfo(symbol="000002.SZ", code="000002", name="深主二", is_st=False),
            StockInfo(symbol="000001.SZ", code="000001", name="深主一", is_st=False),
            StockInfo(symbol="300002.SZ", code="300002", name="创二", is_st=False),
            StockInfo(symbol="300001.SZ", code="300001", name="创一", is_st=False),
            StockInfo(symbol="600003.SH", code="600003", name="ST 沪", is_st=True),
        ]

    def fetch_xdxr(self, symbol: str) -> pd.DataFrame:
        self.fetched.append(symbol)
        if symbol == "000001.SZ":
            return pd.DataFrame()
        if symbol == "300001.SZ":
            raise RuntimeError("source unavailable")
        return pd.DataFrame([{"category": 1}, {"category": 2}])


def test_parse_args_defaults_to_safe_benchmark_parameters() -> None:
    args = benchmark_mootdx_xdxr.parse_args([])

    assert args.sample_size == 300
    assert args.rate_limit == 0.02
    assert args.timeout == 10
    assert args.bestip is False
    assert args.write is False


def test_parse_args_rejects_bestip() -> None:
    with pytest.raises(SystemExit):
        benchmark_mootdx_xdxr.parse_args(["--bestip"])


def test_read_only_benchmark_is_deterministic_and_never_invokes_sync(capsys) -> None:
    source = FakeSource()

    def unexpected_sync(**_kwargs):
        raise AssertionError("read-only benchmark must not invoke ClickHouse sync")

    assert benchmark_mootdx_xdxr.main(
        ["--sample-size", "7"],
        source_factory=lambda **_kwargs: source,
        sync_fn=unexpected_sync,
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "read_only"
    assert payload["catalog_size"] == 7
    assert payload["bucket_counts"] == {"chi_next": 2, "sh_main": 2, "st": 1, "sz_main": 2}
    assert payload["sample_count"] == 7
    assert source.fetched == ["600001.SH", "000001.SZ", "300001.SZ", "600003.SH", "600002.SH", "000002.SZ", "300002.SZ"]
    assert payload["success_count"] == 5
    assert payload["empty_count"] == 1
    assert payload["error_count"] == 1
    assert payload["event_rows"] == 10
    assert payload["bestip"] is False
    assert set(payload) >= {"request_seconds", "p50_ms", "p95_ms", "p99_ms"}


def test_write_mode_invokes_only_xdxr_sync_for_selected_symbols(capsys) -> None:
    source = FakeSource()
    calls: list[dict] = []

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return {"inserted": {"mootdx_xdxr": 2}, "failed": {}, "diagnostics": {"xdxr": {"success": 1}}}

    assert benchmark_mootdx_xdxr.main(
        ["--sample-size", "2", "--write"],
        source_factory=lambda **_kwargs: source,
        sync_fn=fake_sync,
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "write"
    assert calls == [{
        "source": source,
        "symbols": ["600001.SH", "000001.SZ"],
        "tasks": ["xdxr"],
        "ensure_tables": True,
    }]
    assert payload["sync"] == {"inserted": {"mootdx_xdxr": 2}, "failed": {}, "diagnostics": {"xdxr": {"success": 1}}}


def test_select_symbols_round_robins_stable_buckets() -> None:
    source = FakeSource()

    selected, bucket_counts = benchmark_mootdx_xdxr.select_benchmark_symbols(source.fetch_stock_list(), sample_size=5)

    assert bucket_counts == {"chi_next": 2, "sh_main": 2, "st": 1, "sz_main": 2}
    assert selected == ["600001.SH", "000001.SZ", "300001.SZ", "600003.SH", "600002.SH"]
