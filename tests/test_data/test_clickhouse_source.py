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
        if "from stock_quote_snapshots_5m" in query:
            symbols = set((params or {}).get("symbols") or ())
            if "600519" not in symbols:
                return []
            return [
                ("600519", datetime(2026, 6, 15, 14, 30), 1200.0, 1205.0, 1198.0, 1202.0, 100, 120200.0),
                ("600519", datetime(2026, 6, 15, 14, 35), 1202.0, 1208.0, 1201.0, 1206.0, 120, 144720.0),
            ]
        if "from stock_quote_snapshots" in query:
            return [
                (
                    "000001",
                    "平安银行",
                    10.8,
                    1.92,
                    1000000,
                    10800000.0,
                    0.83,
                    4.88,
                    0.46,
                    210_000_000_000.0,
                    205_000_000_000.0,
                    11.88,
                    9.72,
                    datetime(2026, 6, 15, 14, 58),
                    datetime(2026, 6, 15, 14, 57, 55),
                ),
            ]
        return []


class GapFillingClickHouseClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        self.calls.append((query, params))
        if "from minute5_kline" in query:
            return [
                ("000001", datetime(2026, 6, 15, 14, 30), 10.0, 10.2, 9.9, 10.1, 1000, 10100.0),
                ("000001", datetime(2026, 6, 15, 14, 35), 10.1, 10.3, 10.0, 10.2, 1200, 12240.0),
            ]
        if "from stock_quote_snapshots_5m" in query:
            symbols = set((params or {}).get("symbols") or ())
            if "000001" not in symbols:
                return []
            return [
                ("000001", datetime(2026, 6, 15, 14, 35), 10.1, 10.4, 10.0, 10.25, 1300, 13325.0),
                ("000001", datetime(2026, 6, 15, 14, 40), 10.25, 10.5, 10.2, 10.45, 1500, 15675.0),
                ("000001", datetime(2026, 6, 15, 14, 45), 10.45, 10.6, 10.4, 10.55, 1600, 16880.0),
            ]
        return super().execute(query, params)


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

    assert client.calls[0][1] == {
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


def test_clickhouse_source_reads_5m_intraday_bars_batch() -> None:
    client = FakeClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_intraday_bars_batch(["000001.SZ", "600519.SH"], date(2026, 6, 15), "5m")

    assert client.calls[0][1] == {
        "symbols": ("000001", "600519"),
        "start": datetime(2026, 6, 15, 0, 0),
        "end": datetime(2026, 6, 15, 23, 59, 59),
    }
    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ", "600519.SH", "600519.SH"]
    assert result["close"].tolist() == [10.1, 10.2, 1202.0, 1206.0]


def test_clickhouse_source_uses_quote_snapshot_5m_for_missing_intraday_symbols() -> None:
    client = FakeClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_intraday_bars_batch(["000001.SZ", "600519.SH"], date(2026, 6, 15), "5m")

    assert any("from stock_quote_snapshots_5m final" in query.lower() for query, _params in client.calls)
    assert sorted(result["symbol"].unique().tolist()) == ["000001.SZ", "600519.SH"]
    fallback = result[result["symbol"] == "600519.SH"]
    assert fallback["datetime"].tolist() == [
        datetime(2026, 6, 15, 14, 30),
        datetime(2026, 6, 15, 14, 35),
    ]
    assert fallback["close"].tolist() == [1202.0, 1206.0]


def test_clickhouse_source_fills_newer_5m_buckets_from_quote_snapshots() -> None:
    client = GapFillingClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_intraday_bars_batch(["000001.SZ"], date(2026, 6, 15), "5m")

    assert result["datetime"].tolist() == [
        datetime(2026, 6, 15, 14, 30),
        datetime(2026, 6, 15, 14, 35),
        datetime(2026, 6, 15, 14, 40),
        datetime(2026, 6, 15, 14, 45),
    ]
    assert result["close"].tolist() == [10.1, 10.2, 10.45, 10.55]


def test_clickhouse_source_fills_single_symbol_newer_5m_buckets_from_quote_snapshots() -> None:
    client = GapFillingClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 15), "5m")

    assert any("from stock_quote_snapshots_5m final" in query.lower() for query, _params in client.calls)
    assert result["datetime"].tolist() == [
        datetime(2026, 6, 15, 14, 30),
        datetime(2026, 6, 15, 14, 35),
        datetime(2026, 6, 15, 14, 40),
        datetime(2026, 6, 15, 14, 45),
    ]
    assert result["close"].tolist() == [10.1, 10.2, 10.45, 10.55]


def test_clickhouse_source_reads_latest_quote_snapshots() -> None:
    client = FakeClickHouseClient()
    source = ClickHouseStockDataSource(client=client)

    result = source.fetch_latest_quote_snapshots(["000001.SZ"], date(2026, 6, 15))

    assert client.calls[-1][1] == {"symbols": ("000001.SZ",), "trade_date": date(2026, 6, 15)}
    assert result["symbol"].tolist() == ["000001.SZ"]
    assert result["price"].tolist() == [10.8]
    assert result["change_pct"].tolist() == [1.92]
    assert result["pe_ttm"].tolist() == [4.88]
    assert result["pb"].tolist() == [0.46]
    assert result["mcap"].tolist() == [210_000_000_000.0]
    assert str(result["quote_time"].iloc[0]) == "2026-06-15 14:57:55"


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
