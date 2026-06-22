from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

from src.data.clickhouse_minute1_sync import sync_clickhouse_minute1_kline


class FakeClickHouseClient:
    def __init__(self, *, latest_by_symbol: dict[str, datetime] | None = None) -> None:
        self.latest_by_symbol = latest_by_symbol or {}
        self.queries: list[tuple[str, object | None]] = []
        self.inserts: list[list[tuple]] = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized:
            return [
                ("000001", "平安银行"),
                ("000004", "*ST国华"),
                ("600000", "浦发银行"),
            ]
        if "max(datetime)" in normalized and "group by symbol" in normalized:
            return [(symbol, latest) for symbol, latest in sorted(self.latest_by_symbol.items())]
        if normalized.startswith("insert into minute1_kline"):
            self.inserts.append(list(params or []))
            return []
        if "from minute1_kline" in normalized and "count()" in normalized:
            return [(sum(len(batch) for batch in self.inserts), datetime(2026, 6, 17, 9, 30), datetime(2026, 6, 17, 9, 32), 2)]
        return []


class FakeBatchSource:
    def __init__(self) -> None:
        self.batch_calls: list[tuple[list[str], date, str]] = []

    def fetch_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "1m") -> pd.DataFrame:
        self.batch_calls.append((symbols, trade_date, frequency))
        rows = []
        for symbol in symbols:
            rows.extend([
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 09:30:00"),
                    "symbol": symbol,
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 1000,
                    "amount": 10000.0,
                },
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 09:31:00"),
                    "symbol": symbol,
                    "open": 10.1,
                    "high": 10.1,
                    "low": 10.1,
                    "close": 10.1,
                    "volume": 1200,
                    "amount": 12120.0,
                },
            ])
        return pd.DataFrame(rows)


def test_sync_clickhouse_minute1_kline_creates_table_and_inserts_non_st_symbols() -> None:
    client = FakeClickHouseClient()
    source = FakeBatchSource()

    result = sync_clickhouse_minute1_kline(
        client=client,
        source=source,
        trade_date=date(2026, 6, 17),
        target_time=time(9, 31),
    )

    normalized_queries = [" ".join(query.lower().split()) for query, _ in client.queries]
    assert any("create table if not exists minute1_kline" in query for query in normalized_queries)
    assert source.batch_calls == [(["000001.SZ", "600000.SH"], date(2026, 6, 17), "1m")]
    assert result["target_symbols"] == 2
    assert result["success"] == 2
    assert result["inserted_rows"] == 4
    assert client.inserts[0][0] == ("000001", datetime(2026, 6, 17, 9, 30), 10.0, 10.0, 10.0, 10.0, 1000.0, 10000.0)


def test_sync_clickhouse_minute1_kline_only_inserts_rows_after_latest_datetime() -> None:
    client = FakeClickHouseClient(latest_by_symbol={"000001": datetime(2026, 6, 17, 9, 30)})
    source = FakeBatchSource()

    result = sync_clickhouse_minute1_kline(
        client=client,
        source=source,
        trade_date=date(2026, 6, 17),
        symbols=["000001.SZ"],
        target_time=time(9, 31),
    )

    assert result["inserted_rows"] == 1
    assert client.inserts == [[("000001", datetime(2026, 6, 17, 9, 31), 10.1, 10.1, 10.1, 10.1, 1200.0, 12120.0)]]
