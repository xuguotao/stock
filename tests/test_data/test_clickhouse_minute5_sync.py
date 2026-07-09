from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import patch

import pandas as pd

import src.data.clickhouse_minute5_sync as clickhouse_minute5_sync
from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_history_window, sync_clickhouse_minute5_kline


class FakeClickHouseClient:
    def __init__(
        self,
        *,
        complete_symbols: set[str] | None = None,
        latest_by_symbol: dict[str, datetime] | None = None,
    ) -> None:
        self.complete_symbols = complete_symbols or set()
        self.latest_by_symbol = latest_by_symbol or {}
        self.existing_by_symbol: dict[str, set[datetime]] = {
            symbol: {latest} for symbol, latest in self.latest_by_symbol.items()
        }
        self.inserts: list[list[tuple]] = []
        self.calls: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized:
            if "where symbol in" in normalized:
                # _stock_names query - return 2 values
                return [
                    ("000001", "平安银行"),
                    ("000004", "*ST国华"),
                    ("600000", "浦发银行"),
                ][:len(params.get("symbols", []))]
            else:
                # _target_symbols query - return 3 values
                return [
                    ("000001", "平安银行", "SZ"),
                    ("000004", "*ST国华", "SZ"),
                    ("600000", "浦发银行", "SH"),
                ]
        if "select distinct symbol from minute5_kline" in normalized:
            return [(symbol,) for symbol in sorted(self.complete_symbols)]
        if "max(datetime)" in normalized and "group by symbol" in normalized:
            return [
                (symbol, max(values), len(values))
                for symbol, values in sorted(self.existing_by_symbol.items())
                if values
            ]
        if "grouparray(datetime)" in normalized and "group by symbol" in normalized:
            return [
                (symbol, sorted(values))
                for symbol, values in sorted(self.existing_by_symbol.items())
                if values
            ]
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


class FakeBatchSource:
    def __init__(self) -> None:
        self.batch_calls: list[tuple[list[str], date, str]] = []
        self.single_calls: list[str] = []

    def fetch_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.batch_calls.append((symbols, trade_date, frequency))
        return pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                    "symbol": symbol,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10100.0,
                }
                for symbol in symbols
            ]
        )

    def fetch_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.single_calls.append(symbol)
        return pd.DataFrame()


class FakeFutureBucketBatchSource:
    def fetch_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                    "symbol": symbol,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10100.0,
                }
                for symbol in symbols
            ]
            + [
                {
                    "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:05:00"),
                    "symbol": symbol,
                    "open": 10.1,
                    "high": 10.3,
                    "low": 10.0,
                    "close": 10.2,
                    "volume": 1200,
                    "amount": 12240.0,
                }
                for symbol in symbols
            ]
        )


class FakeDuplicateBatchSource:
    def fetch_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        return pd.DataFrame([
            {
                "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                "symbol": symbols[0],
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000,
                "amount": 10100.0,
            },
            {
                "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                "symbol": symbols[0],
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 1200,
                "amount": 12240.0,
            },
        ])


class FakeGapSource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        self.calls.append(symbol)
        return pd.DataFrame([
            {
                "datetime": pd.Timestamp(f"{trade_date.isoformat()} 14:50:00"),
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000,
                "amount": 10100.0,
            },
            {
                "datetime": pd.Timestamp(f"{trade_date.isoformat()} 14:55:00"),
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 1200,
                "amount": 12240.0,
            },
            {
                "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                "open": 10.2,
                "high": 10.4,
                "low": 10.1,
                "close": 10.3,
                "volume": 1300,
                "amount": 13390.0,
            },
        ])


class FakeWindowSource:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], date, date, str]] = []

    def fetch_intraday_bars_window(
        self,
        symbols: list[str],
        start: date,
        end: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        self.calls.append((symbols, start, end, frequency))
        return pd.DataFrame([
            {
                "symbol": "000001.SZ",
                "datetime": pd.Timestamp("2026-06-10 14:55:00"),
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000,
                "amount": 10100.0,
            },
            {
                "symbol": "000001.SZ",
                "datetime": pd.Timestamp("2026-06-10 15:00:00"),
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 1200,
                "amount": 12240.0,
            },
            {
                "symbol": "600000.SH",
                "datetime": pd.Timestamp("2026-06-11 15:00:00"),
                "open": 20.0,
                "high": 20.5,
                "low": 19.8,
                "close": 20.2,
                "volume": 2000,
                "amount": 40400.0,
            },
        ])


class FakePartialWindowSource:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], date, date, str]] = []

    def fetch_intraday_bars_window(
        self,
        symbols: list[str],
        start: date,
        end: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        self.calls.append((symbols, start, end, frequency))
        return pd.DataFrame([
            {
                "symbol": "000001.SZ",
                "datetime": pd.Timestamp("2026-06-10 15:00:00"),
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000,
                "amount": 10100.0,
            },
        ])


class FakeHistoryFallbackSource:
    def __init__(self) -> None:
        self.batch_calls: list[tuple[list[str], date, str]] = []

    def fetch_intraday_bars_batch(
        self,
        symbols: list[str],
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        self.batch_calls.append((symbols, trade_date, frequency))
        return pd.DataFrame([
            {
                "symbol": symbol,
                "datetime": pd.Timestamp(f"{trade_date.isoformat()} 15:00:00"),
                "open": 20.0,
                "high": 20.2,
                "low": 19.9,
                "close": 20.1,
                "volume": 2000,
                "amount": 40200.0,
            }
            for symbol in symbols
        ])


class FakeEmptyWindowSource:
    def fetch_intraday_bars_window(
        self,
        symbols: list[str],
        start: date,
        end: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        return pd.DataFrame()


def _complete_5m_datetimes(trade_date: date, until: time = time(15, 0)) -> set[datetime]:
    values = set()
    current = datetime.combine(trade_date, time(9, 35))
    while current <= datetime.combine(trade_date, min(until, time(11, 30))):
        values.add(current)
        current += pd.Timedelta(minutes=5).to_pytimedelta()
    if until >= time(13, 5):
        current = datetime.combine(trade_date, time(13, 5))
        while current <= datetime.combine(trade_date, until):
            values.add(current)
            current += pd.Timedelta(minutes=5).to_pytimedelta()
    return values


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
            ("600000", datetime(2026, 6, 12, 14, 55), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
            ("600000", datetime(2026, 6, 12, 15, 0), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0),
        ],
    ]


def test_sync_clickhouse_minute5_kline_respects_complete_symbols_and_limit() -> None:
    client = FakeClickHouseClient(latest_by_symbol={"000001": datetime(2026, 6, 12, 15, 0)})
    client.existing_by_symbol["000001"] = _complete_5m_datetimes(date(2026, 6, 12))
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


def test_sync_clickhouse_minute5_kline_can_process_partial_batch() -> None:
    client = FakeClickHouseClient()
    source = FakeSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
        max_fetch_symbols=1,
    )

    assert source.calls == ["000001.SZ"]
    assert result["partial"] is True
    assert result["remaining_symbols"] == 1
    assert result["success"] == 1


def test_sync_clickhouse_minute5_kline_skips_symbols_current_to_target_time() -> None:
    client = FakeClickHouseClient(
        latest_by_symbol={
            "000001": datetime(2026, 6, 12, 14, 10),
            "600000": datetime(2026, 6, 12, 14, 5),
        }
    )
    client.existing_by_symbol["000001"] = _complete_5m_datetimes(date(2026, 6, 12), time(14, 10))
    source = FakeSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
        target_time=time(14, 10),
    )

    assert source.calls == ["600000.SH"]
    assert result["target_datetime"] == "2026-06-12 14:10:00"
    assert result["skipped"] == 1


def test_sync_clickhouse_minute5_kline_only_inserts_rows_after_latest_datetime() -> None:
    client = FakeClickHouseClient(latest_by_symbol={"600000": datetime(2026, 6, 12, 14, 55)})
    source = FakeSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["600000.SH"],
        target_time=time(15, 0),
    )

    group_array_queries = [
        query for query, _ in client.calls
        if "grouparray(datetime)" in " ".join(query.lower().split())
    ]

    assert result["inserted_rows"] == 1
    assert client.inserts == [[("600000", datetime(2026, 6, 12, 15, 0), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0)]]
    assert group_array_queries == []


def test_sync_clickhouse_minute5_kline_queries_existing_datetimes_only_for_gap_symbols() -> None:
    client = FakeClickHouseClient(
        latest_by_symbol={
            "000001": datetime(2026, 6, 12, 15, 0),
            "600000": datetime(2026, 6, 12, 14, 55),
        }
    )
    source = FakeSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
        target_time=time(15, 0),
    )

    group_array_params = [
        params for query, params in client.calls
        if "grouparray(datetime)" in " ".join(query.lower().split())
    ]

    assert result["inserted_rows"] == 2
    assert group_array_params == [{"symbols": ("000001",), "start": datetime(2026, 6, 12, 0, 0), "end": datetime(2026, 6, 12, 23, 59, 59)}]


def test_sync_clickhouse_minute5_kline_fills_gaps_when_latest_reaches_close() -> None:
    client = FakeClickHouseClient(latest_by_symbol={"600000": datetime(2026, 6, 12, 15, 0)})
    source = FakeGapSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["600000.SH"],
        target_time=time(15, 0),
    )

    assert source.calls == ["600000.SH"]
    assert result["inserted_rows"] == 2
    assert client.inserts == [[
        ("600000", datetime(2026, 6, 12, 14, 50), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
        ("600000", datetime(2026, 6, 12, 14, 55), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0),
    ]]


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


def test_sync_clickhouse_minute5_kline_recent_intraday_skips_akshare_fallback() -> None:
    client = FakeClickHouseClient()
    created_sources: list[str] = []

    class FakeTencentSource(FakeSource):
        def __init__(self, rate_limit: float) -> None:
            super().__init__()
            created_sources.append(f"tencent:{rate_limit}")

    class FakeSinaSource(FakeSource):
        def __init__(self, rate_limit: float, intraday_datalen: int) -> None:
            super().__init__()
            created_sources.append(f"sina:{rate_limit}:{intraday_datalen}")

    class FakeAKShareSource(FakeSource):
        def __init__(self, rate_limit: float) -> None:
            super().__init__()
            created_sources.append(f"akshare:{rate_limit}")

    with (
        patch.object(clickhouse_minute5_sync, "TencentQuoteSource", FakeTencentSource),
        patch.object(clickhouse_minute5_sync, "SinaSource", FakeSinaSource),
        patch.object(clickhouse_minute5_sync, "AKShareSource", FakeAKShareSource),
        patch.object(clickhouse_minute5_sync, "date") as fake_date,
    ):
        fake_date.today.return_value = date(2026, 6, 17)
        fake_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        result = sync_clickhouse_minute5_kline(
            client=client,
            trade_date=date(2026, 6, 12),
            symbols=["000001.SZ"],
        )

    assert created_sources == ["tencent:0.0", "sina:0.2:10000"]
    assert result["success"] == 1


def test_sync_clickhouse_minute5_kline_prefers_sina_for_older_history() -> None:
    client = FakeClickHouseClient()
    created_sources: list[str] = []

    class FakeTencentSource(FakeSource):
        def __init__(self, rate_limit: float) -> None:
            super().__init__()
            created_sources.append(f"tencent:{rate_limit}")

    class FakeSinaSource(FakeSource):
        def __init__(self, rate_limit: float, intraday_datalen: int) -> None:
            super().__init__()
            created_sources.append(f"sina:{rate_limit}:{intraday_datalen}")

    class FakeAKShareSource(FakeSource):
        def __init__(self, rate_limit: float) -> None:
            super().__init__()
            created_sources.append(f"akshare:{rate_limit}")

    with (
        patch.object(clickhouse_minute5_sync, "TencentQuoteSource", FakeTencentSource),
        patch.object(clickhouse_minute5_sync, "SinaSource", FakeSinaSource),
        patch.object(clickhouse_minute5_sync, "AKShareSource", FakeAKShareSource),
        patch.object(clickhouse_minute5_sync, "date") as fake_date,
    ):
        fake_date.today.return_value = date(2026, 6, 17)
        fake_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        result = sync_clickhouse_minute5_kline(
            client=client,
            trade_date=date(2026, 6, 5),
            symbols=["000001.SZ"],
        )

    assert created_sources == ["sina:0.2:10000", "tencent:0.0", "akshare:0.2"]
    assert result["success"] == 1


def test_sync_clickhouse_minute5_kline_uses_batch_intraday_fetcher_when_available() -> None:
    client = FakeClickHouseClient()
    source = FakeBatchSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
    )

    assert source.batch_calls == [(["000001.SZ", "600000.SH"], date(2026, 6, 12), "5m")]
    assert source.single_calls == []
    assert result["success"] == 2
    assert result["inserted_rows"] == 2


def test_sync_clickhouse_minute5_kline_batches_clickhouse_inserts_across_symbols() -> None:
    client = FakeClickHouseClient()
    source = FakeBatchSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
        target_time=time(15, 0),
    )

    assert result["success"] == 2
    assert result["inserted_rows"] == 2
    assert len(client.inserts) == 1
    assert client.inserts[0] == [
        ("000001", datetime(2026, 6, 12, 15, 0), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
        ("600000", datetime(2026, 6, 12, 15, 0), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
    ]


def test_sync_clickhouse_minute5_kline_does_not_insert_future_bucket_rows() -> None:
    client = FakeClickHouseClient()
    source = FakeFutureBucketBatchSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
        target_time=time(15, 0),
    )

    assert result["success"] == 2
    assert result["inserted_rows"] == 2
    inserted_datetimes = [row[1] for batch in client.inserts for row in batch]
    assert inserted_datetimes == [datetime(2026, 6, 12, 15, 0), datetime(2026, 6, 12, 15, 0)]


def test_sync_clickhouse_minute5_kline_deduplicates_rows_within_insert_batch() -> None:
    client = FakeClickHouseClient()
    source = FakeDuplicateBatchSource()

    result = sync_clickhouse_minute5_kline(
        client=client,
        trade_date=date(2026, 6, 12),
        source=source,
        symbols=["000001.SZ"],
        target_time=time(15, 0),
    )

    assert result["success"] == 1
    assert result["inserted_rows"] == 1
    assert client.inserts == [[
        ("000001", datetime(2026, 6, 12, 15, 0), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0),
    ]]


def test_sync_clickhouse_minute5_history_window_fetches_once_and_inserts_missing_rows() -> None:
    client = FakeClickHouseClient()
    client.existing_by_symbol["000001"] = {datetime(2026, 6, 10, 14, 55)}
    source = FakeWindowSource()

    result = sync_clickhouse_minute5_history_window(
        client=client,
        start=date(2026, 6, 10),
        end=date(2026, 6, 11),
        source=source,
        symbols=["000001.SZ", "600000.SH"],
    )

    assert source.calls == [(["000001.SZ", "600000.SH"], date(2026, 6, 10), date(2026, 6, 11), "5m")]
    assert result["target_symbols"] == 2
    assert result["inserted_rows"] == 2
    assert client.inserts == [[
        ("000001", datetime(2026, 6, 10, 15, 0), 10.1, 10.3, 10.0, 10.2, 1200.0, 12240.0),
        ("600000", datetime(2026, 6, 11, 15, 0), 20.0, 20.5, 19.8, 20.2, 2000.0, 40400.0),
    ]]


def test_sync_clickhouse_minute5_history_window_uses_batch_fallback_for_symbols_missing_from_window_source() -> None:
    client = FakeClickHouseClient()
    source = FakePartialWindowSource()
    fallback = FakeHistoryFallbackSource()

    result = sync_clickhouse_minute5_history_window(
        client=client,
        start=date(2026, 6, 10),
        end=date(2026, 6, 10),
        source=source,
        fallback_sources=[fallback],
        symbols=["000001.SZ", "600000.SH"],
    )

    assert source.calls == [(["000001.SZ", "600000.SH"], date(2026, 6, 10), date(2026, 6, 10), "5m")]
    assert fallback.batch_calls == [(["600000.SH"], date(2026, 6, 10), "5m")]
    assert result["target_symbols"] == 2
    assert result["inserted_rows"] == 2
    assert result["no_data"] == 0
    assert client.inserts == [[
        ("000001", datetime(2026, 6, 10, 15, 0), 10.0, 10.2, 9.9, 10.1, 1000.0, 10100.0),
        ("600000", datetime(2026, 6, 10, 15, 0), 20.0, 20.2, 19.9, 20.1, 2000.0, 40200.0),
    ]]


def test_sync_clickhouse_minute5_history_window_reports_no_data_symbols() -> None:
    client = FakeClickHouseClient()

    result = sync_clickhouse_minute5_history_window(
        client=client,
        start=date(2026, 6, 10),
        end=date(2026, 6, 10),
        source=FakeEmptyWindowSource(),
        fallback_sources=[],
        symbols=["000001.SZ", "600000.SH"],
    )

    assert result["inserted_rows"] == 0
    assert result["no_data"] == 2
    assert result["no_data_symbols"] == ["000001.SZ", "600000.SH"]
    assert client.inserts == []
