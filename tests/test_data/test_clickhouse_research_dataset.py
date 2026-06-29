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


class InvalidOhlcClickHouseClient:
    """ClickHouse stub returning a negative-price dirty row alongside clean rows."""

    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized:
            return [("000937", "冀中能源"), ("600519", "贵州茅台")]
        if "from daily_kline" in normalized:
            # Column order matches the real query: symbol, date, open, high, low, close, volume, amount
            return [
                ("000937", date(2021, 3, 26), -0.21, -0.23, -0.20, -0.21, 1000.0, -210.0),  # 负价脏行
                ("000937", date(2021, 3, 29), 10.0, 10.2, 9.8, 10.1, 2000.0, 20200.0),       # 正常
                ("600519", date(2021, 3, 29), 1800.0, 1810.0, 1790.0, 1805.0, 500.0, 902500.0),
            ]
        return []


def test_build_clickhouse_research_dataset_filters_invalid_ohlc_rows(tmp_path) -> None:
    output = tmp_path / "research" / "daily_clickhouse.parquet"

    manifest = build_clickhouse_research_dataset(
        start=date(2021, 3, 26),
        end=date(2021, 3, 29),
        output_path=output,
        symbols=["000937.SZ", "600519.SH"],
        client=InvalidOhlcClickHouseClient(),
    )

    df = pd.read_parquet(output)
    # 防御历史 invalid OHLC（如 000937 2020-2021 负价），负价脏行不应进 parquet
    assert (df["close"] <= 0).sum() == 0
    assert (df[["open", "high", "low", "close"]] > 0).all().all()
    assert len(df) == 2  # 负价脏行被滤除，剩 2 行
    assert manifest["row_count"] == 2
