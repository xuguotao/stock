from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.run_tail_session_live import calculate_market_breadth_above_ma20, resolve_scan_symbols
from src.strategy.tail_session.live import prices_from_quotes


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


def _write_trending_cache_file(path, symbol: str, closes: list[float]) -> None:
    stem = symbol.replace(".", "_")
    rows = []
    for i, close in enumerate(closes):
        rows.append({
            "date": pd.Timestamp("2025-01-01") + pd.offsets.BDay(i),
            "symbol": symbol,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000,
            "amount": close * 1000,
            "adjusted_close": close,
        })
    pd.DataFrame(rows).to_parquet(path / f"{stem}_20250101_20250228.parquet", index=False)


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


def test_calculate_market_breadth_uses_realtime_price_over_latest_close(tmp_path) -> None:
    cache_dir = tmp_path / "bars"
    cache_dir.mkdir()
    _write_trending_cache_file(cache_dir, "000001.SZ", [10.0] * 20)
    _write_trending_cache_file(cache_dir, "600519.SH", [20.0] * 20)
    quotes = pd.DataFrame([
        {"symbol": "000001.SZ", "price": 11.0},
        {"symbol": "600519.SH", "price": 19.0},
    ])

    result = calculate_market_breadth_above_ma20(
        symbols=["000001.SZ", "600519.SH"],
        bars_cache_dir=cache_dir,
        trade_date=date(2025, 2, 3),
        quotes=quotes,
        ma_window=20,
    )

    assert result.symbol_count == 2
    assert result.above_count == 1
    assert result.breadth == 0.5


def test_calculate_market_breadth_skips_symbols_without_enough_history(tmp_path) -> None:
    cache_dir = tmp_path / "bars"
    cache_dir.mkdir()
    _write_trending_cache_file(cache_dir, "000001.SZ", [10.0] * 20)
    _write_trending_cache_file(cache_dir, "600519.SH", [20.0] * 5)

    result = calculate_market_breadth_above_ma20(
        symbols=["000001.SZ", "600519.SH"],
        bars_cache_dir=cache_dir,
        trade_date=date(2025, 2, 3),
        quotes=None,
        ma_window=20,
    )

    assert result.symbol_count == 1
    assert result.above_count == 0
    assert result.breadth == 0.0


def test_prices_from_quotes_falls_back_to_signal_prices() -> None:
    class Signal:
        symbol = "600519.SH"
        last_price = 100.0

    quotes = pd.DataFrame([{"symbol": "000001.SZ", "price": 11.0}])

    assert prices_from_quotes(quotes, [Signal()]) == {
        "000001.SZ": 11.0,
        "600519.SH": 100.0,
    }
