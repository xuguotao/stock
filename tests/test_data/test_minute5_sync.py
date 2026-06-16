from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from src.data.minute5_sync import sync_minute5_kline


def _create_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "create table stocks (symbol text primary key, name text, industry text, market text, list_date text, updated_at text)"
        )
        conn.execute(
            "create table minute5_kline (symbol text, datetime text, open real, high real, low real, close real, volume real, amount real, primary key (symbol, datetime))"
        )
        conn.executemany(
            "insert into stocks values (?, ?, ?, ?, ?, ?)",
            [
                ("000001", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-12"),
                ("000004", "*ST国华", "软件", "SZ", "1990-12-01", "2026-06-12"),
                ("600000", "浦发银行", "银行", "SH", "1999-11-10", "2026-06-12"),
            ],
        )


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
                    "time": pd.Timestamp(f"{trade_date.isoformat()} 14:55:00").time(),
                    "symbol": symbol,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10100.0,
                },
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                    "time": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00").time(),
                    "symbol": symbol,
                    "open": 10.1,
                    "high": 10.3,
                    "low": 10.0,
                    "close": 10.2,
                    "volume": 1200,
                    "amount": 12240.0,
                },
            ]
        )


def test_sync_minute5_kline_upserts_non_st_symbols(tmp_path) -> None:
    db_path = tmp_path / "stock.db"
    _create_db(db_path)
    source = FakeSource()
    progress_events = []

    result = sync_minute5_kline(
        db_path=db_path,
        trade_date=date(2026, 6, 12),
        source=source,
        progress=lambda percent, stage, message: progress_events.append((percent, stage, message)),
    )

    assert source.calls == ["000001.SZ", "600000.SH"]
    assert result["target_symbols"] == 2
    assert result["success"] == 2
    assert result["failed"] == 0
    assert result["inserted_rows"] == 4
    assert result["coverage_after"]["symbol_count"] == 2
    assert progress_events[-1][1] == "completed"

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select symbol, datetime, close from minute5_kline order by symbol, datetime"
        ).fetchall()

    assert rows == [
        ("000001", "2026-06-12 14:55:00", 10.1),
        ("000001", "2026-06-12 15:00:00", 10.2),
        ("600000", "2026-06-12 14:55:00", 10.1),
        ("600000", "2026-06-12 15:00:00", 10.2),
    ]


def test_sync_minute5_kline_respects_limit_and_explicit_symbols(tmp_path) -> None:
    db_path = tmp_path / "stock.db"
    _create_db(db_path)
    source = FakeSource()

    result = sync_minute5_kline(
        db_path=db_path,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "000004.SZ", "600000.SH"],
        limit=1,
    )

    assert source.calls == ["000001.SZ"]
    assert result["target_symbols"] == 1


def test_sync_minute5_kline_reports_no_data_without_counting_success(tmp_path) -> None:
    db_path = tmp_path / "stock.db"
    _create_db(db_path)
    source = FakeSource(empty_symbols={"000001.SZ"})

    result = sync_minute5_kline(
        db_path=db_path,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ"],
    )

    assert result["success"] == 0
    assert result["no_data"] == 1
    assert result["failed"] == 0
    assert result["inserted_rows"] == 0


def test_sync_minute5_kline_skips_symbols_already_complete(tmp_path) -> None:
    db_path = tmp_path / "stock.db"
    _create_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into minute5_kline values (?, ?, ?, ?, ?, ?, ?, ?)",
            ("000001", "2026-06-12 15:00:00", 10, 10, 10, 10, 100, 1000),
        )
    source = FakeSource()

    result = sync_minute5_kline(
        db_path=db_path,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
    )

    assert source.calls == ["600000.SH"]
    assert result["skipped"] == 1
    assert result["success"] == 1
