from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.data.clickhouse_quote_snapshot_sync import sync_clickhouse_quote_snapshots


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.inserted: list[tuple] = []

    def execute(self, query: str, params=None):
        self.queries.append(query)
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized:
            return [("000001", "平安银行"), ("600000", "浦发银行")]
        if normalized.startswith("insert into stock_quote_snapshots ("):
            self.inserted.extend(params)
            return []
        return []


class FakeQuoteSource:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def fetch_realtime_quotes(self, symbols):
        self.calls.append(symbols)
        return pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "price": 11.06,
                    "change_pct": -1.6,
                    "volume": 100000,
                    "amount": 110600000.0,
                    "turnover_pct": 1.2,
                    "pe_ttm": 4.98,
                    "pb": 0.47,
                    "mcap": 220000000000.0,
                    "float_mcap": 210000000000.0,
                    "limit_up": 12.36,
                    "limit_down": 10.12,
                    "timestamp": "2026-06-16 14:30:00",
                },
                {
                    "symbol": "600000.SH",
                    "name": "浦发银行",
                    "price": 9.1,
                    "change_pct": 0.2,
                    "volume": 200000,
                    "amount": 182000000.0,
                    "timestamp": "2026-06-16 14:30:00",
                },
            ]
        )


def test_sync_clickhouse_quote_snapshots_creates_table_and_inserts_quotes() -> None:
    client = FakeClickHouseClient()
    quote_source = FakeQuoteSource()
    progress = []

    result = sync_clickhouse_quote_snapshots(
        client=client,
        quote_source=quote_source,
        checked_at="2026-06-16 14:30:05",
        chunk_size=400,
        progress=lambda percent, stage, message: progress.append((percent, stage, message)),
    )

    assert any("create table if not exists stock_quote_snapshots" in query.lower() for query in client.queries)
    assert quote_source.calls == [["000001.SZ", "600000.SH"]]
    assert len(client.inserted) == 2
    assert client.inserted[0][0] == datetime(2026, 6, 16, 14, 30, 5)
    assert client.inserted[0][1] == "000001.SZ"
    assert client.inserted[0][-1] == datetime(2026, 6, 16, 14, 30, 0)
    assert result["target_symbols"] == 2
    assert result["quote_rows"] == 2
    assert result["inserted_rows"] == 2
    assert result["failed_chunks"] == 0
    assert result["latest_quote_time"] == "2026-06-16 14:30:00"
    assert result["timings"]["fetch_seconds"] >= 0
    assert result["timings"]["write_seconds"] >= 0
    assert result["timings"]["rollup_seconds"] >= 0
    assert progress[-1] == (100, "completed", "行情快照同步完成")


def test_sync_clickhouse_quote_snapshots_maintains_retention_and_rollups() -> None:
    client = FakeClickHouseClient()
    quote_source = FakeQuoteSource()

    result = sync_clickhouse_quote_snapshots(
        client=client,
        quote_source=quote_source,
        checked_at="2026-06-16 14:30:05",
        chunk_size=400,
    )

    normalized_queries = [" ".join(query.lower().split()) for query in client.queries]
    assert any("modify ttl snapshot_at + interval 120 day delete" in query for query in normalized_queries)
    assert any("create table if not exists stock_quote_snapshots_1m" in query for query in normalized_queries)
    assert any("create table if not exists stock_quote_snapshots_5m" in query for query in normalized_queries)
    assert any("insert into stock_quote_snapshots_1m" in query for query in normalized_queries)
    assert any("insert into stock_quote_snapshots_5m" in query for query in normalized_queries)
    assert result["rollups"] == {
        "1m": {"bucket_start": "2026-06-16 14:30:00", "refreshed_buckets": 2},
        "5m": {"bucket_start": "2026-06-16 14:30:00", "refreshed_buckets": 2},
    }
