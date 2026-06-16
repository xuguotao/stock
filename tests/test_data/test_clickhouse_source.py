from __future__ import annotations

from datetime import date, datetime

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.models import StockInfo


class FakeClickHouseClient:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if "from stocks" in query:
            return [
                ("000001", "平安银行", "银行", "SZ", date(1991, 4, 3)),
                ("600519", "贵州茅台", "白酒", "SH", date(2001, 8, 27)),
            ]
        if "avg(amount)" in query:
            return [
                ("600519", 120, date(2026, 6, 15), 500_000_000.0, 1_000_000.0),
                ("000001", 120, date(2026, 6, 15), 200_000_000.0, 2_000_000.0),
            ]
        if "from daily_kline" in query:
            return [
                ("000001", date(2026, 6, 12), 10.0, 10.5, 9.9, 10.2, 1000, 10200.0),
                ("000001", date(2026, 6, 15), 10.2, 10.8, 10.1, 10.6, 1200, 12600.0),
            ]
        if "from minute5_kline" in query:
            return [
                ("000001", datetime(2026, 6, 15, 14, 30), 10.0, 10.2, 9.9, 10.1, 1000, 10100.0),
                ("000001", datetime(2026, 6, 15, 14, 35), 10.1, 10.3, 10.0, 10.2, 1200, 12240.0),
            ]
        return []


def test_clickhouse_source_reads_stock_list() -> None:
    source = ClickHouseStockDataSource(client=FakeClickHouseClient())

    result = source.fetch_stock_list()

    assert result == [
        StockInfo(
            symbol="000001.SZ",
            code="000001",
            name="平安银行",
            industry="银行",
            list_date=date(1991, 4, 3),
        ),
        StockInfo(
            symbol="600519.SH",
            code="600519",
            name="贵州茅台",
            industry="白酒",
            list_date=date(2001, 8, 27),
        ),
    ]


def test_clickhouse_source_reads_daily_bars() -> None:
    client = FakeClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_bars("000001.SZ", date(2026, 6, 12), date(2026, 6, 15))

    assert client.calls[-1][1] == {
        "symbol": "000001",
        "start": date(2026, 6, 12),
        "end": date(2026, 6, 15),
    }
    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert result["date"].tolist() == [date(2026, 6, 12), date(2026, 6, 15)]
    assert result["close"].tolist() == [10.2, 10.6]
    assert result["adjusted_close"].tolist() == [10.2, 10.6]


def test_clickhouse_source_reads_5m_intraday_bars() -> None:
    client = FakeClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 15), "5m")

    assert client.calls[-1][1] == {
        "symbol": "000001",
        "start": datetime(2026, 6, 15, 0, 0),
        "end": datetime(2026, 6, 15, 23, 59, 59),
    }
    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert result["time"].tolist() == [
        datetime(2026, 6, 15, 14, 30).time(),
        datetime(2026, 6, 15, 14, 35).time(),
    ]
    assert result["close"].tolist() == [10.1, 10.2]


def test_clickhouse_source_ranks_liquid_symbols() -> None:
    client = FakeClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.rank_liquid_symbols(
        start=date(2026, 1, 1),
        end=date(2026, 6, 15),
        limit=2,
        min_bars=120,
        min_end_date=date(2026, 6, 15),
    )

    assert client.calls[-1][1] == {
        "start": date(2026, 1, 1),
        "end": date(2026, 6, 15),
        "min_bars": 120,
        "limit": 2,
        "min_end_date": date(2026, 6, 15),
    }
    assert [row["symbol"] for row in result] == ["600519.SH", "000001.SZ"]
    assert result[0]["bars"] == 120
    assert result[0]["avg_amount"] == 500_000_000.0


def test_clickhouse_source_returns_empty_for_unsupported_frequency() -> None:
    source = ClickHouseStockDataSource(client=FakeClickHouseClient())

    assert source.fetch_bars("000001.SZ", date(2026, 6, 12), date(2026, 6, 15), "weekly").empty
    assert source.fetch_intraday_bars("000001.SZ", date(2026, 6, 15), "1m").empty
