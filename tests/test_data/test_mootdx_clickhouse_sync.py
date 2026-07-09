from __future__ import annotations

from datetime import date

import pandas as pd


class FakeClickHouse:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.inserts: list[tuple[str, list[tuple]]] = []

    def execute(self, sql: str, params=None):
        self.sql.append(sql)
        if "insert into" in sql.lower():
            self.inserts.append((sql, params or []))
        return []


class FakeSource:
    def fetch_stock_list(self):
        from src.data.models import StockInfo

        return [StockInfo(symbol="000001.SZ", code="000001", name="平安银行")]

    def fetch_realtime_quotes(self, symbols):
        return pd.DataFrame([
            {
                "symbol": symbols[0],
                "price": 10.5,
                "open": 10.1,
                "prev_close": 10.0,
                "high": 10.8,
                "low": 10.0,
                "volume": 100,
                "amount": 1000.0,
                "change_pct": 5.0,
                "timestamp": "2026-07-09 14:30:00",
            }
        ])

    def fetch_bars(self, symbol, start, end, frequency="daily"):
        return pd.DataFrame([
            {
                "date": date(2026, 7, 9),
                "open": 10.1,
                "high": 10.8,
                "low": 10.0,
                "close": 10.5,
                "volume": 100,
                "amount": 1000.0,
                "adjusted_close": 10.5,
                "symbol": symbol,
            }
        ])

    def fetch_intraday_bars(self, symbol, trade_date, frequency):
        return pd.DataFrame([
            {
                "datetime": pd.Timestamp("2026-07-09 14:45:00"),
                "time": pd.Timestamp("2026-07-09 14:45:00").time(),
                "symbol": symbol,
                "open": 10.1,
                "high": 10.8,
                "low": 10.0,
                "close": 10.5,
                "volume": 100,
                "amount": 1000.0,
            }
        ])

    def fetch_index_bars(self, symbol, frequency):
        return pd.DataFrame([
            {
                "datetime": pd.Timestamp("2026-07-09 15:00:00"),
                "open": 4000.0,
                "high": 4010.0,
                "low": 3990.0,
                "close": 4005.0,
                "volume": 100,
                "amount": 1000.0,
            }
        ])

    def fetch_xdxr(self, symbol):
        return pd.DataFrame([
            {
                "year": 2026,
                "month": 7,
                "day": 9,
                "category": 1,
                "name": "分红",
                "fenhong": 1.0,
            }
        ])

    def fetch_finance_frame(self, symbol):
        return pd.DataFrame([
            {
                "code": "000001",
                "industry": "银行",
                "updated_date": "20260709",
                "ipo_date": "19910403",
                "liutongguben": 1.0,
                "zongguben": 2.0,
                "zongzichan": 3.0,
                "jingzichan": 4.0,
                "zhuyingshouru": 5.0,
                "jinglirun": 6.0,
                "meigujingzichan": 7.0,
            }
        ])


def test_ensure_mootdx_tables_creates_only_prefixed_tables() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    joined = "\n".join(client.sql)
    assert "create table if not exists mootdx_sync_runs" in joined
    assert "create table if not exists mootdx_stock_catalog" in joined
    assert "create table if not exists mootdx_quote_snapshots" in joined
    assert "create table if not exists mootdx_stock_kline" in joined
    assert "create table if not exists mootdx_index_kline" in joined
    assert "create table if not exists stocks (" not in joined
    assert "create table if not exists daily_kline" not in joined
    assert "create table if not exists minute5_kline" not in joined


def test_sync_default_tasks_writes_only_mootdx_tables() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FakeSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        frequencies=["5m", "daily"],
        tasks=[
            "stock_catalog",
            "quote_snapshot",
            "stock_kline_daily",
            "stock_kline_intraday",
            "index_kline",
            "xdxr",
            "finance_snapshot",
        ],
        ensure_tables=False,
    )

    inserted_sql = "\n".join(sql for sql, _ in client.inserts)
    assert "insert into mootdx_stock_catalog" in inserted_sql
    assert "insert into mootdx_quote_snapshots" in inserted_sql
    assert "insert into mootdx_stock_kline" in inserted_sql
    assert "insert into mootdx_index_kline" in inserted_sql
    assert "insert into mootdx_xdxr" in inserted_sql
    assert "insert into mootdx_finance_snapshot" in inserted_sql
    assert "insert into daily_kline" not in inserted_sql
    assert "insert into minute5_kline" not in inserted_sql
    assert result["inserted"]["mootdx_stock_kline"] >= 2


def test_sync_extended_probe_tasks_write_probe_tables() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class ExtendedSource(FakeSource):
        def fetch_minutes(self, symbol, trade_date):
            return pd.DataFrame([{"price": 10.1, "vol": 100, "volume": 100}])

        def fetch_realtime_minute(self, symbol):
            return pd.DataFrame([{"price": 10.2, "vol": 120, "volume": 120}])

        def fetch_transactions(self, symbol, trade_date=None, start=0, offset=800):
            return pd.DataFrame([{"price": 10.2, "vol": 120, "volume": 120, "amount": 1224.0}])

        def fetch_f10_catalog(self, symbol):
            return pd.DataFrame([{"title": "最新提示"}])

        def fetch_f10_detail(self, symbol, title):
            return "公司经营正常"

        def fetch_affair_files(self):
            return [{"filename": "gpcw20260331.zip", "hash": "abc", "filesize": 123}]

    client = FakeClickHouse()
    sync_mootdx_offline_data(
        client=client,
        source=ExtendedSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=[
            "minutes_probe",
            "realtime_minute_probe",
            "transaction_probe",
            "historical_transaction_probe",
            "f10_catalog_probe",
            "f10_detail_probe",
            "affair_file_list_probe",
        ],
        ensure_tables=False,
    )

    inserted_sql = "\n".join(sql for sql, _ in client.inserts)
    assert "insert into mootdx_minutes" in inserted_sql
    assert "insert into mootdx_transactions" in inserted_sql
    assert "insert into mootdx_f10_catalog" in inserted_sql
    assert "insert into mootdx_f10_detail" in inserted_sql
    assert "insert into mootdx_affair_files" in inserted_sql


def test_insert_kline_rows_batches_by_partition() -> None:
    from src.data.mootdx_clickhouse_sync import _insert_rows

    client = FakeClickHouse()
    rows = [
        (pd.Timestamp("2026-07-09 15:00").to_pydatetime(), date(2026, 7, 9), "daily", "000001.SH"),
        (pd.Timestamp("2026-07-10 15:00").to_pydatetime(), date(2026, 7, 10), "daily", "000001.SH"),
        (pd.Timestamp("2026-07-10 09:35").to_pydatetime(), date(2026, 7, 10), "5m", "000001.SH"),
    ]

    _insert_rows(client, "mootdx_index_kline", rows)

    assert [len(params) for _, params in client.inserts] == [1, 1, 1]


class _CatalogClient:
    """Fake ClickHouse that returns canned latest catalog rows for SELECTs."""

    def __init__(self, latest_rows: list[tuple]) -> None:
        self.sql: list[str] = []
        self.inserts: list[tuple[str, list[tuple]]] = []
        self._latest_rows = latest_rows

    def execute(self, sql: str, params=None):
        self.sql.append(sql)
        if "insert into" in sql.lower():
            self.inserts.append((sql, params or []))
            return []
        return self._latest_rows


def test_stock_catalog_skips_unchanged_symbols() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    # existing latest matches FakeSource exactly (market SZ=0, code, name, is_st=0)
    client = _CatalogClient([("000001.SZ", 0, "000001", "平安银行", 0)])
    result = sync_mootdx_offline_data(
        client=client,
        source=FakeSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_catalog"],
        ensure_tables=False,
    )

    assert result["inserted"].get("mootdx_stock_catalog", 0) == 0
    assert not any("mootdx_stock_catalog" in sql for sql, _ in client.inserts)
    assert not any("optimize" in s.lower() for s in client.sql)


def test_stock_catalog_inserts_changed_symbols() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    # existing name differs from FakeSource ("平安银行")
    client = _CatalogClient([("000001.SZ", 0, "000001", "旧名称", 0)])
    result = sync_mootdx_offline_data(
        client=client,
        source=FakeSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_catalog"],
        ensure_tables=False,
    )

    assert result["inserted"]["mootdx_stock_catalog"] == 1
    assert any("optimize" in s.lower() and "mootdx_stock_catalog" in s for s in client.sql)
