from __future__ import annotations

from datetime import date
import json

import pandas as pd

from src.data.clickhouse_research_dataset import build_clickhouse_research_dataset


class FakeClickHouseClient:
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized:
            return [
                ("000001", "平安银行"),
                ("000004", "*ST国华"),
                ("600000", "浦发银行"),
            ]
        if "from daily_kline" in normalized:
            return [
                ("000001", date(2026, 6, 12), 10.0, 10.5, 9.9, 10.2, 1000.0, 10200.0),
                ("600000", date(2026, 6, 12), 20.0, 20.5, 19.9, 20.2, 2000.0, 40400.0),
            ]
        return []


def test_build_clickhouse_research_dataset_writes_standard_parquet_and_manifest(tmp_path) -> None:
    output = tmp_path / "research" / "daily_clickhouse.parquet"

    manifest = build_clickhouse_research_dataset(
        start=date(2026, 6, 12),
        end=date(2026, 6, 12),
        output_path=output,
        client=FakeClickHouseClient(),
    )

    assert output.exists()
    assert output.with_name("daily_clickhouse_manifest.json").exists()
    assert manifest["source"] == "clickhouse"
    assert manifest["row_count"] == 2
    assert manifest["symbols"] == ["000001.SZ", "600000.SH"]
    assert manifest["missing_symbols"] == []

    df = pd.read_parquet(output)
    assert df["symbol"].tolist() == ["000001.SZ", "600000.SH"]
    assert set(["date", "symbol", "open", "high", "low", "close", "volume", "amount", "adjusted_close"]).issubset(df.columns)

    saved = json.loads(output.with_name("daily_clickhouse_manifest.json").read_text(encoding="utf-8"))
    assert saved["dataset_path"] == str(output)
    assert saved["clickhouse"]["table"] == "daily_kline"


def test_build_clickhouse_research_dataset_respects_symbols_and_limit(tmp_path) -> None:
    output = tmp_path / "research" / "daily_clickhouse.parquet"

    manifest = build_clickhouse_research_dataset(
        start=date(2026, 6, 12),
        end=date(2026, 6, 12),
        output_path=output,
        symbols=["000001.SZ", "000004.SZ", "600000.SH"],
        limit=1,
        client=FakeClickHouseClient(),
    )

    assert manifest["requested_symbols"] == ["000001.SZ"]
    assert manifest["symbols"] == ["000001.SZ"]
