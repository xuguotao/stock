"""Data coverage and health inspection for the local stock database."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.core.constants import format_symbol
from src.data.clickhouse_table_maintenance import minute5_duplicate_stats
from src.data.clickhouse_source import ClickHouseStockDataSource


TABLE_SPECS = {
    "stocks": {"symbol_col": "symbol"},
    "trade_calendar": {"date_col": "date"},
    "daily_kline": {"date_col": "date", "symbol_col": "symbol"},
    "minute1_kline": {"date_col": "datetime", "symbol_col": "symbol"},
    "minute5_kline": {"date_col": "datetime", "symbol_col": "symbol"},
    "index_daily": {"date_col": "date", "symbol_col": "code"},
    "financials": {"date_col": "report_date", "symbol_col": "symbol"},
    "stock_quote_snapshots": {"date_col": "snapshot_at", "symbol_col": "symbol"},
    "stock_quote_snapshots_1m": {"date_col": "bucket_start", "symbol_col": "symbol"},
    "stock_quote_snapshots_5m": {"date_col": "bucket_start", "symbol_col": "symbol"},
    "stock_concept_blocks": {"date_col": "updated_at", "symbol_col": "symbol"},
    "stock_announcements": {"date_col": "date", "symbol_col": "symbol"},
    "data_source_health": {"date_col": "checked_at"},
    "fund_tail_nav": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_proxy": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_benchmark": {"date_col": "date"},
    "fund_watchlist": {"date_col": "updated_at", "symbol_col": "fund_code"},
}

CLICKHOUSE_TABLE_SPECS = {
    "stocks": {"symbol_col": "symbol"},
    "trade_calendar": {"date_col": "date"},
    "daily_kline": {"date_col": "date", "symbol_col": "symbol"},
    "minute1_kline": {"date_col": "datetime", "symbol_col": "symbol"},
    "minute5_kline": {"date_col": "datetime", "symbol_col": "symbol"},
    "index_daily": {"date_col": "date", "symbol_col": "code"},
    "financials": {"date_col": "report_date", "symbol_col": "symbol"},
    "stock_quote_snapshots": {"date_col": "snapshot_at", "symbol_col": "symbol"},
    "stock_quote_snapshots_1m": {"date_col": "bucket_start", "symbol_col": "symbol"},
    "stock_quote_snapshots_5m": {"date_col": "bucket_start", "symbol_col": "symbol"},
    "stock_concept_blocks": {"date_col": "updated_at", "symbol_col": "symbol"},
    "stock_announcements": {"date_col": "date", "symbol_col": "symbol"},
    "data_source_health": {"date_col": "checked_at"},
    "fund_tail_nav": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_proxy": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_benchmark": {"date_col": "date"},
    "fund_watchlist": {"date_col": "updated_at", "symbol_col": "fund_code"},
}

QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS = 10
QUOTE_SNAPSHOT_RAW_RETENTION_DAYS = 120
QUOTE_SNAPSHOT_AGGREGATE_RETENTION_DAYS = 1095
QUOTE_SNAPSHOT_ROLLUPS = {
    "1m": {"table": "stock_quote_snapshots_1m", "bucket_seconds": 60},
    "5m": {"table": "stock_quote_snapshots_5m", "bucket_seconds": 300},
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
    minute1 = tables.get("minute1_kline", {})
    minute5 = tables.get("minute5_kline", {})
    quote_snapshots = tables.get("stock_quote_snapshots", {})
    health = {
        "status": "ok",
        "daily_latest_date": (daily.get("date_range") or {}).get("end"),
        "daily_symbol_count": daily.get("symbol_count", 0),
        "minute1_latest_datetime": (minute1.get("date_range") or {}).get("end"),
        "minute1_symbol_count": minute1.get("symbol_count", 0),
        "minute5_latest_datetime": (minute5.get("date_range") or {}).get("end"),
        "minute5_symbol_count": minute5.get("symbol_count", 0),
        "quote_snapshot_latest_datetime": (quote_snapshots.get("date_range") or {}).get("end"),
        "quote_snapshot_symbol_count": quote_snapshots.get("symbol_count", 0),
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
    as_of: date | None = None,
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
    minute1 = tables.get("minute1_kline", {})
    minute5 = tables.get("minute5_kline", {})
    quote_snapshots = tables.get("stock_quote_snapshots", {})
    health = {
        "status": "ok",
        "daily_latest_date": (daily.get("date_range") or {}).get("end"),
        "daily_symbol_count": daily.get("symbol_count", 0),
        "minute1_latest_datetime": (minute1.get("date_range") or {}).get("end"),
        "minute1_symbol_count": minute1.get("symbol_count", 0),
        "minute5_latest_datetime": (minute5.get("date_range") or {}).get("end"),
        "minute5_symbol_count": minute5.get("symbol_count", 0),
        "quote_snapshot_latest_datetime": (quote_snapshots.get("date_range") or {}).get("end"),
        "quote_snapshot_symbol_count": quote_snapshots.get("symbol_count", 0),
    }
    return {
        "database": db_info,
        "tables": tables,
        "stock_summary": stock_summary,
        "health": health,
        "quality": (
            quality := _clickhouse_quality(
                client=clickhouse,
                tables=tables,
                stock_summary=stock_summary,
                as_of=as_of,
            )
        ),
        "datasets_health": _dataset_health_rows(
            tables=tables,
            stock_summary=stock_summary,
            quality=quality,
        ),
    }


def persist_clickhouse_quality_snapshot(
    *,
    client: Any | None = None,
    quality: dict[str, Any] | None = None,
    checked_at: datetime | None = None,
    host: str = "10.211.49.42",
    user: str = "default",
    password: str = "stock123",
    database: str = "stock",
) -> dict[str, Any]:
    """Persist the current ClickHouse data quality result for historical review."""
    clickhouse = client or ClickHouseStockDataSource(
        host=host,
        user=user,
        password=password,
        database=database,
    )._client_instance()
    snapshot_time = checked_at or datetime.now()
    quality_payload = quality or inspect_clickhouse_database(
        client=clickhouse,
        host=host,
        user=user,
        password=password,
        database=database,
    )["quality"]
    clickhouse.execute(
        """
        create table if not exists data_source_health (
            checked_at DateTime,
            check_name LowCardinality(String),
            status LowCardinality(String),
            ok UInt8,
            message String,
            details String
        )
        engine = MergeTree
        partition by toYYYYMM(checked_at)
        order by (checked_at, check_name)
        """
    )
    rows = _quality_health_rows(quality_payload, snapshot_time)
    if rows:
        clickhouse.execute(
            """
            insert into data_source_health
                (checked_at, check_name, status, ok, message, details)
            values
            """,
            rows,
        )
    return {"checked_at": snapshot_time.isoformat(sep=" ", timespec="seconds"), "rows": len(rows)}


def _dataset_health_rows(
    *,
    tables: dict[str, dict[str, Any]],
    stock_summary: dict[str, int],
    quality: dict[str, Any],
) -> list[dict[str, Any]]:
    non_st_count = int(stock_summary.get("non_st_stock_count") or 0)
    expected_all = int(stock_summary.get("stock_count") or 0)
    quote_quality = quality.get("quote_snapshots") or {}
    scheduled = quality.get("scheduled_checks") or {}
    definitions = [
        {
            "key": "stocks",
            "name": "股票基础信息",
            "category": "基础数据",
            "table": "stocks",
            "source": "ClickHouse / stocks",
            "update_mechanism": "旧库同步或基础信息同步任务更新，作为股票池和 ST 过滤基准。",
            "consumer": "全市场扫描、股票名称展示、非 ST 标的池",
            "expected_symbols": expected_all,
            "status": "ok" if tables.get("stocks", {}).get("row_count", 0) else "missing",
            "issues": [],
        },
        {
            "key": "trade_calendar",
            "name": "交易日历",
            "category": "基础数据",
            "table": "trade_calendar",
            "source": "ClickHouse / trade_calendar",
            "update_mechanism": "基础数据同步维护交易日，非交易日采集任务会自动跳过。",
            "consumer": "日常维护、分钟采集、快照采集、回测交易日判断",
            "status": "ok" if tables.get("trade_calendar", {}).get("row_count", 0) else "missing",
            "issues": [],
        },
        {
            "key": "daily_kline",
            "name": "股票日线",
            "category": "行情数据",
            "table": "daily_kline",
            "source": "ClickHouse / daily_kline",
            "update_mechanism": "日常维护补齐；当分钟线先到位时可由 5m 聚合修复最新交易日。",
            "consumer": "尾盘选股、个股趋势、策略复盘、回测、因子计算",
            "quality_key": ("daily",),
            "expected_symbols": (quality.get("daily") or {}).get("expected_symbols", non_st_count),
            "issues": _dataset_issues("daily_kline", quality),
        },
        {
            "key": "minute1_kline",
            "name": "1m 分钟线",
            "category": "行情数据",
            "table": "minute1_kline",
            "source": "ClickHouse / minute1_kline",
            "update_mechanism": "可由分钟源补齐，当前主要用于更细粒度盘中分析和后续因子挖掘。",
            "consumer": "盘中趋势、精细化复盘、短周期因子",
            "expected_symbols": non_st_count,
            "status": _table_presence_status(tables.get("minute1_kline")),
            "issues": [],
        },
        {
            "key": "minute5_kline",
            "name": "5m 分钟线",
            "category": "行情数据",
            "table": "minute5_kline",
            "source": "ClickHouse / minute5_kline",
            "update_mechanism": "交易时段持续更新，手动更新可补指定交易日；尾盘读取可用快照 5m 聚合兜底。",
            "consumer": "今日尾盘选股、尾盘回测、个股趋势分钟图、策略复盘",
            "quality_key": ("minute5",),
            "expected_symbols": (quality.get("minute5") or {}).get("expected_symbols", non_st_count),
            "issues": _dataset_issues("minute5_kline", quality),
        },
        {
            "key": "stock_quote_snapshots",
            "name": "秒级行情快照",
            "category": "实时数据",
            "table": "stock_quote_snapshots",
            "source": "腾讯快照 / ClickHouse",
            "update_mechanism": "交易时段自动守护，按约 10 秒节拍全市场快照采集，原始数据保留短周期。",
            "consumer": "今日尾盘预演、实时价格、快照聚合、盘中可信度检查",
            "quality_key": ("quote_snapshots", "raw"),
            "expected_symbols": quote_quality.get("expected_symbols", non_st_count),
            "issues": quote_quality.get("issues", []),
        },
        {
            "key": "stock_quote_snapshots_1m",
            "name": "1m 快照聚合",
            "category": "聚合数据",
            "table": "stock_quote_snapshots_1m",
            "source": "stock_quote_snapshots 聚合",
            "update_mechanism": "快照采集任务每轮写入后自动滚动聚合，保留长周期。",
            "consumer": "盘中复盘、短线统计、快照降采样",
            "quality_key": ("quote_snapshots", "rollups", "1m"),
            "expected_symbols": quote_quality.get("expected_symbols", non_st_count),
            "issues": quote_quality.get("issues", []),
        },
        {
            "key": "stock_quote_snapshots_5m",
            "name": "5m 快照聚合",
            "category": "聚合数据",
            "table": "stock_quote_snapshots_5m",
            "source": "stock_quote_snapshots 聚合",
            "update_mechanism": "快照采集任务每轮写入后自动滚动聚合，可作为 5m 分钟线实时兜底。",
            "consumer": "尾盘选股 5m 兜底、个股趋势、盘中验证",
            "quality_key": ("quote_snapshots", "rollups", "5m"),
            "expected_symbols": quote_quality.get("expected_symbols", non_st_count),
            "issues": quote_quality.get("issues", []),
        },
        {
            "key": "index_daily",
            "name": "指数日线",
            "category": "基准数据",
            "table": "index_daily",
            "source": "AKShare 指数日线 / ClickHouse",
            "update_mechanism": "日常维护或专项补齐同步指数行情。",
            "consumer": "市场环境、基准对照、策略过滤",
            "expected_symbols": 10,
            "status": _table_presence_status(tables.get("index_daily")),
            "issues": [],
        },
        {
            "key": "financials",
            "name": "财务数据",
            "category": "基本面",
            "table": "financials",
            "source": "ClickHouse / financials",
            "update_mechanism": "低频同步财报数据，按报告期更新。",
            "consumer": "基本面过滤、估值分析、后续因子研究",
            "expected_symbols": expected_all,
            "status": _table_presence_status(tables.get("financials")),
            "issues": [],
        },
        {
            "key": "fund_tail_nav",
            "name": "基金净值",
            "category": "基金尾盘",
            "table": "fund_tail_nav",
            "source": "基金净值 CSV / ClickHouse",
            "update_mechanism": "基金尾盘数据导入任务写入，跟随基金建议刷新。",
            "consumer": "基金尾盘建议、基金复盘",
            "status": _table_presence_status(tables.get("fund_tail_nav")),
            "issues": [],
        },
        {
            "key": "fund_tail_proxy",
            "name": "基金代理行情",
            "category": "基金尾盘",
            "table": "fund_tail_proxy",
            "source": "代理指数/ETF 行情 / ClickHouse",
            "update_mechanism": "基金尾盘数据导入任务写入，用于估计基金盘中表现。",
            "consumer": "基金尾盘建议、代理趋势判断",
            "status": _table_presence_status(tables.get("fund_tail_proxy")),
            "issues": [],
        },
        {
            "key": "fund_tail_benchmark",
            "name": "基金基准",
            "category": "基金尾盘",
            "table": "fund_tail_benchmark",
            "source": "基准指数行情 / ClickHouse",
            "update_mechanism": "基金尾盘数据导入任务写入，用于对照市场基准。",
            "consumer": "基金尾盘相对强弱、基金复盘",
            "status": _table_presence_status(tables.get("fund_tail_benchmark")),
            "issues": [],
        },
        {
            "key": "data_source_health",
            "name": "质量检查历史",
            "category": "运维数据",
            "table": "data_source_health",
            "source": "数据中心质量检查落库",
            "update_mechanism": "每次质量检查或日常维护后写入，保留历史健康度。",
            "consumer": "数据中心、任务健康追踪、异常复盘",
            "status": _table_presence_status(tables.get("data_source_health")),
            "issues": scheduled.get("issues", []),
        },
    ]
    return [
        _dataset_health_row(definition=definition, tables=tables, quality=quality)
        for definition in definitions
    ]


def _dataset_health_row(
    *,
    definition: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    quality: dict[str, Any],
) -> dict[str, Any]:
    table = tables.get(str(definition["table"]), {})
    quality_row = _nested_quality(quality, definition.get("quality_key"))
    status = str(definition.get("status") or quality_row.get("status") or _table_presence_status(table))
    symbols = _quality_symbol_count(quality_row, table)
    expected = definition.get("expected_symbols")
    coverage = quality_row.get("coverage_ratio")
    if coverage is None and expected:
        coverage = _coverage_ratio(int(symbols or 0), int(expected or 0))
    return {
        "key": definition["key"],
        "name": definition["name"],
        "category": definition["category"],
        "table": definition["table"],
        "source": definition["source"],
        "update_mechanism": definition["update_mechanism"],
        "consumer": definition["consumer"],
        "latest": _dataset_latest(table, quality_row),
        "range": table.get("date_range"),
        "rows": int(table.get("row_count") or quality_row.get("row_count") or 0),
        "symbols": symbols,
        "expected_symbols": expected,
        "coverage_ratio": coverage,
        "status": status,
        "issues": [str(issue) for issue in definition.get("issues", [])],
    }


def _nested_quality(quality: dict[str, Any], path: Any) -> dict[str, Any]:
    if not path:
        return {}
    current: Any = quality
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _quality_symbol_count(quality_row: dict[str, Any], table: dict[str, Any]) -> int:
    for key in ("covered_symbols", "latest_symbol_count", "symbol_count"):
        if key in quality_row:
            return int(quality_row.get(key) or 0)
    return int(table.get("symbol_count") or 0)


def _dataset_latest(table: dict[str, Any], quality_row: dict[str, Any]) -> str | None:
    for key in ("latest_date", "latest_datetime", "latest_bucket"):
        if quality_row.get(key):
            return str(quality_row[key])
    return (table.get("date_range") or {}).get("end")


def _table_presence_status(table: dict[str, Any] | None) -> str:
    if not table or table.get("error"):
        return "missing"
    return "ok" if int(table.get("row_count") or 0) > 0 else "missing"


def _dataset_issues(prefix: str, quality: dict[str, Any]) -> list[str]:
    return [
        str(issue)
        for issue in quality.get("issues", [])
        if str(issue).startswith(prefix)
    ]


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
    as_of: date | None = None,
) -> dict[str, Any]:
    non_st_count = int(stock_summary.get("non_st_stock_count") or 0)
    daily = tables.get("daily_kline", {})
    minute5 = tables.get("minute5_kline", {})
    daily_latest = (daily.get("date_range") or {}).get("end")
    minute5_latest = (minute5.get("date_range") or {}).get("end")
    daily_latest_symbols = _latest_symbol_count(
        client=client,
        table="daily_kline",
        date_col="date",
        latest=daily_latest,
        non_st_only=True,
    )
    minute5_latest_symbols = _latest_symbol_count(
        client=client,
        table="minute5_kline",
        date_col="datetime",
        latest=minute5_latest,
        non_st_only=True,
    )
    daily_expected_symbols = (
        minute5_latest_symbols
        if _as_date(daily_latest) is not None
        and _as_date(daily_latest) == _as_date(minute5_latest)
        and minute5_latest_symbols > 0
        else non_st_count
    )
    minute5_expected_symbols = _active_daily_symbol_count(
        client=client,
        latest=minute5_latest,
        fallback=non_st_count,
    )
    minute5_complete_latest, minute5_complete_symbols = _latest_complete_intraday_bucket(
        client=client,
        table="minute5_kline",
        date_col="datetime",
        latest=minute5_latest,
        expected=minute5_expected_symbols,
        non_st_only=True,
    )
    daily_check = _coverage_check(
        latest=daily_latest,
        covered=daily_latest_symbols,
        expected=daily_expected_symbols,
        latest_key="latest_date",
    )
    daily_check["expected_symbols"] = daily_expected_symbols
    minute5_check = _coverage_check(
        latest=minute5_complete_latest or minute5_latest,
        covered=minute5_complete_symbols if minute5_complete_latest else minute5_latest_symbols,
        expected=minute5_expected_symbols,
        latest_key="latest_datetime",
    )
    minute5_check["expected_symbols"] = minute5_expected_symbols
    minute5_check["current_latest_datetime"] = minute5_latest
    minute5_check["current_covered_symbols"] = minute5_latest_symbols
    minute5_check["current_coverage_ratio"] = _coverage_ratio(minute5_latest_symbols, minute5_expected_symbols)
    minute5_duplicates = _safe_minute5_duplicate_stats(client)
    minute5_check.update(minute5_duplicates)
    if daily_check["missing_symbols"] > 0:
        samples = _missing_symbol_samples(
            client=client,
            table="daily_kline",
            date_col="date",
            latest=daily_check["latest_date"],
            non_st_only=True,
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
            active_daily_only=True,
        )
        if samples:
            minute5_check["missing_samples"] = samples
    issues = []
    if daily_check["missing_symbols"] > 0:
        issues.append(f"daily_kline_missing_{daily_check['missing_symbols']}_symbols")
    if minute5_check["missing_symbols"] > 0:
        issues.append(f"minute5_kline_missing_{minute5_check['missing_symbols']}_symbols")
    if minute5_check.get("extra_rows", 0) > 0:
        issues.append(f"minute5_kline_duplicate_{minute5_check['extra_rows']}_extra_rows")
        if minute5_check["status"] == "ok":
            minute5_check["status"] = "warning"
    quote_snapshot_check = _quote_snapshot_quality(
        client=client,
        tables=tables,
        expected_symbols=non_st_count,
    )
    issues.extend(quote_snapshot_check["issues"])
    scheduled_checks = _scheduled_data_quality_checks(
        client=client,
        latest_daily_date=daily_latest,
        as_of=as_of,
    )
    issues.extend(scheduled_checks["issues"])
    statuses = {
        daily_check["status"],
        minute5_check["status"],
        quote_snapshot_check["status"],
        scheduled_checks["status"],
    }
    status = "missing" if "missing" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": status,
        "expected_non_st_symbols": non_st_count,
        "daily": daily_check,
        "minute5": minute5_check,
        "quote_snapshots": quote_snapshot_check,
        "scheduled_checks": scheduled_checks,
        "issues": issues,
    }


def _safe_minute5_duplicate_stats(client: Any) -> dict[str, int]:
    try:
        return minute5_duplicate_stats(client=client)
    except Exception:  # noqa: BLE001 - keep data dashboard best-effort.
        return {"duplicate_groups": 0, "extra_rows": 0}


def _quality_health_rows(quality: dict[str, Any], checked_at: datetime) -> list[tuple]:
    checks = [
        ("daily", quality.get("daily") or {}),
        ("minute5", quality.get("minute5") or {}),
        ("quote_snapshots", quality.get("quote_snapshots") or {}),
    ]
    scheduled = quality.get("scheduled_checks") or {}
    checks.extend(
        [
            ("scheduled_completeness_30d", scheduled.get("completeness_30d") or {}),
            ("scheduled_today_anomalies", scheduled.get("today_anomalies") or {}),
            ("scheduled_freshness", scheduled.get("freshness") or {}),
        ]
    )
    rows = []
    for name, details in checks:
        status = str(details.get("status") or "unknown")
        rows.append(
            (
                checked_at,
                name,
                status,
                1 if status == "ok" else 0,
                _quality_check_message(name, details),
                json.dumps(details, ensure_ascii=False, default=str, sort_keys=True),
            )
        )
    if quality.get("issues"):
        rows.append(
            (
                checked_at,
                "overall_issues",
                str(quality.get("status") or "unknown"),
                1 if quality.get("status") == "ok" else 0,
                ", ".join(str(issue) for issue in quality.get("issues", [])),
                json.dumps({"issues": quality.get("issues", [])}, ensure_ascii=False, default=str, sort_keys=True),
            )
        )
    return rows


def _quality_check_message(name: str, details: dict[str, Any]) -> str:
    if name == "daily":
        return (
            f"latest={details.get('latest_date')}, "
            f"coverage={details.get('covered_symbols')}/{details.get('covered_symbols', 0) + details.get('missing_symbols', 0)}"
        )
    if name == "minute5":
        return (
            f"latest={details.get('latest_datetime')}, "
            f"coverage={details.get('covered_symbols')}/{details.get('expected_symbols')}, "
            f"duplicates={details.get('extra_rows', 0)}"
        )
    if name == "quote_snapshots":
        raw = details.get("raw") or {}
        return (
            f"latest={raw.get('latest_datetime')}, "
            f"coverage={raw.get('latest_symbol_count')}/{details.get('expected_symbols')}, "
            f"missing_rate={raw.get('missing_rate')}"
        )
    if name == "scheduled_completeness_30d":
        return f"affected_symbols={details.get('affected_symbols')}"
    if name == "scheduled_today_anomalies":
        return f"bad_rows={details.get('bad_rows')}"
    if name == "scheduled_freshness":
        return f"lag_days={details.get('lag_days')}, max_lag_days={details.get('max_lag_days')}"
    return str(details.get("status") or "")


def _scheduled_data_quality_checks(
    *,
    client: Any,
    latest_daily_date: Any,
    as_of: date | None = None,
    completeness_window_days: int = 30,
    min_required_days: int = 15,
    max_lag_days: int = 3,
) -> dict[str, Any]:
    as_of_date = as_of or date.today()
    completeness = _daily_completeness_check(
        client=client,
        latest=latest_daily_date,
        window_days=completeness_window_days,
        min_required_days=min_required_days,
    )
    anomalies = _daily_today_anomaly_check(client=client, latest=latest_daily_date)
    freshness = _daily_freshness_check(
        client=client,
        latest=latest_daily_date,
        as_of=as_of_date,
        max_lag_days=max_lag_days,
    )
    issues = [*completeness["issues"], *anomalies["issues"], *freshness["issues"]]
    statuses = {completeness["status"], anomalies["status"], freshness["status"]}
    status = "missing" if "missing" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": status,
        "completeness_30d": {key: value for key, value in completeness.items() if key != "issues"},
        "today_anomalies": {key: value for key, value in anomalies.items() if key != "issues"},
        "freshness": {key: value for key, value in freshness.items() if key != "issues"},
        "issues": issues,
    }


def _daily_completeness_check(
    *,
    client: Any,
    latest: Any,
    window_days: int,
    min_required_days: int,
    sample_limit: int = 20,
) -> dict[str, Any]:
    if not latest:
        return {
            "status": "missing",
            "window_days": window_days,
            "min_required_days": min_required_days,
            "affected_symbols": 0,
            "samples": [],
            "issues": ["daily_kline_missing"],
        }
    try:
        latest_date = _as_date(latest)
        window_start = latest_date - timedelta(days=window_days - 1) if latest_date else None
        rows = client.execute(
            """
            select count() as affected_symbols
            from (
                select s.symbol, countDistinct(k.date) as daily_days
                from stocks s
                left join daily_kline k
                    on s.symbol = k.symbol
                    and k.date >= %(window_start)s
                    and k.date <= %(latest)s
                where upper(s.name) not like '%%ST%%'
                    and s.name not like '%%退市%%'
                    and (
                        toDateOrNull(nullIf(s.list_date, '')) is null
                        or toDateOrNull(nullIf(s.list_date, '')) <= %(window_start)s
                    )
                group by s.symbol
                having daily_days < %(min_required_days)s
            )
            """,
            {
                "latest": latest_date,
                "window_start": window_start,
                "min_required_days": int(min_required_days),
            },
        )
        affected = int(rows[0][0] or 0) if rows else 0
        samples = client.execute(
            """
            select s.symbol, any(s.name) as name, countDistinct(k.date) as daily_days
            from stocks s
            left join daily_kline k
                on s.symbol = k.symbol
                and k.date >= %(window_start)s
                and k.date <= %(latest)s
            where upper(s.name) not like '%%ST%%'
                and s.name not like '%%退市%%'
                and (
                    toDateOrNull(nullIf(s.list_date, '')) is null
                    or toDateOrNull(nullIf(s.list_date, '')) <= %(window_start)s
                )
            group by s.symbol
            having daily_days < %(min_required_days)s
            order by daily_days asc, s.symbol
            limit %(limit)s
            """,
            {
                "latest": latest_date,
                "window_start": window_start,
                "min_required_days": int(min_required_days),
                "limit": int(sample_limit),
            },
        )
    except Exception as exc:  # noqa: BLE001 - data quality checks should not break status API.
        return {
            "status": "warning",
            "window_days": window_days,
            "min_required_days": min_required_days,
            "affected_symbols": 0,
            "samples": [],
            "error": str(exc),
            "issues": ["daily_kline_30d_completeness_check_failed"],
        }
    issues = [f"daily_kline_30d_incomplete_{affected}_symbols"] if affected > 0 else []
    return {
        "status": "warning" if affected > 0 else "ok",
        "window_days": window_days,
        "min_required_days": min_required_days,
        "affected_symbols": affected,
        "samples": [
            {"symbol": format_symbol(str(symbol)), "name": str(name or ""), "data_days": int(days or 0)}
            for symbol, name, days in samples
        ],
        "issues": issues,
    }


def _daily_today_anomaly_check(*, client: Any, latest: Any, sample_limit: int = 20) -> dict[str, Any]:
    if not latest:
        return {
            "status": "missing",
            "latest_date": None,
            "bad_rows": 0,
            "samples": [],
            "issues": ["daily_kline_missing"],
        }
    try:
        rows = client.execute(
            """
            select count() as bad_rows
            from daily_kline
            where date = %(latest)s
                and (open <= 0 or high <= 0 or low <= 0 or close <= 0 or volume <= 0)
            """,
            {"latest": _as_date(latest)},
        )
        bad_rows = int(rows[0][0] or 0) if rows else 0
        samples = client.execute(
            """
            select symbol, date, open, high, low, close, volume
            from daily_kline k
            where date = %(latest)s
                and (open <= 0 or high <= 0 or low <= 0 or close <= 0 or volume <= 0)
            order by symbol
            limit %(limit)s
            """,
            {"latest": _as_date(latest), "limit": int(sample_limit)},
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "warning",
            "latest_date": _format_status_value(latest),
            "bad_rows": 0,
            "samples": [],
            "error": str(exc),
            "issues": ["daily_kline_today_anomaly_check_failed"],
        }
    issues = [f"daily_kline_today_anomalies_{bad_rows}_rows"] if bad_rows > 0 else []
    return {
        "status": "warning" if bad_rows > 0 else "ok",
        "latest_date": _format_status_value(latest),
        "bad_rows": bad_rows,
        "samples": [
            {
                "symbol": format_symbol(str(symbol)),
                "date": _format_status_value(day),
                "open": float(open_ or 0),
                "high": float(high or 0),
                "low": float(low or 0),
                "close": float(close or 0),
                "volume": float(volume or 0),
            }
            for symbol, day, open_, high, low, close, volume in samples
        ],
        "issues": issues,
    }


def _daily_freshness_check(*, latest: Any, as_of: date, max_lag_days: int, client: Any | None = None) -> dict[str, Any]:
    latest_date = _as_date(latest)
    if latest_date is None:
        return {
            "status": "missing",
            "latest_date": None,
            "as_of_date": as_of.isoformat(),
            "lag_days": None,
            "expected_latest_date": None,
            "trading_lag_days": None,
            "max_lag_days": max_lag_days,
            "issues": ["daily_kline_missing"],
        }
    expected_latest = _expected_latest_daily_date(client=client, as_of=as_of) if client is not None else None
    compare_date = expected_latest or as_of
    lag_days = max(0, (as_of - latest_date).days)
    trading_lag_days = _daily_trading_lag_days(
        client=client,
        latest=latest_date,
        expected=compare_date,
    ) if client is not None else None
    effective_lag = trading_lag_days if trading_lag_days is not None else lag_days
    issues = [f"daily_kline_stale_{effective_lag}_days"] if effective_lag > max_lag_days else []
    return {
        "status": "warning" if effective_lag > max_lag_days else "ok",
        "latest_date": latest_date.isoformat(),
        "as_of_date": as_of.isoformat(),
        "lag_days": lag_days,
        "expected_latest_date": compare_date.isoformat(),
        "trading_lag_days": trading_lag_days,
        "max_lag_days": max_lag_days,
        "issues": issues,
    }


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.date()
            except ValueError:
                continue
    return None


def _quote_snapshot_quality(
    *,
    client: Any,
    tables: dict[str, dict[str, Any]],
    expected_symbols: int,
) -> dict[str, Any]:
    raw_table = "stock_quote_snapshots"
    raw_status = tables.get(raw_table, {})
    raw_latest = (raw_status.get("date_range") or {}).get("end")
    raw_latest_symbols = _latest_quote_symbol_count(
        client=client,
        table=raw_table,
        date_col="snapshot_at",
        latest=raw_latest,
    )
    interval_stats = _quote_snapshot_interval_stats(
        client=client,
        expected_interval_seconds=QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS,
    )
    recent_windows = {
        "5m": _quote_snapshot_interval_stats(
            client=client,
            expected_interval_seconds=QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS,
            recent_minutes=5,
        ),
        "30m": _quote_snapshot_interval_stats(
            client=client,
            expected_interval_seconds=QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS,
            recent_minutes=30,
        ),
    }
    raw = {
        "table": raw_table,
        "latest_datetime": raw_latest,
        "row_count": int(raw_status.get("row_count") or 0),
        "symbol_count": int(raw_status.get("symbol_count") or 0),
        "latest_symbol_count": raw_latest_symbols,
        "missing_symbols": max(0, expected_symbols - raw_latest_symbols),
        "coverage_ratio": _coverage_ratio(raw_latest_symbols, expected_symbols),
        "retention_days": QUOTE_SNAPSHOT_RAW_RETENTION_DAYS,
        "expected_interval_seconds": QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS,
        **interval_stats,
        "recent_windows": recent_windows,
    }
    raw["status"] = _quote_layer_status(
        latest=raw_latest,
        missing_symbols=int(raw["missing_symbols"]),
        row_count=int(raw["row_count"]),
    )
    if raw["status"] == "ok" and raw["missing_rate"] > 0.2:
        raw["status"] = "warning"

    rollups = {
        label: _quote_rollup_quality(
            client=client,
            tables=tables,
            label=label,
            table=str(spec["table"]),
            bucket_seconds=int(spec["bucket_seconds"]),
            expected_symbols=expected_symbols,
        )
        for label, spec in QUOTE_SNAPSHOT_ROLLUPS.items()
    }

    issues: list[str] = []
    if raw["status"] == "missing":
        issues.append("stock_quote_snapshots_missing")
    elif raw["missing_symbols"] > 0:
        issues.append(f"stock_quote_snapshots_missing_{raw['missing_symbols']}_symbols")
    if raw["missing_rate"] > 0.2:
        issues.append(f"stock_quote_snapshots_interval_missing_rate_{raw['missing_rate']:.2f}")
    for label, rollup in rollups.items():
        if rollup["status"] == "missing":
            issues.append(f"stock_quote_snapshots_{label}_missing")
        elif rollup["missing_symbols"] > 0:
            issues.append(f"stock_quote_snapshots_{label}_missing_{rollup['missing_symbols']}_symbols")

    statuses = {raw["status"], *(rollup["status"] for rollup in rollups.values())}
    status = "missing" if "missing" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": status,
        "expected_symbols": expected_symbols,
        "expected_interval_seconds": QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS,
        "raw_retention_days": QUOTE_SNAPSHOT_RAW_RETENTION_DAYS,
        "aggregate_retention_days": QUOTE_SNAPSHOT_AGGREGATE_RETENTION_DAYS,
        "raw": raw,
        "rollups": rollups,
        "issues": issues,
    }


def _quote_rollup_quality(
    *,
    client: Any,
    tables: dict[str, dict[str, Any]],
    label: str,
    table: str,
    bucket_seconds: int,
    expected_symbols: int,
) -> dict[str, Any]:
    del label
    status = tables.get(table, {})
    latest = (status.get("date_range") or {}).get("end")
    latest_symbols = _latest_quote_symbol_count(
        client=client,
        table=table,
        date_col="bucket_start",
        latest=latest,
    )
    row_count = int(status.get("row_count") or 0)
    missing_symbols = max(0, expected_symbols - latest_symbols)
    return {
        "table": table,
        "latest_bucket": latest,
        "row_count": row_count,
        "symbol_count": int(status.get("symbol_count") or 0),
        "latest_symbol_count": latest_symbols,
        "missing_symbols": missing_symbols,
        "coverage_ratio": _coverage_ratio(latest_symbols, expected_symbols),
        "retention_days": QUOTE_SNAPSHOT_AGGREGATE_RETENTION_DAYS,
        "bucket_seconds": bucket_seconds,
        "status": _quote_layer_status(
            latest=latest,
            missing_symbols=missing_symbols,
            row_count=row_count,
        ),
    }


def _latest_quote_symbol_count(
    *,
    client: Any,
    table: str,
    date_col: str,
    latest: Any,
) -> int:
    if not latest:
        return 0
    rows = client.execute(
        f"""
        select uniqExact(symbol)
        from {table}
        where {date_col} = %(latest)s
        """,
        {"latest": latest},
    )
    return int(rows[0][0] or 0) if rows else 0


def _quote_snapshot_interval_stats(
    *,
    client: Any,
    expected_interval_seconds: int,
    limit: int = 120,
    recent_minutes: int | None = None,
) -> dict[str, Any]:
    where_clause = ""
    if recent_minutes is not None:
        where_clause = f"where snapshot_at >= now() - interval {int(recent_minutes)} minute"
    try:
        rows = client.execute(
            f"""
            select snapshot_at, count()
            from stock_quote_snapshots
            {where_clause}
            group by snapshot_at
            order by snapshot_at desc
            limit %(limit)s
            """,
            {"limit": limit},
        )
    except Exception:  # noqa: BLE001 - keep data quality inspection best-effort.
        rows = []
    parsed = [_coerce_datetime(row[0]) for row in rows]
    timestamps = sorted(value for value in parsed if value is not None)
    observed = len(timestamps)
    if observed < 2:
        return {
            "observed_rounds": observed,
            "expected_rounds": observed,
            "missing_rounds": 0,
            "missing_rate": 0.0,
            "actual_avg_interval_seconds": None,
        }
    span_seconds = max(0.0, (timestamps[-1] - timestamps[0]).total_seconds())
    expected_rounds = int(span_seconds // expected_interval_seconds) + 1
    missing_rounds = max(0, expected_rounds - observed)
    gaps = [
        (timestamps[index] - timestamps[index - 1]).total_seconds()
        for index in range(1, observed)
    ]
    return {
        "observed_rounds": observed,
        "expected_rounds": expected_rounds,
        "missing_rounds": missing_rounds,
        "missing_rate": round(missing_rounds / expected_rounds, 6) if expected_rounds else 0.0,
        "actual_avg_interval_seconds": round(sum(gaps) / len(gaps), 3) if gaps else None,
    }


def _coverage_ratio(covered: int, expected: int) -> float:
    return round(min(1.0, covered / expected), 6) if expected else 0.0


def _quote_layer_status(*, latest: Any, missing_symbols: int, row_count: int) -> str:
    if not latest or row_count <= 0:
        return "missing"
    if missing_symbols > 0:
        return "warning"
    return "ok"


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _missing_symbol_samples(
    *,
    client: Any,
    table: str,
    date_col: str,
    latest: Any,
    non_st_only: bool,
    active_daily_only: bool = False,
    limit: int = 20,
) -> list[dict[str, str]]:
    if not latest:
        return []
    non_st_filter = "and upper(s.name) not like '%%ST%%'" if non_st_only else ""
    active_join = ""
    active_filter = ""
    if active_daily_only:
        active_join = """
        inner join daily_kline d
            on s.symbol = d.symbol and d.date = toDate(%(latest)s)
        """
        active_filter = "and d.volume >= 1 and d.amount >= 1"
    rows = client.execute(
        f"""
        select s.symbol, s.name
        from stocks s
        {active_join}
        left join {table} k
            on s.symbol = k.symbol and k.{date_col} = %(latest)s
        where k.symbol = '' {non_st_filter} {active_filter}
        order by s.symbol
        limit %(limit)s
        """,
        {"latest": latest, "limit": limit},
    )
    return [
        {"symbol": format_symbol(str(symbol)), "name": str(name or "")}
        for symbol, name in rows
    ]


def _latest_symbol_count(
    *,
    client: Any,
    table: str,
    date_col: str,
    latest: Any,
    non_st_only: bool,
) -> int:
    if not latest:
        return 0
    non_st_filter = "and upper(s.name) not like '%%ST%%'" if non_st_only else ""
    rows = client.execute(
        f"""
        select uniqExact(k.symbol)
        from {table} k
        inner join stocks s on k.symbol = s.symbol
        where k.{date_col} = %(latest)s {non_st_filter}
        """,
        {"latest": latest},
    )
    return int(rows[0][0] or 0) if rows else 0


def _latest_complete_intraday_bucket(
    *,
    client: Any,
    table: str,
    date_col: str,
    latest: Any,
    expected: int,
    non_st_only: bool,
    min_coverage: float = 0.95,
) -> tuple[Any | None, int]:
    if not latest or expected <= 0:
        return None, 0
    latest_dt = _coerce_datetime(latest)
    if latest_dt is None:
        return None, 0
    non_st_filter = "and upper(s.name) not like '%%ST%%'" if non_st_only else ""
    min_symbols = max(1, int(expected * min_coverage))
    try:
        rows = client.execute(
            f"""
            select k.{date_col}, uniqExact(k.symbol) as covered
            from {table} k
            inner join stocks s on k.symbol = s.symbol
            where toDate(k.{date_col}) = toDate(%(latest)s)
                and k.{date_col} <= %(latest)s
                {non_st_filter}
            group by k.{date_col}
            having covered >= %(min_symbols)s
            order by k.{date_col} desc
            limit 1
            """,
            {"latest": latest_dt, "min_symbols": min_symbols},
        )
    except Exception:  # noqa: BLE001 - fallback keeps health checks available.
        return None, 0
    if not rows:
        return None, 0
    if len(rows[0]) < 2 or not isinstance(rows[0][1], (int, float)):
        return None, 0
    return _format_status_value(rows[0][0]), int(rows[0][1] or 0)


def _active_daily_symbol_count(*, client: Any, latest: Any, fallback: int) -> int:
    if not latest:
        return fallback
    try:
        rows = client.execute(
            """
            select count()
            from stocks s
            inner join daily_kline d
                on s.symbol = d.symbol and d.date = toDate(%(latest)s)
            where upper(s.name) not like '%%ST%%'
                and d.volume >= 1
                and d.amount >= 1
            """,
            {"latest": latest},
        )
    except Exception:  # noqa: BLE001 - fallback keeps health checks available.
        return fallback
    active = int(rows[0][0] or 0) if rows else 0
    return active if active > 0 else fallback


def _expected_latest_daily_date(*, client: Any, as_of: date) -> date | None:
    try:
        rows = client.execute(
            """
            select max(date)
            from trade_calendar
            where date < %(as_of)s
            """,
            {"as_of": as_of},
        )
    except Exception:  # noqa: BLE001 - fallback to natural-day freshness.
        return None
    value = rows[0][0] if rows else None
    return _as_date(value)


def _daily_trading_lag_days(*, client: Any | None, latest: date, expected: date) -> int | None:
    if client is None:
        return None
    if latest >= expected:
        return 0
    try:
        rows = client.execute(
            """
            select count()
            from trade_calendar
            where date > %(latest)s and date <= %(expected)s
            """,
            {"latest": latest, "expected": expected},
        )
    except Exception:  # noqa: BLE001 - fallback to natural-day freshness.
        return None
    return int(rows[0][0] or 0) if rows else 0


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
