"""Daily bar repair helpers for ClickHouse."""

from __future__ import annotations

from datetime import date
from threading import Lock
from typing import Any, Callable

import pandas as pd

from src.data.clickhouse_source import ClickHouseStockDataSource

_DAILY_REPAIR_LOCK = Lock()


def sync_clickhouse_daily_from_minute5(
    *,
    trade_date: date,
    client: Any | None = None,
    host: str = "10.211.49.42",
    user: str = "default",
    password: str = "stock123",
    database: str = "stock",
) -> dict[str, Any]:
    """Derive missing daily bars from deduplicated 5-minute bars."""
    clickhouse = client or ClickHouseStockDataSource(
        host=host,
        user=user,
        password=password,
        database=database,
    )._client_instance()
    before = _daily_count(clickhouse, trade_date)
    if not _DAILY_REPAIR_LOCK.acquire(blocking=False):
        return _daily_lock_skipped_result(trade_date=trade_date, before=before)
    acquired_clickhouse_lock = False
    try:
        acquired_clickhouse_lock = _acquire_daily_repair_marker(clickhouse, trade_date)
        if not acquired_clickhouse_lock:
            return _daily_lock_skipped_result(trade_date=trade_date, before=before)
        clickhouse.execute(
            """
            insert into daily_kline (
                symbol, date, open, high, low, close, volume, amount,
                amplitude, pct_change, change, turnover
            )
            select
                bars.symbol,
                %(trade_date)s as date,
                argMin(bars.open, bars.datetime) as open,
                max(bars.high) as high,
                min(bars.low) as low,
                argMax(bars.close, bars.datetime) as close,
                sum(bars.volume) as volume,
                sum(bars.amount) as amount,
                if(prev.prev_close > 0, (max(bars.high) - min(bars.low)) / prev.prev_close * 100, null) as amplitude,
                if(prev.prev_close > 0, (argMax(bars.close, bars.datetime) - prev.prev_close) / prev.prev_close * 100, null) as pct_change,
                if(prev.prev_close > 0, argMax(bars.close, bars.datetime) - prev.prev_close, null) as change,
                null as turnover
            from (
                select
                    symbol,
                    datetime,
                    anyLast(open) as open,
                    anyLast(high) as high,
                    anyLast(low) as low,
                    anyLast(close) as close,
                    anyLast(volume) as volume,
                    anyLast(amount) as amount
                from minute5_kline
                where toDate(datetime) = %(trade_date)s
                group by symbol, datetime
            ) bars
            left join (
                select symbol, argMax(close, date) as prev_close
                from daily_kline
                where date < %(trade_date)s
                group by symbol
            ) prev on bars.symbol = prev.symbol
            where bars.symbol not in (
                select symbol from daily_kline where date = %(trade_date)s
            )
            group by bars.symbol, prev.prev_close
            """,
            {"trade_date": trade_date},
        )
        after = _daily_count(clickhouse, trade_date)
        return {
            "trade_date": trade_date.isoformat(),
            "before_rows": before,
            "after_rows": after,
            "inserted_rows": max(0, after - before),
        }
    finally:
        if acquired_clickhouse_lock:
            _release_daily_repair_marker(clickhouse, trade_date)
        _DAILY_REPAIR_LOCK.release()


def _daily_count(client: Any, trade_date: date) -> int:
    rows = client.execute(
        "select count() from daily_kline where date = %(trade_date)s",
        {"trade_date": trade_date},
    )
    return int(rows[0][0] or 0) if rows else 0


def _daily_lock_skipped_result(*, trade_date: date, before: int) -> dict[str, Any]:
    return {
        "trade_date": trade_date.isoformat(),
        "before_rows": before,
        "after_rows": before,
        "inserted_rows": 0,
        "skipped": True,
        "skip_reason": "daily_repair_lock_held",
    }


def _acquire_daily_repair_marker(client: Any, trade_date: date) -> bool:
    client.execute(
        """
        create table if not exists daily_kline_repair_locks (
            trade_date Date,
            acquired_at DateTime
        )
        engine = MergeTree
        order by trade_date
        """
    )
    rows = client.execute(
        """
        insert into daily_kline_repair_locks
        select %(trade_date)s, now()
        where not exists (
            select 1 from daily_kline_repair_locks where trade_date = %(trade_date)s
        )
        """,
        {"trade_date": trade_date},
    )
    if rows and len(rows[0]) == 1:
        return int(rows[0][0] or 0) > 0
    return True


def _release_daily_repair_marker(client: Any, trade_date: date) -> None:
    client.execute(
        "alter table daily_kline_repair_locks delete where trade_date = %(trade_date)s",
        {"trade_date": trade_date},
    )


def sync_clickhouse_index_daily(
    *,
    start: date,
    end: date,
    client: Any | None = None,
    fetcher: Callable[[str], pd.DataFrame] | None = None,
    host: str = "10.211.49.42",
    user: str = "default",
    password: str = "stock123",
    database: str = "stock",
) -> dict[str, Any]:
    """Fill missing index daily bars for index codes already present in ClickHouse."""
    clickhouse = client or ClickHouseStockDataSource(
        host=host,
        user=user,
        password=password,
        database=database,
    )._client_instance()
    index_fetcher = fetcher or _fetch_akshare_index_daily
    codes = [
        str(row[0])
        for row in clickhouse.execute("select distinct code from index_daily order by code")
    ]
    total_inserted = 0
    failures: list[dict[str, str]] = []
    per_code: list[dict[str, Any]] = []
    for code in codes:
        existing = {
            row[0]
            for row in clickhouse.execute(
                """
                select date
                from index_daily
                where code = %(code)s and date >= %(start)s and date <= %(end)s
                """,
                {"code": code, "start": start, "end": end},
            )
        }
        try:
            source_df = index_fetcher(_index_source_symbol(code))
        except Exception as exc:  # noqa: BLE001 - continue other index codes.
            failures.append({"code": code, "error": str(exc)})
            continue
        rows = _index_daily_rows(code=code, df=source_df, start=start, end=end, existing=existing)
        if rows:
            clickhouse.execute(
                """
                insert into index_daily
                    (code, date, open, high, low, close, volume, amount, pct_change)
                values
                """,
                rows,
            )
        total_inserted += len(rows)
        per_code.append({"code": code, "inserted_rows": len(rows)})
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "codes": len(codes),
        "inserted_rows": total_inserted,
        "failures": failures,
        "per_code": per_code,
    }


def _fetch_akshare_index_daily(source_symbol: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_index_daily(symbol=source_symbol)


def _index_source_symbol(code: str) -> str:
    value = str(code)
    if value.startswith(("sh", "sz")):
        return value
    return f"sz{value}" if value.startswith("399") else f"sh{value}"


def _index_daily_rows(
    *,
    code: str,
    df: pd.DataFrame,
    start: date,
    end: date,
    existing: set[date],
) -> list[tuple]:
    if df.empty:
        return []
    source = df.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce").dt.date
    source = source.dropna(subset=["date"]).sort_values("date")
    source["pct_change"] = pd.to_numeric(source["close"], errors="coerce").pct_change() * 100
    selected = source[
        (source["date"] >= start)
        & (source["date"] <= end)
        & (~source["date"].isin(existing))
    ]
    rows = []
    for row in selected.itertuples(index=False):
        rows.append(
            (
                code,
                row.date,
                float(getattr(row, "open") or 0),
                float(getattr(row, "high") or 0),
                float(getattr(row, "low") or 0),
                float(getattr(row, "close") or 0),
                float(getattr(row, "volume") or 0),
                float(getattr(row, "amount", 0) or 0),
                _optional_float(getattr(row, "pct_change", None)),
            )
        )
    return rows


def _optional_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), 6)
