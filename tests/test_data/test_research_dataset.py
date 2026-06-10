from __future__ import annotations

from datetime import date
import json

import pandas as pd

from src.data.research_dataset import build_research_dataset, load_research_dataset


def _write_cache_file(path, symbol: str, start_key: str = "20240101", end_key: str = "20250101") -> None:
    df = pd.DataFrame([
        {
            "date": pd.Timestamp("2024-01-02"),
            "symbol": symbol,
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
            "symbol": symbol,
            "open": 10.2,
            "high": 10.3,
            "low": 10.1,
            "close": 10.2,
            "volume": 1200,
            "amount": 12_240,
            "adjusted_close": 10.2,
        },
    ])
    stem = symbol.replace(".", "_")
    df.to_parquet(path / f"{stem}_{start_key}_{end_key}.parquet", index=False)


def test_build_research_dataset_from_cache_writes_parquet_and_manifest(tmp_path) -> None:
    cache_dir = tmp_path / "cache" / "bars"
    cache_dir.mkdir(parents=True)
    output_path = tmp_path / "research" / "daily_bars.parquet"
    manifest_path = tmp_path / "research" / "daily_bars_manifest.json"
    _write_cache_file(cache_dir, "000001.SZ")

    manifest = build_research_dataset(
        symbols=["000001.SZ", "600519.SH"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
        bars_dir=cache_dir,
        output_path=output_path,
        manifest_path=manifest_path,
    )

    assert output_path.exists()
    assert manifest_path.exists()
    assert manifest["row_count"] == 2
    assert manifest["symbols"] == ["000001.SZ"]
    assert manifest["missing_symbols"] == ["600519.SH"]
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved_manifest["dataset_path"] == str(output_path)


def test_load_research_dataset_filters_symbols_and_dates(tmp_path) -> None:
    dataset_path = tmp_path / "daily_bars.parquet"
    pd.DataFrame([
        {"date": pd.Timestamp("2024-01-02"), "symbol": "000001.SZ", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 1, "amount": 10, "adjusted_close": 10},
        {"date": pd.Timestamp("2024-01-03"), "symbol": "600519.SH", "open": 20, "high": 20, "low": 20, "close": 20, "volume": 1, "amount": 20, "adjusted_close": 20},
    ]).to_parquet(dataset_path, index=False)

    bars = load_research_dataset(
        dataset_path,
        symbols=["600519.SH"],
        start=date(2024, 1, 3),
        end=date(2024, 1, 3),
    )

    assert len(bars) == 1
    assert bars.index.names == ["date", "symbol"]
    assert bars.index.get_level_values("symbol").tolist() == ["600519.SH"]
