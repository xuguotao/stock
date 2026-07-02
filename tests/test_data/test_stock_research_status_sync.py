from __future__ import annotations

from datetime import date, datetime

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
        "eligible_rows": 1,
        "excluded_rows": 3,
        "daily_missing_rows": 1,
        "minute5_missing_rows": 1,
        "daily_latest_date": "2026-07-01",
        "minute5_trade_date": "2026-07-02",
    }
    insert_query, rows = client.commands[-1]
    assert "insert into stock_research_status" in insert_query.lower()
    by_symbol = {row[0]: row for row in rows}
    assert by_symbol["000001"][9] == 1
    assert by_symbol["000001"][10] == "[]"
    assert by_symbol["000004"][9] == 0
    assert by_symbol["000004"][10] == '["st_stock"]'
    assert by_symbol["002808"][9] == 0
    assert by_symbol["002808"][10] == '["delisting_period"]'
    assert by_symbol["920699"][9] == 0
    assert by_symbol["920699"][10] == '["daily_missing", "minute5_missing"]'
    assert by_symbol["920699"][12] == 1
    assert by_symbol["920699"][14] == 1
    assert by_symbol["000001"][16] == datetime(2026, 7, 2, 11, 40, 0)
