from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.bar_repository import CacheBarRepository


def _write_cache_file(path, symbol: str, closes: list[float]) -> None:
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
            "volume": 1000 + i,
            "amount": close * (1000 + i),
            "adjusted_close": close,
        })
    pd.DataFrame(rows).to_parquet(path / f"{stem}_20250101_20250228.parquet", index=False)


def test_cache_bar_repository_loads_range_as_multiindex(tmp_path) -> None:
    _write_cache_file(tmp_path, "000001.SZ", [10, 11, 12])
    repo = CacheBarRepository(tmp_path)

    bars = repo.load_range(["000001.SZ"], date(2025, 1, 2), date(2025, 1, 3))

    assert len(bars) == 2
    assert bars.index.names == ["date", "symbol"]
    assert bars["close"].tolist() == [11, 12]


def test_cache_bar_repository_loads_latest_history_until_date(tmp_path) -> None:
    _write_cache_file(tmp_path, "000001.SZ", [10, 11, 12])
    repo = CacheBarRepository(tmp_path)

    bars = repo.load_latest_until("000001.SZ", pd.Timestamp("2025-01-02"))

    assert bars["close"].tolist() == [10, 11]


def test_cache_bar_repository_ranks_liquid_symbols(tmp_path) -> None:
    _write_cache_file(tmp_path, "000001.SZ", [10, 10])
    _write_cache_file(tmp_path, "600519.SH", [100, 100])
    repo = CacheBarRepository(tmp_path)

    ranking = repo.rank_liquid_symbols(
        start=date(2025, 1, 1),
        end=date(2025, 1, 10),
        limit=1,
        min_bars=2,
    )

    assert [row["symbol"] for row in ranking] == ["600519.SH"]
