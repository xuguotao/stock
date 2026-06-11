from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.run_tail_session_live import resolve_scan_symbols


class FakeAggregator:
    def get_csi300_symbols(self):
        return ["000001.SZ", "600519.SH", "300750.SZ"]


def _write_cache_file(path, symbol: str, close: float, volume: int) -> None:
    stem = symbol.replace(".", "_")
    pd.DataFrame([
        {
            "date": pd.Timestamp("2025-01-02"),
            "symbol": symbol,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
            "amount": 0,
            "adjusted_close": close,
        },
        {
            "date": pd.Timestamp("2025-01-03"),
            "symbol": symbol,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
            "amount": 0,
            "adjusted_close": close,
        },
    ]).to_parquet(path / f"{stem}_20250101_20250110.parquet", index=False)


def test_resolve_scan_symbols_prefers_explicit_symbols(tmp_path) -> None:
    symbols = resolve_scan_symbols(
        aggregator=FakeAggregator(),
        raw_symbols=["1", "600519"],
        limit=1,
        universe="liquid-cache",
        bars_cache_dir=tmp_path,
        liquidity_start=date(2025, 1, 1),
        liquidity_end=date(2025, 1, 10),
        liquidity_min_bars=2,
        liquidity_min_end_date=None,
    )

    assert symbols == ["000001.SZ", "600519.SH"]


def test_resolve_scan_symbols_uses_liquid_cache_universe(tmp_path) -> None:
    cache_dir = tmp_path / "bars"
    cache_dir.mkdir()
    _write_cache_file(cache_dir, "000001.SZ", close=10, volume=100)
    _write_cache_file(cache_dir, "600519.SH", close=100, volume=1000)

    symbols = resolve_scan_symbols(
        aggregator=FakeAggregator(),
        raw_symbols=None,
        limit=1,
        universe="liquid-cache",
        bars_cache_dir=cache_dir,
        liquidity_start=date(2025, 1, 1),
        liquidity_end=date(2025, 1, 10),
        liquidity_min_bars=2,
        liquidity_min_end_date=None,
    )

    assert symbols == ["600519.SH"]


def test_resolve_scan_symbols_falls_back_to_default_pool_when_liquid_cache_empty(tmp_path) -> None:
    symbols = resolve_scan_symbols(
        aggregator=FakeAggregator(),
        raw_symbols=None,
        limit=2,
        universe="liquid-cache",
        bars_cache_dir=tmp_path,
        liquidity_start=date(2025, 1, 1),
        liquidity_end=date(2025, 1, 10),
        liquidity_min_bars=2,
        liquidity_min_end_date=None,
    )

    assert symbols == ["000001.SZ", "600519.SH"]
