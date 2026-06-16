"""Data coverage and health inspection for the local stock database."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.core.constants import format_symbol
from src.data.clickhouse_source import ClickHouseStockDataSource


TABLE_SPECS = {
    "stocks": {"symbol_col": "symbol"},
    "trade_calendar": {"date_col": "date"},
    "daily_kline": {"date_col": "date", "symbol_col": "symbol"},
    "minute5_kline": {"date_col": "datetime", "symbol_col": "symbol"},
    "index_daily": {"date_col": "date", "symbol_col": "code"},
    "financials": {"date_col": "report_date", "symbol_col": "symbol"},
    "stock_quote_snapshots": {"date_col": "snapshot_at", "symbol_col": "symbol"},
    "stock_concept_blocks": {"date_col": "updated_at", "symbol_col": "symbol"},
    "stock_announcements": {"date_col": "date", "symbol_col": "symbol"},
    "data_source_health": {"date_col": "checked_at"},
}

CLICKHOUSE_TABLE_SPECS = {
    "stocks": {"symbol_col": "symbol"},
    "trade_calendar": {"date_col": "date"},
    "daily_kline": {"date_col": "date", "symbol_col": "symbol"},
    "minute5_kline": {"date_col": "datetime", "symbol_col": "symbol"},
    "index_daily": {"date_col": "date", "symbol_col": "code"},
    "financials": {"date_col": "report_date", "symbol_col": "symbol"},
    "stock_quote_snapshots": {"date_col": "snapshot_at", "symbol_col": "symbol"},
    "stock_concept_blocks": {"date_col": "updated_at", "symbol_col": "symbol"},
    "stock_announcements": {"date_col": "date", "symbol_col": "symbol"},
    "data_source_health": {"date_col": "checked_at"},
}


def inspect_stock_database(db_path: str | Path = "data/stock.db") -> dict[str, Any]:
    """Return read-only coverage metrics for the local stock SQLite database."""
    path = Path(db_path)
    database = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    if not path.exists():
        return {
            "database": database,
            "tables": {},
            "stock_summary": {"stock_count": 0, "non_st_stock_count": 0, "st_stock_count": 0},
            "health": {"status": "missing_database"},
        }

    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        available_tables = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type = 'table'")
        }
        tables = {
            table: _table_status(conn, table, spec)
            for table, spec in TABLE_SPECS.items()
            if table in available_tables
        }
        stock_summary = _stock_summary(conn) if "stocks" in available_tables else {
            "stock_count": 0,
            "non_st_stock_count": 0,
            "st_stock_count": 0,
        }

    daily = tables.get("daily_kline", {})
    minute5 = tables.get("minute5_kline", {})
    health = {
        "status": "ok",
        "daily_latest_date": (daily.get("date_range") or {}).get("end"),
        "daily_symbol_count": daily.get("symbol_count", 0),
        "minute5_latest_datetime": (minute5.get("date_range") or {}).get("end"),
        "minute5_symbol_count": minute5.get("symbol_count", 0),
    }
    return {
        "database": database,
        "tables": tables,
        "stock_summary": stock_summary,
        "health": health,
    }


def inspect_clickhouse_database(
    *,
    client: Any | None = None,
    host: str = "10.211.49.42",
    user: str = "default",
    password: str = "stock123",
    database: str = "stock",
) -> dict[str, Any]:
    """Return read-only coverage metrics for the ClickHouse stock database."""
    db_info = {
        "type": "clickhouse",
        "host": host,
        "database": database,
        "exists": True,
        "size_bytes": 0,
    }
    clickhouse = client or ClickHouseStockDataSource(
        host=host,
        user=user,
        password=password,
        database=database,
    )._client_instance()

    try:
        available_tables = {
            row[0]
            for row in clickhouse.execute(
                """
                select name
                from system.tables
                where database = currentDatabase()
                """
            )
        }
        tables = {
            table: _safe_clickhouse_table_status(clickhouse, table, spec)
            for table, spec in CLICKHOUSE_TABLE_SPECS.items()
            if table in available_tables
        }
        stock_summary = _clickhouse_stock_summary(clickhouse) if "stocks" in available_tables else {
            "stock_count": 0,
            "non_st_stock_count": 0,
            "st_stock_count": 0,
        }
    except Exception as exc:  # noqa: BLE001 - surface health instead of breaking the dashboard.
        return {
            "database": {**db_info, "exists": False},
            "tables": {},
            "stock_summary": {"stock_count": 0, "non_st_stock_count": 0, "st_stock_count": 0},
            "health": {"status": "unavailable", "error": str(exc)},
        }

    daily = tables.get("daily_kline", {})
    minute5 = tables.get("minute5_kline", {})
    health = {
        "status": "ok",
        "daily_latest_date": (daily.get("date_range") or {}).get("end"),
        "daily_symbol_count": daily.get("symbol_count", 0),
        "minute5_latest_datetime": (minute5.get("date_range") or {}).get("end"),
        "minute5_symbol_count": minute5.get("symbol_count", 0),
    }
    return {
        "database": db_info,
        "tables": tables,
        "stock_summary": stock_summary,
        "health": health,
        "quality": _clickhouse_quality(client=clickhouse, tables=tables, stock_summary=stock_summary),
    }


def _table_status(conn: sqlite3.Connection, table: str, spec: dict[str, str]) -> dict[str, Any]:
    row_count = conn.execute(f"select count(*) from {table}").fetchone()[0]
    result: dict[str, Any] = {"row_count": row_count}
    date_col = spec.get("date_col")
    if date_col:
        start, end = conn.execute(f"select min({date_col}), max({date_col}) from {table}").fetchone()
        result["date_range"] = {"start": start, "end": end}
    symbol_col = spec.get("symbol_col")
    if symbol_col:
        result["symbol_count"] = conn.execute(f"select count(distinct {symbol_col}) from {table}").fetchone()[0]
    return result


def _stock_summary(conn: sqlite3.Connection) -> dict[str, int]:
    stock_count = conn.execute("select count(*) from stocks").fetchone()[0]
    st_stock_count = conn.execute(
        "select count(*) from stocks where upper(name) like '%ST%'"
    ).fetchone()[0]
    return {
        "stock_count": stock_count,
        "non_st_stock_count": stock_count - st_stock_count,
        "st_stock_count": st_stock_count,
    }


def _clickhouse_table_status(client: Any, table: str, spec: dict[str, str]) -> dict[str, Any]:
    selectors = ["count()"]
    date_col = spec.get("date_col")
    symbol_col = spec.get("symbol_col")
    if date_col:
        selectors.extend([f"min({date_col})", f"max({date_col})"])
    if symbol_col:
        selectors.append(f"uniqExact({symbol_col})")
    row = client.execute(f"select {', '.join(selectors)} from {table}")[0]

    result: dict[str, Any] = {"row_count": int(row[0] or 0)}
    offset = 1
    if date_col:
        result["date_range"] = {
            "start": _format_status_value(row[offset]),
            "end": _format_status_value(row[offset + 1]),
        }
        offset += 2
    if symbol_col:
        result["symbol_count"] = int(row[offset] or 0)
    return result


def _safe_clickhouse_table_status(client: Any, table: str, spec: dict[str, str]) -> dict[str, Any]:
    try:
        return _clickhouse_table_status(client, table, spec)
    except Exception as exc:  # noqa: BLE001 - keep optional-table failures local.
        return {"row_count": 0, "error": str(exc)}


def _clickhouse_stock_summary(client: Any) -> dict[str, int]:
    row = client.execute(
        """
        select count(), count() - countIf(upper(name) like '%ST%'), countIf(upper(name) like '%ST%')
        from stocks
        """
    )[0]
    return {
        "stock_count": int(row[0] or 0),
        "non_st_stock_count": int(row[1] or 0),
        "st_stock_count": int(row[2] or 0),
    }


def _clickhouse_quality(
    *,
    client: Any,
    tables: dict[str, dict[str, Any]],
    stock_summary: dict[str, int],
) -> dict[str, Any]:
    stock_count = int(stock_summary.get("stock_count") or 0)
    non_st_count = int(stock_summary.get("non_st_stock_count") or 0)
    daily = tables.get("daily_kline", {})
    minute5 = tables.get("minute5_kline", {})
    daily_check = _coverage_check(
        latest=(daily.get("date_range") or {}).get("end"),
        covered=int(daily.get("symbol_count") or 0),
        expected=stock_count,
        latest_key="latest_date",
    )
    minute5_check = _coverage_check(
        latest=(minute5.get("date_range") or {}).get("end"),
        covered=int(minute5.get("symbol_count") or 0),
        expected=non_st_count,
        latest_key="latest_datetime",
    )
    if daily_check["missing_symbols"] > 0:
        samples = _missing_symbol_samples(
            client=client,
            table="daily_kline",
            date_col="date",
            latest=daily_check["latest_date"],
            non_st_only=False,
        )
        if samples:
            daily_check["missing_samples"] = samples
    if minute5_check["missing_symbols"] > 0:
        samples = _missing_symbol_samples(
            client=client,
            table="minute5_kline",
            date_col="datetime",
            latest=minute5_check["latest_datetime"],
            non_st_only=True,
        )
        if samples:
            minute5_check["missing_samples"] = samples
    issues = []
    if daily_check["missing_symbols"] > 0:
        issues.append(f"daily_kline_missing_{daily_check['missing_symbols']}_symbols")
    if minute5_check["missing_symbols"] > 0:
        issues.append(f"minute5_kline_missing_{minute5_check['missing_symbols']}_symbols")
    statuses = {daily_check["status"], minute5_check["status"]}
    status = "missing" if "missing" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": status,
        "expected_non_st_symbols": non_st_count,
        "daily": daily_check,
        "minute5": minute5_check,
        "issues": issues,
    }


def _missing_symbol_samples(
    *,
    client: Any,
    table: str,
    date_col: str,
    latest: Any,
    non_st_only: bool,
    limit: int = 20,
) -> list[dict[str, str]]:
    if not latest:
        return []
    non_st_filter = "and upper(s.name) not like '%ST%'" if non_st_only else ""
    rows = client.execute(
        f"""
        select s.symbol, s.name
        from stocks s
        left join {table} k
            on s.symbol = k.symbol and k.{date_col} = %(latest)s
        where k.symbol = '' {non_st_filter}
        order by s.symbol
        limit %(limit)s
        """,
        {"latest": latest, "limit": limit},
    )
    return [
        {"symbol": format_symbol(str(symbol)), "name": str(name or "")}
        for symbol, name in rows
    ]


def _coverage_check(
    *,
    latest: Any,
    covered: int,
    expected: int,
    latest_key: str,
) -> dict[str, Any]:
    missing = max(0, expected - covered)
    ratio = min(1.0, covered / expected) if expected else 0.0
    if not latest or expected <= 0:
        status = "missing"
    elif missing:
        status = "warning"
    else:
        status = "ok"
    return {
        latest_key: latest,
        "covered_symbols": covered,
        "missing_symbols": missing,
        "coverage_ratio": round(ratio, 6),
        "status": status,
    }


def _format_status_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
