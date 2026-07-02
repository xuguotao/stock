from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from src.data.stock_research_status_sync import sync_stock_research_status


class FakeClient:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if normalized.startswith("select symbol, name, market, list_date from stocks"):
            return [
                ("000001", "平安银行", "SZ", "1991-04-03"),
                ("000004", "*ST国华", "SZ", "1990-12-01"),
                ("002808", "恒久退", "SZ", "2016-08-12"),
                ("920699", "海达尔", "BJ", ""),
            ]
        if normalized.startswith("select max(date) from daily_kline"):
            return [(date(2026, 7, 1),)]
        if normalized.startswith("select distinct symbol from daily_kline"):
            return [("000001",), ("000004",), ("002808",)]
        if normalized.startswith("select max(todate(datetime)) from minute5_kline"):
            return [(date(2026, 7, 2),)]
        if normalized.startswith("select distinct symbol from minute5_kline"):
            return [("000001",), ("000004",), ("002808",)]
        return []


def test_sync_stock_research_status_marks_eligibility_reasons_and_data_gaps() -> None:
    client = FakeClient()

    result = sync_stock_research_status(client=client, checked_at="2026-07-02 11:40:00")

    assert result == {
        "source": "stock_research_status",
        "total_rows": 4,
        "eligible_rows": 2,
        "data_ready_rows": 1,
        "excluded_rows": 2,
        "not_ready_rows": 1,
        "daily_missing_rows": 1,
        "minute5_missing_rows": 1,
        "daily_latest_date": "2026-07-01",
        "minute5_trade_date": "2026-07-02",
    }
    insert_query, rows = client.commands[-1]
    assert "insert into stock_research_status" in insert_query.lower()
    by_symbol = {row[0]: row for row in rows}
    assert by_symbol["000001"][9] == 1
    assert by_symbol["000001"][10] == 1
    assert by_symbol["000001"][11] == "[]"
    assert by_symbol["000001"][12] == "[]"
    assert by_symbol["000004"][9] == 0
    assert by_symbol["000004"][10] == 0
    assert by_symbol["000004"][11] == '["st_stock"]'
    assert by_symbol["002808"][9] == 0
    assert by_symbol["002808"][11] == '["delisting_period"]'
    assert by_symbol["920699"][9] == 1
    assert by_symbol["920699"][10] == 0
    assert by_symbol["920699"][11] == "[]"
    assert by_symbol["920699"][12] == '["daily_missing", "minute5_missing"]'
    assert by_symbol["920699"][14] == 1
    assert by_symbol["920699"][16] == 1
    assert by_symbol["000001"][18] == datetime(2026, 7, 2, 11, 40, 0)


def test_sync_stock_research_status_detects_delisting_prefix_names() -> None:
    class PrefixDelistingClient(FakeClient):
        def execute(self, query, params=None):
            self.commands.append((query, params))
            normalized = " ".join(query.lower().split())
            if normalized.startswith("select symbol, name, market, list_date from stocks"):
                return [("600193", "退市创兴", "SH", "1999-05-27")]
            if normalized.startswith("select max(date) from daily_kline"):
                return [(date(2026, 7, 1),)]
            if normalized.startswith("select max(todate(datetime)) from minute5_kline"):
                return [(date(2026, 7, 2),)]
            return []

    client = PrefixDelistingClient()

    sync_stock_research_status(client=client, checked_at="2026-07-02 11:40:00")

    _insert_query, rows = client.commands[-1]
    assert rows[0][5] == 1
    assert rows[0][9] == 0
    assert rows[0][11] == '["delisting_period"]'


def test_sync_stock_research_status_does_not_mark_no_trade_symbols_as_missing() -> None:
    class MissingKlineClient(FakeClient):
        def execute(self, query, params=None):
            self.commands.append((query, params))
            normalized = " ".join(query.lower().split())
            if normalized.startswith("select symbol, name, market, list_date from stocks"):
                return [
                    ("000524", "岭南控股", "SZ", "1993-11-18"),
                    ("920580", "科创新材", "BJ", ""),
                ]
            if normalized.startswith("select max(date) from daily_kline"):
                return [(date(2026, 7, 2),)]
            if normalized.startswith("select max(todate(datetime)) from minute5_kline"):
                return [(date(2026, 7, 2),)]
            return []

    class QuoteSource:
        def fetch_realtime_quotes(self, symbols):
            return pd.DataFrame([
                {
                    "symbol": "000524.SZ",
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "volume": 0,
                    "amount": 0.0,
                    "timestamp": pd.Timestamp("2026-07-02 16:04:12"),
                },
                {
                    "symbol": "920580.BJ",
                    "open": 11.0,
                    "high": 11.31,
                    "low": 10.86,
                    "volume": 20812,
                    "amount": 23134300.0,
                    "timestamp": pd.Timestamp("2026-07-02 15:35:30"),
                },
            ])

    client = MissingKlineClient()

    result = sync_stock_research_status(
        client=client,
        checked_at="2026-07-02 16:10:00",
        quote_source=QuoteSource(),
    )

    _insert_query, rows = client.commands[-1]
    by_symbol = {row[0]: row for row in rows}
    assert result["data_ready_rows"] == 1
    assert result["daily_missing_rows"] == 1
    assert by_symbol["000524"][10] == 1
    assert by_symbol["000524"][12] == "[]"
    assert by_symbol["000524"][14] == 0
    assert by_symbol["000524"][16] == 0
    assert by_symbol["920580"][10] == 0
    assert by_symbol["920580"][12] == '["daily_missing", "minute5_missing"]'
