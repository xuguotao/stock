"""ClickHouse table maintenance helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource


def minute5_duplicate_stats(
    *,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, int]:
    """Return duplicate key stats for minute5_kline."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    rows = clickhouse.execute(
        """
        select count() as duplicate_groups, sum(c - 1) as extra_rows
        from (
            select symbol, datetime, count() as c
            from minute5_kline
            group by symbol, datetime
            having count() > 1
        )
        """
    )
    duplicate_groups, extra_rows = rows[0] if rows else (0, 0)
    return {
        "duplicate_groups": int(duplicate_groups or 0),
        "extra_rows": int(extra_rows or 0),
    }


def daily_duplicate_stats(
    *,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, int]:
    """Return duplicate key stats for daily_kline."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    rows = clickhouse.execute(
        """
        select count() as duplicate_groups, sum(c - 1) as extra_rows
        from (
            select symbol, date, count() as c
            from daily_kline
            group by symbol, date
            having count() > 1
        )
        """
    )
    duplicate_groups, extra_rows = rows[0] if rows else (0, 0)
    return {
        "duplicate_groups": int(duplicate_groups or 0),
        "extra_rows": int(extra_rows or 0),
    }


def deduplicate_minute5_kline(
    *,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    dry_run: bool = True,
    suffix: str | None = None,
) -> dict[str, Any]:
    """Rebuild minute5_kline as a deduplicated ReplacingMergeTree table."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    before = minute5_duplicate_stats(client=clickhouse)
    suffix = suffix or datetime.now().strftime("%Y%m%d%H%M%S")
    replacement_table = f"minute5_kline_dedup_{suffix}"
    backup_table = f"minute5_kline_backup_{suffix}"
    result = {
        "dry_run": dry_run,
        "before": before,
        "replacement_table": replacement_table,
        "backup_table": backup_table,
    }
    if dry_run:
        return result

    if _table_exists(clickhouse, replacement_table) or _table_exists(clickhouse, backup_table):
        raise RuntimeError(f"maintenance table already exists for suffix {suffix}")

    clickhouse.execute(_create_minute5_replacement_sql(replacement_table))
    clickhouse.execute(
        f"""
        insert into {replacement_table}
            (symbol, datetime, open, high, low, close, volume, amount, updated_at)
        select
            symbol,
            datetime,
            anyLast(open) as open,
            anyLast(high) as high,
            anyLast(low) as low,
            anyLast(close) as close,
            anyLast(volume) as volume,
            anyLast(amount) as amount,
            now() as updated_at
        from minute5_kline
        group by symbol, datetime
        """
    )
    clickhouse.execute(
        f"""
        rename table
            minute5_kline to {backup_table},
            {replacement_table} to minute5_kline
        """
    )
    after = minute5_duplicate_stats(client=clickhouse)
    result["after"] = after
    return result


def deduplicate_daily_kline(
    *,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    dry_run: bool = True,
    suffix: str | None = None,
) -> dict[str, Any]:
    """Rebuild daily_kline as one row per (symbol, date)."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    before = daily_duplicate_stats(client=clickhouse)
    suffix = suffix or datetime.now().strftime("%Y%m%d%H%M%S")
    replacement_table = f"daily_kline_dedup_{suffix}"
    backup_table = f"daily_kline_backup_{suffix}"
    result = {
        "dry_run": dry_run,
        "before": before,
        "replacement_table": replacement_table,
        "backup_table": backup_table,
    }
    if dry_run:
        return result

    if _table_exists(clickhouse, replacement_table) or _table_exists(clickhouse, backup_table):
        raise RuntimeError(f"maintenance table already exists for suffix {suffix}")

    clickhouse.execute(_create_daily_replacement_sql(replacement_table))
    clickhouse.execute(
        f"""
        insert into {replacement_table}
            (symbol, date, open, high, low, close, volume, amount, amplitude, pct_change, change, turnover)
        select
            symbol,
            date,
            anyLast(open) as open,
            anyLast(high) as high,
            anyLast(low) as low,
            anyLast(close) as close,
            anyLast(volume) as volume,
            anyLast(amount) as amount,
            anyLast(amplitude) as amplitude,
            anyLast(pct_change) as pct_change,
            anyLast(change) as change,
            anyLast(turnover) as turnover
        from daily_kline
        group by symbol, date
        """
    )
    clickhouse.execute(
        f"""
        rename table
            daily_kline to {backup_table},
            {replacement_table} to daily_kline
        """
    )
    after = daily_duplicate_stats(client=clickhouse)
    result["after"] = after
    return result


def optimize_quote_snapshot_rollups(
    *,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, Any]:
    """Trigger ReplacingMergeTree final merges for quote snapshot rollup tables."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    tables = ["stock_quote_snapshots_1m", "stock_quote_snapshots_5m"]
    for table in tables:
        clickhouse.execute(f"optimize table {table} final")
    return {"tables": tables, "optimized": len(tables)}


def _client(*, host: str | None, user: str | None, password: str | None, database: str | None) -> Any:
    source = ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
    return source._client_instance()


def _table_exists(client: Any, table: str) -> bool:
    rows = client.execute(
        """
        select count()
        from system.tables
        where database = currentDatabase() and name = %(table)s
        """,
        {"table": table},
    )
    return bool(rows and int(rows[0][0] or 0) > 0)


def _create_minute5_replacement_sql(table: str) -> str:
    return f"""
    create table {table} (
        symbol String,
        datetime DateTime,
        open Float64,
        high Float64,
        low Float64,
        close Float64,
        volume Float64,
        amount Float64,
        updated_at DateTime default now()
    )
    engine = ReplacingMergeTree(updated_at)
    partition by toYYYYMM(datetime)
    order by (symbol, datetime)
    """


def _create_daily_replacement_sql(table: str) -> str:
    return f"""
    create table {table} (
        symbol String,
        date Date,
        open Float64,
        high Float64,
        low Float64,
        close Float64,
        volume Float64,
        amount Float64,
        amplitude Nullable(Float64),
        pct_change Nullable(Float64),
        change Nullable(Float64),
        turnover Nullable(Float64)
    )
    engine = MergeTree
    partition by toYYYYMM(date)
    order by (symbol, date)
    """
