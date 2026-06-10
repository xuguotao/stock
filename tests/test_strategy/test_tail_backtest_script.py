from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.run_tail_session_backtest import (
    load_bars_from_offline_cache,
    load_bars_from_research_dataset,
    load_bars_with_progress,
    make_aggregator,
    resolve_symbols,
)


class FakeAggregator:
    def __init__(self):
        self.calls = []

    def get_csi300_symbols(self):
        return ["000001.SZ", "600519.SH", "300750.SZ"]

    def get_bars(self, symbol, start, end, use_cache=True):
        self.calls.append(symbol)
        if symbol == "600519.SH":
            return pd.DataFrame()
        return pd.DataFrame([{
            "date": start,
            "symbol": symbol,
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "volume": 1000,
            "amount": 10_000,
            "adjusted_close": 10.0,
        }])


def test_resolve_symbols_applies_limit_to_default_pool() -> None:
    symbols = resolve_symbols(FakeAggregator(), raw_symbols=None, limit=2)

    assert symbols == ["000001.SZ", "600519.SH"]


def test_resolve_symbols_formats_explicit_symbols_without_limit() -> None:
    symbols = resolve_symbols(FakeAggregator(), raw_symbols=["1", "600519"], limit=1)

    assert symbols == ["000001.SZ", "600519.SH"]


def test_load_bars_with_progress_combines_non_empty_symbol_data() -> None:
    agg = FakeAggregator()

    bars = load_bars_with_progress(
        agg,
        ["000001.SZ", "600519.SH", "300750.SZ"],
        date(2025, 1, 1),
        date(2025, 1, 2),
        verbose=False,
    )

    assert agg.calls == ["000001.SZ", "600519.SH", "300750.SZ"]
    assert bars.index.names == ["date", "symbol"]
    assert bars.index.get_level_values("symbol").tolist() == ["000001.SZ", "300750.SZ"]


def test_make_aggregator_uses_sina_only_by_default() -> None:
    agg = make_aggregator(fallback_sources=False)

    assert [source.name for source in agg.sources] == ["sina"]


def test_load_bars_from_offline_cache_uses_covering_parquet_file(tmp_path) -> None:
    cache_dir = tmp_path / "bars"
    cache_dir.mkdir()
    pd.DataFrame([
        {
            "date": pd.Timestamp("2024-01-02"),
            "symbol": "000001.SZ",
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "volume": 1000,
            "amount": 10_000,
            "adjusted_close": 10.0,
        },
        {
            "date": pd.Timestamp("2024-01-03"),
            "symbol": "000001.SZ",
            "open": 10.1,
            "high": 10.2,
            "low": 10.0,
            "close": 10.1,
            "volume": 1000,
            "amount": 10_100,
            "adjusted_close": 10.1,
        },
    ]).to_parquet(cache_dir / "000001_SZ_20240101_20250601.parquet", index=False)

    bars = load_bars_from_offline_cache(
        cache_dir,
        ["000001.SZ"],
        date(2024, 1, 2),
        date(2024, 1, 3),
    )

    assert len(bars) == 2
    assert bars.index.names == ["date", "symbol"]


def test_load_bars_from_research_dataset_uses_all_symbols_when_none_requested(tmp_path) -> None:
    dataset_path = tmp_path / "daily_bars.parquet"
    pd.DataFrame([
        {"date": pd.Timestamp("2024-01-02"), "symbol": "000001.SZ", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 1, "amount": 10, "adjusted_close": 10},
        {"date": pd.Timestamp("2024-01-02"), "symbol": "600519.SH", "open": 20, "high": 20, "low": 20, "close": 20, "volume": 1, "amount": 20, "adjusted_close": 20},
    ]).to_parquet(dataset_path, index=False)

    bars, symbols = load_bars_from_research_dataset(
        dataset_path,
        raw_symbols=None,
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
    )

    assert symbols == ["000001.SZ", "600519.SH"]
    assert len(bars) == 2
