from __future__ import annotations

from datetime import date
import fcntl

import pandas as pd

import src.data.clickhouse_daily_sync as daily_sync
from src.data.clickhouse_daily_sync import (
    sync_clickhouse_daily_from_minute5,
    sync_clickhouse_index_daily,
)


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.counts = [0, 2]
        self.lock_inserted = True

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.lower().split())
        if normalized.startswith("create table if not exists daily_kline_repair_locks"):
            return []
        if normalized.startswith("insert into daily_kline_repair_locks"):
            return [(1 if self.lock_inserted else 0,)]
        if "delete from daily_kline_repair_locks" in normalized:
            return []
        if normalized.startswith("select count() from daily_kline"):
            return [(self.counts.pop(0),)]
        return []


class FakeIndexClickHouseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.lower().split())
        if "select distinct code from index_daily" in normalized:
            return [("000001",), ("399001",), ("sh000300",)]
        if "select date from index_daily" in normalized:
            return [(date(2026, 6, 17),)]
        return []


def test_sync_clickhouse_daily_from_minute5_derives_missing_daily_rows() -> None:
    client = FakeClickHouseClient()

    result = sync_clickhouse_daily_from_minute5(client=client, trade_date=date(2026, 6, 18))

    executed = [" ".join(query.lower().split()) for query, _ in client.calls]
    assert result == {
        "trade_date": "2026-06-18",
        "before_rows": 0,
        "after_rows": 2,
        "inserted_rows": 2,
    }
    assert any("insert into daily_kline" in query for query in executed)
    assert any("from minute5_kline" in query for query in executed)
    assert any("group by symbol, datetime" in query for query in executed)
    assert any("daily_kline_repair_locks" in query for query in executed)
    assert any("where bars.symbol not in" in query for query in executed)


def test_sync_clickhouse_daily_from_minute5_skips_when_trade_date_lock_is_held() -> None:
    client = FakeClickHouseClient()
    client.lock_inserted = False

    result = sync_clickhouse_daily_from_minute5(client=client, trade_date=date(2026, 6, 18))

    executed = [" ".join(query.lower().split()) for query, _ in client.calls]
    assert result == {
        "trade_date": "2026-06-18",
        "before_rows": 0,
        "after_rows": 0,
        "inserted_rows": 0,
        "skipped": True,
        "skip_reason": "daily_repair_lock_held",
    }
    assert not any("insert into daily_kline (" in query for query in executed)


def test_sync_clickhouse_daily_from_minute5_skips_when_process_lock_is_held(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "daily_repair.lock"
    monkeypatch.setattr(daily_sync, "_DAILY_REPAIR_LOCK_PATH", lock_path, raising=False)
    client = FakeClickHouseClient()
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = sync_clickhouse_daily_from_minute5(client=client, trade_date=date(2026, 6, 18))

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    executed = [" ".join(query.lower().split()) for query, _ in client.calls]
    assert result == {
        "trade_date": "2026-06-18",
        "before_rows": 0,
        "after_rows": 0,
        "inserted_rows": 0,
        "skipped": True,
        "skip_reason": "daily_repair_lock_held",
    }
    assert not any("insert into daily_kline (" in query for query in executed)


def test_sync_clickhouse_index_daily_fills_existing_index_codes() -> None:
    client = FakeIndexClickHouseClient()
    fetched_symbols: list[str] = []

    def fetcher(symbol: str) -> pd.DataFrame:
        fetched_symbols.append(symbol)
        return pd.DataFrame(
            [
                {"date": date(2026, 6, 17), "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
                {"date": date(2026, 6, 18), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 120},
            ]
        )

    result = sync_clickhouse_index_daily(
        client=client,
        fetcher=fetcher,
        start=date(2026, 6, 17),
        end=date(2026, 6, 18),
    )

    inserts = [
        params
        for query, params in client.calls
        if "insert into index_daily" in " ".join(query.lower().split())
    ]
    assert fetched_symbols == ["sh000001", "sz399001", "sh000300"]
    assert result["inserted_rows"] == 3
    assert len(inserts) == 3
    assert inserts[0][0][0] == "000001"
    assert inserts[0][0][1] == date(2026, 6, 18)
    assert inserts[0][0][8] == 10.0
