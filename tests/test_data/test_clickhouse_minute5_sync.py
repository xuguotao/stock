from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline


class FakeClickHouseClient:
    def __init__(self, *, complete_symbols: set[str] | None = None) -> None:
        self.complete_symbols = complete_symbols or set()
        self.inserts: list[list[tuple]] = []
        self.calls: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized:
            return [
                ("000001", "平安银行"),
                ("000004", "*ST国华"),
                ("600000", "浦发银行"),
            ]
        if "select distinct symbol from minute5_kline" in normalized:
            return [(symbol,) for symbol in sorted(self.complete_symbols)]
        if "from minute5_kline" in normalized and "count()" in normalized:
            return [(len(self.inserts) * 2, datetime(2026, 6, 12, 14, 55), datetime(2026, 6, 12, 15, 0), 2)]
        if normalized.startswith("insert into minute5_kline"):
            self.inserts.append(list(params or []))
            return []
        return []


class FakeSource:
    def __init__(self, empty_symbols: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.empty_symbols = empty_symbols or set()

    def fetch_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.calls.append(symbol)
        if symbol in self.empty_symbols:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 14:55:00"),
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10100.0,
                },
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                    "open": 10.1,
                    "high": 10.3,
                    "low": 10.0,
                    "close": 10.2,
                    "volume": 1200,
                    "amount": 12240.0,
                },
            ]
        )


def test_sync_clickhouse_minute5_kline_inserts_non_st_symbols() -> None:
    client = FakeClickHouseClient()
    source = FakeSource()
    progress_events = []

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        progress=lambda percent, stage, message: progress_events.append((percent, stage, message)),
    )

    assert source.calls == ["000001.SZ", "600000.SH"]
    assert result["target_symbols"] == 2
    assert result["success"] == 2
    assert result["failed"] == 0
    assert result["inserted_rows"] == 4
    assert progress_events[-1][1] == "completed"
    assert client.inserts == [
        [
            ("000001", datetime(2026, 6, 12, 14, 55), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
            ("000001", datetime(2026, 6, 12, 15, 0), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0),
        ],
        [
            ("600000", datetime(2026, 6, 12, 14, 55), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
            ("600000", datetime(2026, 6, 12, 15, 0), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0),
        ],
    ]


def test_sync_clickhouse_minute5_kline_respects_complete_symbols_and_limit() -> None:
    client = FakeClickHouseClient(complete_symbols={"000001"})
    source = FakeSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
        limit=2,
    )

    assert source.calls == ["600000.SH"]
    assert result["target_symbols"] == 2
    assert result["skipped"] == 1
    assert result["success"] == 1


def test_sync_clickhouse_minute5_kline_reports_no_data() -> None:
    client = FakeClickHouseClient()
    source = FakeSource(empty_symbols={"000001.SZ"})

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ"],
    )

    assert result["success"] == 0
    assert result["no_data"] == 1
    assert result["no_data_symbols"] == ["000001.SZ"]
    assert result["inserted_rows"] == 0
    assert client.inserts == []
