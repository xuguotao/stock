from __future__ import annotations

from datetime import date, datetime

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

    def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
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


class EmptyDailySource(FakeSource):
    def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
        return pd.DataFrame()


class BaostockBars:
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None) -> None:
        self._frame = frame if frame is not None else pd.DataFrame()
        self._error = error

    def fetch_daily_bars(self, symbol, start_date, end_date):
        if self._error:
            raise self._error
        return self._frame.copy()


def test_ensure_mootdx_tables_creates_only_prefixed_tables() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    joined = "\n".join(client.sql)
    assert "create table if not exists mootdx_sync_runs" in joined
    assert "create table if not exists mootdx_stock_catalog" in joined
    assert "is_active UInt8 default 1" in joined
    assert "alter table mootdx_stock_catalog add column if not exists is_active" in joined
    assert "create table if not exists mootdx_quote_snapshots" in joined
    assert "create table if not exists mootdx_stock_kline" in joined
    assert "create table if not exists mootdx_index_kline" in joined
    assert "create table if not exists stocks (" not in joined
    assert "create table if not exists daily_kline" not in joined
    assert "create table if not exists minute5_kline" not in joined


def test_ensure_mootdx_tables_creates_daily_gap_verifications() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    assert any("create table if not exists mootdx_daily_gap_verifications" in sql.lower() for sql in client.sql)


def test_insert_catalog_rows_uses_explicit_lifecycle_column_order() -> None:
    from src.data.mootdx_clickhouse_sync import _insert_rows

    client = FakeClickHouse()
    _insert_rows(
        client,
        "mootdx_stock_catalog",
        [(datetime(2026, 7, 15), 0, "000001.SZ", "000001", "平安银行", 0, 1, 0, None, None, None, "mootdx", "{}")],
    )

    sql, rows = client.inserts[0]
    assert "insert into mootdx_stock_catalog (captured_at, market, symbol, code, name, is_st, is_active" in sql.lower()
    assert rows[0][6:8] == (1, 0)


def test_ensure_mootdx_tables_makes_xdxr_numeric_fields_nullable() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    joined = "\n".join(client.sql).lower()
    assert "fenhong nullable(float64)" in joined
    assert "suogu nullable(float64)" in joined
    assert any(
        "alter table mootdx_xdxr modify column suogu nullable(float64)" in sql.lower()
        for sql in client.sql
    )


def test_ensure_mootdx_tables_creates_daily_xdxr_events_view() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    view_sql = "\n".join(sql for sql in client.sql if "mootdx_daily_xdxr_events_view" in sql).lower()
    assert "create view if not exists mootdx_daily_xdxr_events_view" in view_sql
    assert "mootdx_stock_kline final" in view_sql
    assert "mootdx_xdxr final" in view_sql
    assert "groupuniqarray(category)" in view_sql
    assert "countif(category = 1)" in view_sql
    assert "k.symbol = e.symbol and k.trade_date = e.event_date" in view_sql


def test_ensure_mootdx_tables_creates_xdxr_symbol_audit_with_array_columns_and_ttl() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    audit_sql = next(sql.lower() for sql in client.sql if "create table if not exists mootdx_xdxr_symbol_runs" in sql.lower())
    assert "raw_columns array(string)" in audit_sql
    assert "ttl requested_at + interval 365 day delete" in audit_sql
    assert any(
        "alter table mootdx_xdxr_symbol_runs modify ttl requested_at + interval 365 day delete" in sql.lower()
        for sql in client.sql
    )


def test_ensure_mootdx_tables_migrates_legacy_xdxr_audit_string_column_without_data_loss() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    class LegacyAuditClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            super().execute(sql, params)
            if "from system.columns" in sql.lower():
                return [("String",)]
            return []

    client = LegacyAuditClient()
    ensure_mootdx_tables(client)

    sql = "\n".join(client.sql).lower()
    assert "rename column raw_columns to raw_columns_json" in sql
    assert "add column if not exists raw_columns array(string) default []" in sql


def test_ensure_mootdx_tables_adds_typed_xdxr_audit_column_after_interrupted_migration() -> None:
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    client = FakeClickHouse()
    ensure_mootdx_tables(client)

    assert any(
        "alter table mootdx_xdxr_symbol_runs add column if not exists raw_columns array(string) default []" in sql.lower()
        for sql in client.sql
    )


def test_daily_sync_backfills_mootdx_miss_from_baostock() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=EmptyDailySource(),
        baostock_source=BaostockBars(pd.DataFrame([{
            "date": date(2026, 6, 24), "symbol": "000001.SZ", "open": 10.1, "high": 10.8,
            "low": 10.0, "close": 10.5, "volume": 100, "amount": 1234.5, "tradestatus": 1,
        }])),
        symbols=["000001.SZ"],
        trade_date=date(2026, 6, 24),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    kline_rows = next(rows for sql, rows in client.inserts if "insert into mootdx_stock_kline" in sql.lower())
    verification_rows = next(rows for sql, rows in client.inserts if "insert into mootdx_daily_gap_verifications" in sql.lower())
    assert kline_rows[0][10] == "baostock"
    assert verification_rows[0][5] == "available"
    assert result["diagnostics"]["stock_kline_daily"]["baostock"]["available"] == 1


def test_daily_sync_records_baostock_no_data_and_error_separately() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    no_data_client = FakeClickHouse()
    no_data_result = sync_mootdx_offline_data(
        client=no_data_client, source=EmptyDailySource(), baostock_source=BaostockBars(), symbols=["000001.SZ"],
        trade_date=date(2026, 6, 24), tasks=["stock_kline_daily"], ensure_tables=False,
    )
    error_client = FakeClickHouse()
    sync_mootdx_offline_data(
        client=error_client, source=EmptyDailySource(), baostock_source=BaostockBars(error=RuntimeError("network")), symbols=["000001.SZ"],
        trade_date=date(2026, 6, 24), tasks=["stock_kline_daily"], ensure_tables=False,
    )

    no_data_rows = next(rows for sql, rows in no_data_client.inserts if "insert into mootdx_daily_gap_verifications" in sql.lower())
    error_rows = next(rows for sql, rows in error_client.inserts if "insert into mootdx_daily_gap_verifications" in sql.lower())
    assert no_data_rows[0][5] == "no_data"
    assert error_rows[0][5] == "error"
    assert no_data_result["diagnostics"]["stock_kline_daily"]["coverage_rate"] == 1.0
    assert no_data_result["diagnostics"]["stock_kline_daily"]["audit"] == {"status": "healthy", "reasons": []}


def test_daily_sync_treats_baostock_suspension_placeholder_as_no_data() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    client = FakeClickHouse()
    sync_mootdx_offline_data(
        client=client,
        source=EmptyDailySource(),
        baostock_source=BaostockBars(pd.DataFrame([{
            "date": date(2026, 6, 24), "symbol": "000524.SZ", "open": 8.95, "high": 8.95,
            "low": 8.95, "close": 8.95, "volume": 0, "amount": None, "tradestatus": 0,
        }])),
        symbols=["000524.SZ"],
        trade_date=date(2026, 6, 24),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert not any("insert into mootdx_stock_kline" in sql.lower() for sql, _ in client.inserts)
    verification_rows = next(rows for sql, rows in client.inserts if "insert into mootdx_daily_gap_verifications" in sql.lower())
    assert verification_rows[0][5] == "no_data"


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


def test_stock_catalog_uses_source_as_authoritative_pool_and_reports_changes() -> None:
    from src.data.models import StockInfo
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class CatalogClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "argmax(market, captured_at), argmax(is_st" in sql.lower():
                return [("600001.SH", 1, 0)]
            if "argmax(market, captured_at), argmax(code" in sql.lower():
                return [("600001.SH", 1, "600001", "浦发银行", 0)]
            return []

    class Source(FakeSource):
        def fetch_stock_list(self):
            return [
                StockInfo(symbol="001234.SZ", code="001234", name="新上市"),
                StockInfo(symbol="600001.SH", code="600001", name="浦发银行"),
            ]

    client = CatalogClient()
    result = sync_mootdx_offline_data(
        client=client,
        source=Source(),
        trade_date=date(2026, 7, 9),
        tasks=["stock_catalog"],
        ensure_tables=False,
    )

    catalog_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_stock_catalog" in sql.lower()
        for row in params
    ]
    assert [row[2] for row in catalog_rows] == ["001234.SZ"]
    assert catalog_rows[0][1] == 0
    assert result["diagnostics"]["stock_catalog"] == {
        "source_symbols": 2,
        "inserted_symbols": 1,
        "new_symbols": 1,
        "changed_symbols": 0,
        "removed_symbols": 0,
        "dormant_symbols": 0,
        "st_changed_symbols": 0,
        "audit": {
            "status": "degraded",
            "reasons": ["catalog_count_changed"],
        },
    }


def test_stock_catalog_writes_append_only_change_events() -> None:
    from src.data.models import StockInfo
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class CatalogClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "argmax(market, captured_at), argmax(is_st" in sql.lower():
                return [("000001.SZ", 0, 0), ("000002.SZ", 0, 0)]
            if "argmax(market, captured_at), argmax(code" in sql.lower():
                return [
                    ("000001.SZ", 0, "000001", "旧名称", 0),
                    ("000002.SZ", 0, "000002", "已移除", 0),
                ]
            return []

    class Source(FakeSource):
        def fetch_stock_list(self):
            return [
                StockInfo(symbol="000001.SZ", code="000001", name="*ST新名称", is_st=True),
                StockInfo(symbol="000003.SZ", code="000003", name="新增股票"),
            ]

    client = CatalogClient()
    sync_mootdx_offline_data(
        client=client,
        source=Source(),
        trade_date=date(2026, 7, 9),
        tasks=["stock_catalog"],
        ensure_tables=False,
    )

    event_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_catalog_change_events" in sql.lower()
        for row in params
    ]
    assert {row[2] for row in event_rows} == {"added", "name_changed", "st_changed"}
    assert {row[1] for row in event_rows} == {"000001.SZ", "000003.SZ"}


def test_stock_catalog_marks_second_successive_missing_symbol_dormant() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class CatalogClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "argmax(market, captured_at), argmax(code" in sql.lower():
                return [("000002.SZ", 0, "000002", "观察中", 0, 1, 1)]
            return []

    class Source(FakeSource):
        def fetch_stock_list(self):
            from src.data.models import StockInfo

            return [StockInfo(symbol="000001.SZ", code="000001", name="仍在目录")]

    client = CatalogClient()
    result = sync_mootdx_offline_data(
        client=client,
        source=Source(),
        trade_date=date(2026, 7, 9),
        tasks=["stock_catalog"],
        ensure_tables=False,
    )

    catalog_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_stock_catalog" in sql.lower()
        for row in params
    ]
    dormant_row = next(row for row in catalog_rows if row[2] == "000002.SZ")
    assert dormant_row[6:8] == (0, 2)
    assert result["diagnostics"]["stock_catalog"]["dormant_symbols"] == 1


def test_daily_catalog_pool_excludes_dormant_symbols() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class CatalogPoolClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "from mootdx_stock_catalog" in sql.lower():
                return [("000001.SZ", 0, 0, 1), ("000002.SZ", 0, 0, 0)]
            return []

    class Source(FakeSource):
        def __init__(self) -> None:
            self.daily_symbols: list[str] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.daily_symbols.append(symbol)
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = Source()
    sync_mootdx_offline_data(
        client=CatalogPoolClient(),
        source=source,
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert source.daily_symbols == ["000001.SZ"]


def test_stock_kline_daily_retries_empty_symbol_with_larger_offsets() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class RetryDailySource(FakeSource):
        def __init__(self) -> None:
            self.daily_calls: list[tuple[str, int | None]] = []

        def fetch_stock_list(self):
            from src.data.models import StockInfo

            return [
                StockInfo(symbol="000001.SZ", code="000001", name="平安银行"),
                StockInfo(symbol="000002.SZ", code="000002", name="万科A"),
            ]

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.daily_calls.append((symbol, offset))
            if symbol == "000002.SZ" and offset in {5, 20}:
                return pd.DataFrame()
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = RetryDailySource()
    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=source,
        symbols=["000001.SZ", "000002.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert source.daily_calls == [
        ("000001.SZ", 5),
        ("000002.SZ", 5),
        ("000002.SZ", 20),
        ("000002.SZ", 800),
    ]
    assert result["inserted"]["mootdx_stock_kline"] == 2
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["target_symbols"] == 2
    assert daily["retry_success_count"] == 1
    assert daily["failed_symbols_count"] == 0
    assert daily["coverage_rate"] == 1.0
    assert any("optimize table mootdx_stock_kline partition" in sql.lower() for sql in client.sql)


def test_stock_kline_daily_records_failed_symbols_without_failing_task() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class FailingDailySource(FakeSource):
        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            if symbol == "000002.SZ":
                raise TimeoutError("tdx timeout")
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FailingDailySource(),
        symbols=["000001.SZ", "000002.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert result["failed"] == {}
    assert result["inserted"]["mootdx_stock_kline"] == 1
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["target_symbols"] == 2
    assert daily["failed_symbols_count"] == 1
    assert daily["failed_symbols_sample"][0]["symbol"] == "000002.SZ"
    assert daily["failed_symbols_sample"][0]["final_status"] == "failed"
    assert daily["coverage_rate"] == 0.5


def test_stock_kline_daily_drops_invalid_ohlc_rows() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class InvalidDailySource(FakeSource):
        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            return pd.DataFrame([
                {
                    "date": date(2026, 7, 9),
                    "open": 10.0,
                    "high": 9.0,
                    "low": 8.0,
                    "close": 10.5,
                    "volume": 100,
                    "amount": 1000.0,
                    "symbol": symbol,
                }
            ])

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=InvalidDailySource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert result["inserted"].get("mootdx_stock_kline", 0) == 0
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["dropped_rows"] == 1
    assert daily["inserted_rows"] == 0
    assert daily["coverage_rate"] == 0.0


def test_stock_kline_daily_uses_latest_catalog_pool_when_symbols_not_provided() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class CatalogPoolClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "from mootdx_stock_catalog" in sql.lower():
                return [
                    ("000001.SZ", 0, 0),
                    ("000002.SZ", 0, 0),
                    ("600000.SH", 1, 0),
                    ("688001.SH", 1, 1),
                    ("830001.BJ", 2, 0),
                ]
            return []

    class CatalogDailySource(FakeSource):
        def __init__(self) -> None:
            self.stock_list_calls = 0
            self.daily_symbols: list[str] = []

        def fetch_stock_list(self):
            self.stock_list_calls += 1
            return super().fetch_stock_list()

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.daily_symbols.append(symbol)
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = CatalogDailySource()
    client = CatalogPoolClient()
    result = sync_mootdx_offline_data(
        client=client,
        source=source,
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert source.stock_list_calls == 0
    assert source.daily_symbols == ["000001.SZ", "000002.SZ", "600000.SH"]
    assert result["symbols"] == ["000001.SZ", "000002.SZ", "600000.SH"]


def test_stock_kline_daily_skips_symbols_marked_no_data() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class StatusClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "from mootdx_symbol_data_status" in sql.lower():
                return [("000002.SZ", "no_data")]
            return []

    class DailySource(FakeSource):
        def __init__(self) -> None:
            self.daily_symbols: list[str] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.daily_symbols.append(symbol)
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = DailySource()
    client = StatusClient()
    result = sync_mootdx_offline_data(
        client=client,
        source=source,
        symbols=["000001.SZ", "000002.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    assert source.daily_symbols == ["000001.SZ"]
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["skipped_no_data_symbols_count"] == 1
    assert daily["skipped_no_data_symbols_sample"] == ["000002.SZ"]
    assert result["inserted"]["mootdx_stock_kline"] == 1


def test_daily_no_data_status_only_skips_the_verified_trade_date() -> None:
    from src.data.mootdx_clickhouse_sync import _should_skip_daily_symbol

    record = {
        "status": "no_data",
        "no_data_trade_date": date(2026, 7, 1),
    }

    assert _should_skip_daily_symbol(record, trade_date=date(2026, 7, 1)) is True
    assert _should_skip_daily_symbol(record, trade_date=date(2026, 7, 10)) is False


def test_stock_kline_daily_records_empty_all_offsets_as_no_data_status() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class EmptyDailySource(FakeSource):
        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            return pd.DataFrame()

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=EmptyDailySource(),
        symbols=["301583.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    status_inserts = [
        params
        for sql, params in client.inserts
        if "insert into mootdx_symbol_data_status" in sql.lower()
    ]
    assert result["inserted"].get("mootdx_stock_kline", 0) == 0
    assert status_inserts
    row = status_inserts[0][0]
    assert row[0] == "301583.SZ"
    assert row[1] == "stock_kline_daily"
    assert row[2] == "no_data"
    assert row[3] == "empty_all_offsets"
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["new_no_data_symbols_count"] == 1
    assert daily["empty_symbols_sample"] == ["301583.SZ"]


def test_stock_kline_daily_records_successful_symbols_as_active_status() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FakeSource(),
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    status_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_symbol_data_status" in sql.lower()
        for row in params
    ]
    assert result["inserted"]["mootdx_stock_kline"] == 1
    assert any(row[0] == "000001.SZ" and row[2] == "active" and row[3] == "daily_bar_loaded" for row in status_rows)
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["active_status_updates_count"] == 1


def test_stock_kline_daily_records_failed_symbols_as_temporary_failed_status() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class FailingDailySource(FakeSource):
        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            if symbol == "000002.SZ":
                raise TimeoutError("tdx timeout")
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FailingDailySource(),
        symbols=["000001.SZ", "000002.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    status_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_symbol_data_status" in sql.lower()
        for row in params
    ]
    assert result["failed"] == {}
    assert any(row[0] == "000002.SZ" and row[2] == "temporary_failed" and row[3] == "fetch_error" for row in status_rows)
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["temporary_failed_status_updates_count"] == 1


def test_stock_kline_daily_preserves_failure_history_and_rechecks_expired_no_data() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    first_failure = datetime(2026, 7, 1, 15, 0)
    stale_no_data = datetime(2026, 6, 1, 15, 0)

    class StatusClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "from mootdx_symbol_data_status" in sql.lower():
                return [
                    ("000002.SZ", "temporary_failed", first_failure, first_failure, 2, None),
                    ("000003.SZ", "no_data", stale_no_data, stale_no_data, 0, None),
                ]
            return []

    class Source(FakeSource):
        def __init__(self) -> None:
            self.requested: list[str] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.requested.append(symbol)
            if symbol == "000002.SZ":
                raise TimeoutError("tdx timeout")
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    client = StatusClient()
    source = Source()
    sync_mootdx_offline_data(
        client=client,
        source=source,
        symbols=["000002.SZ", "000003.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
    )

    status_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_symbol_data_status" in sql.lower()
        for row in params
    ]
    failed_row = next(row for row in status_rows if row[0] == "000002.SZ")
    active_row = next(row for row in status_rows if row[0] == "000003.SZ")
    assert source.requested == ["000002.SZ", "000002.SZ", "000002.SZ", "000003.SZ"]
    assert failed_row[4] == first_failure
    assert failed_row[6] == 3
    assert active_row[4] == stale_no_data
    assert active_row[6] == 0


def test_stock_kline_daily_can_recheck_symbols_marked_no_data() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class StatusClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "from mootdx_symbol_data_status" in sql.lower():
                return [("000001.SZ", "no_data")]
            return []

    class DailySource(FakeSource):
        def __init__(self) -> None:
            self.daily_symbols: list[str] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.daily_symbols.append(symbol)
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = DailySource()
    result = sync_mootdx_offline_data(
        client=StatusClient(),
        source=source,
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
        recheck_no_data=True,
    )

    assert source.daily_symbols == ["000001.SZ"]
    assert result["inserted"]["mootdx_stock_kline"] == 1
    assert result["diagnostics"]["stock_kline_daily"]["skipped_no_data_symbols_count"] == 0


def test_daily_reconciliation_requests_only_symbols_missing_from_trade_date() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class KlineClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "insert into" in sql.lower():
                self.inserts.append((sql, params or []))
                return []
            if "from mootdx_stock_kline final" in sql.lower():
                return [("000001.SZ",)]
            return []

    class Source(FakeSource):
        def __init__(self) -> None:
            self.requested: list[str] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.requested.append(symbol)
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = Source()
    result = sync_mootdx_offline_data(
        client=KlineClient(),
        source=source,
        symbols=["000001.SZ", "000002.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        daily_reconcile=True,
        ensure_tables=False,
    )

    assert source.requested == ["000002.SZ"]
    assert result["diagnostics"]["stock_kline_daily"]["reconciliation"] == {
        "candidate_symbols": 2,
        "missing_symbols": 1,
        "missing_symbols_sample": ["000002.SZ"],
    }
    assert result["diagnostics"]["stock_kline_daily"]["audit"] == {
        "status": "healthy",
        "reasons": [],
    }


def test_daily_reconciliation_treats_known_no_data_symbols_as_resolved() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class KlineClient(FakeClickHouse):
        def execute(self, sql: str, params=None):
            self.sql.append(sql)
            if "from mootdx_symbol_data_status" in sql.lower():
                return [("000001.SZ", "no_data")]
            return []

    class Source(FakeSource):
        def __init__(self) -> None:
            self.requested: list[str] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.requested.append(symbol)
            return super().fetch_bars(symbol, start, end, frequency, offset=offset)

    source = Source()
    result = sync_mootdx_offline_data(
        client=KlineClient(),
        source=source,
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        daily_reconcile=True,
        ensure_tables=False,
    )

    daily = result["diagnostics"]["stock_kline_daily"]
    assert source.requested == []
    assert daily["requested_symbols"] == 0
    assert daily["skipped_no_data_symbols_count"] == 1
    assert daily["coverage_rate"] == 1.0
    assert daily["audit"] == {"status": "healthy", "reasons": []}


def test_stock_kline_daily_backfill_fetches_once_and_filters_date_range() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class BackfillSource(FakeSource):
        def __init__(self) -> None:
            self.daily_calls: list[tuple[str, int | None]] = []

        def fetch_bars(self, symbol, start, end, frequency="daily", offset=None):
            self.daily_calls.append((symbol, offset))
            return pd.DataFrame([
                {
                    "date": date(2026, 7, 7),
                    "open": 9.8,
                    "high": 10.0,
                    "low": 9.7,
                    "close": 9.9,
                    "volume": 90,
                    "amount": 900.0,
                    "symbol": symbol,
                },
                {
                    "date": date(2026, 7, 8),
                    "open": 10.0,
                    "high": 10.3,
                    "low": 9.9,
                    "close": 10.2,
                    "volume": 100,
                    "amount": 1000.0,
                    "symbol": symbol,
                },
                {
                    "date": date(2026, 7, 9),
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 120,
                    "amount": 1200.0,
                    "symbol": symbol,
                },
            ])

    source = BackfillSource()
    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=source,
        symbols=["000001.SZ"],
        trade_date=date(2026, 7, 9),
        tasks=["stock_kline_daily"],
        ensure_tables=False,
        daily_mode="backfill",
        daily_offset=800,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 9),
    )

    assert source.daily_calls == [("000001.SZ", 800)]
    assert result["inserted"]["mootdx_stock_kline"] == 2
    inserted_rows = [
        row
        for sql, params in client.inserts
        if "insert into mootdx_stock_kline" in sql.lower()
        for row in params
    ]
    assert [row[1] for row in inserted_rows] == [date(2026, 7, 8), date(2026, 7, 9)]
    daily = result["diagnostics"]["stock_kline_daily"]
    assert daily["mode"] == "backfill"
    assert daily["daily_offset"] == 800
    assert daily["start_date"] == "2026-07-08"
    assert daily["end_date"] == "2026-07-09"
    assert daily["inserted_rows"] == 2
    optimize_sql = [sql.lower() for sql in client.sql if "optimize table mootdx_stock_kline partition" in sql.lower()]
    assert any("'2026-07-08','daily'" in sql for sql in optimize_sql)
    assert any("'2026-07-09','daily'" in sql for sql in optimize_sql)


def test_xdxr_insert_is_batched_by_event_month() -> None:
    from src.data.mootdx_clickhouse_sync import _insert_rows

    client = FakeClickHouse()
    rows = [
        ("000001.SZ", date(1990, 3, 1), 1, "除权除息"),
        ("000001.SZ", date(1990, 3, 8), 1, "除权除息"),
        ("000001.SZ", date(2026, 6, 12), 1, "除权除息"),
    ]

    _insert_rows(client, "mootdx_xdxr", rows)

    xdxr_batches = [params for sql, params in client.inserts if "insert into mootdx_xdxr" in sql.lower()]
    assert len(xdxr_batches) == 2
    assert sorted(len(batch) for batch in xdxr_batches) == [1, 2]


def test_xdxr_rows_preserve_nulls_skip_invalid_dates_and_report_diagnostics() -> None:
    from src.data.mootdx_clickhouse_sync import _run_task

    class XdxrSource:
        def fetch_xdxr(self, symbol):
            if symbol == "000001.SZ":
                return pd.DataFrame([
                    {
                        "year": 2026,
                        "month": 6,
                        "day": 12,
                        "category": 1,
                        "name": "分红",
                        "fenhong": 1.0,
                        "suogu": None,
                        "panqianliutong": None,
                    },
                    {
                        "year": 2026,
                        "month": 6,
                        "day": 12,
                        "category": 2,
                        "name": "配股",
                        "peigu": 0.5,
                        "suogu": "",
                    },
                    {
                        "year": 2026,
                        "month": 13,
                        "day": 1,
                        "category": 1,
                        "name": "非法日期",
                    },
                ])
            return pd.DataFrame()

    diagnostics = {}

    result = _run_task(
        task="xdxr",
        source=XdxrSource(),
        symbols=["000001.SZ", "000002.SZ"],
        trade_date=date(2026, 7, 14),
        frequencies=["daily"],
        diagnostics=diagnostics,
    )

    rows = result["mootdx_xdxr"]
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("000001.SZ", date(2026, 6, 12), 1),
        ("000001.SZ", date(2026, 6, 12), 2),
    ]
    assert rows[0][8] is None
    assert rows[0][9] is None
    assert rows[1][8] is None
    assert {key: diagnostics["xdxr"][key] for key in (
        "target_symbols",
        "requested_symbols",
        "success_symbols",
        "event_rows",
        "empty_symbols_count",
        "invalid_event_rows",
        "failed_symbols_count",
        "failed_symbols_sample",
        "circuit_breaker_triggered",
    )} == {
        "target_symbols": 2,
        "requested_symbols": 2,
        "success_symbols": 1,
        "event_rows": 2,
        "empty_symbols_count": 1,
        "invalid_event_rows": 1,
        "failed_symbols_count": 0,
        "failed_symbols_sample": [],
        "circuit_breaker_triggered": False,
    }
    assert diagnostics["xdxr"]["request_seconds"] >= 0
    assert diagnostics["xdxr"]["parse_seconds"] >= 0


def test_xdxr_task_writes_per_symbol_audits_and_stops_after_three_errors() -> None:
    from src.data.mootdx_clickhouse_sync import _run_task

    class AuditedXdxrSource:
        def fetch_xdxr(self, symbol):
            if symbol in {"000003.SZ", "000004.SZ", "000005.SZ"}:
                raise RuntimeError(f"source unavailable: {symbol}; {'x' * 300}")
            if symbol == "000002.SZ":
                return pd.DataFrame()
            return pd.DataFrame([{
                "year": 2026,
                "month": 7,
                "day": 14,
                "category": 1,
                "name": "分红",
            }])

    diagnostics = {}
    result = _run_task(
        task="xdxr",
        source=AuditedXdxrSource(),
        symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ", "000006.SZ"],
        run_id="xdxr-audit-run",
        trade_date=date(2026, 7, 14),
        frequencies=["daily"],
        diagnostics=diagnostics,
    )

    assert [(row[0], row[1], row[3]) for row in result["mootdx_xdxr_symbol_runs"]] == [
        ("xdxr-audit-run", "000001.SZ", "success"),
        ("xdxr-audit-run", "000002.SZ", "empty"),
        ("xdxr-audit-run", "000003.SZ", "error"),
        ("xdxr-audit-run", "000004.SZ", "error"),
        ("xdxr-audit-run", "000005.SZ", "error"),
    ]
    assert result["mootdx_xdxr_symbol_runs"][0][4] == 1
    assert result["mootdx_xdxr_symbol_runs"][1][4] == 0
    assert result["mootdx_xdxr_symbol_runs"][2][7].startswith("RuntimeError: source unavailable")
    assert len(result["mootdx_xdxr_symbol_runs"][2][7]) == 240
    assert diagnostics["xdxr"]["target_symbols"] == 6
    assert diagnostics["xdxr"]["requested_symbols"] == 5
    assert diagnostics["xdxr"]["success_symbols"] == 1
    assert diagnostics["xdxr"]["empty_symbols_count"] == 1
    assert diagnostics["xdxr"]["failed_symbols_count"] == 3
    assert diagnostics["xdxr"]["circuit_breaker_triggered"] is True
    assert diagnostics["xdxr"]["event_rows"] == 1
    assert diagnostics["xdxr"]["request_seconds"] >= 0
    assert diagnostics["xdxr"]["parse_seconds"] >= 0


def test_xdxr_circuit_breaker_marks_outer_sync_and_run_row_failed() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class FailingXdxrSource(FakeSource):
        def fetch_xdxr(self, symbol):
            raise RuntimeError("upstream unavailable")

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FailingXdxrSource(),
        symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        tasks=["xdxr"],
        ensure_tables=False,
    )

    assert "xdxr" in result["failed"]
    assert "circuit breaker" in result["failed"]["xdxr"].lower()
    assert result["inserted"]["mootdx_xdxr_symbol_runs"] == 3
    run_row = next(rows[0] for sql, rows in client.inserts if "insert into mootdx_sync_runs" in sql.lower())
    assert run_row[4] == "failed"


def test_xdxr_individual_errors_below_circuit_threshold_keep_outer_sync_successful() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    class PartiallyFailingXdxrSource(FakeSource):
        def fetch_xdxr(self, symbol):
            if symbol in {"000001.SZ", "000003.SZ"}:
                raise RuntimeError("single symbol unavailable")
            return super().fetch_xdxr(symbol)

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=PartiallyFailingXdxrSource(),
        symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        tasks=["xdxr"],
        ensure_tables=False,
    )

    assert result["failed"] == {}
    assert result["diagnostics"]["xdxr"]["failed_symbols_count"] == 2
    assert result["diagnostics"]["xdxr"]["circuit_breaker_triggered"] is False
    run_row = next(rows[0] for sql, rows in client.inserts if "insert into mootdx_sync_runs" in sql.lower())
    assert run_row[4] == "success"


def test_xdxr_sync_writes_event_and_symbol_audit_rows() -> None:
    from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

    client = FakeClickHouse()
    result = sync_mootdx_offline_data(
        client=client,
        source=FakeSource(),
        symbols=["000001.SZ"],
        tasks=["xdxr"],
        ensure_tables=False,
    )

    assert result["inserted"] == {"mootdx_xdxr": 1, "mootdx_xdxr_symbol_runs": 1}
    assert any("insert into mootdx_xdxr values" in sql.lower() for sql, _ in client.inserts)
    assert any("insert into mootdx_xdxr_symbol_runs" in sql.lower() for sql, _ in client.inserts)
