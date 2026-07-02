"""Data coverage and health inspection for the local stock database."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from src.core.constants import format_symbol, is_st
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.clickhouse_table_maintenance import daily_duplicate_stats, minute5_duplicate_stats
from src.data.strategy_universe import StrategyUniverseOptions, resolve_strategy_universe


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
    "stock_research_status": {"date_col": "checked_at", "symbol_col": "symbol"},
    "data_source_health": {"date_col": "checked_at"},
    "fund_tail_nav": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_proxy": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_benchmark": {"date_col": "date"},
    "fund_watchlist": {"date_col": "updated_at", "symbol_col": "fund_code"},
}

CLICKHOUSE_TABLE_SPECS = {
    "stocks": {"symbol_col": "symbol", "date_col": "updated_at"},
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
    "stock_research_status": {"date_col": "checked_at", "symbol_col": "symbol"},
    "data_source_health": {"date_col": "checked_at"},
    "fund_tail_nav": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_proxy": {"date_col": "date", "symbol_col": "fund_code"},
    "fund_tail_benchmark": {"date_col": "date"},
    "fund_watchlist": {"date_col": "updated_at", "symbol_col": "fund_code"},
}

QUOTE_SNAPSHOT_EXPECTED_INTERVAL_SECONDS = 10
QUOTE_SNAPSHOT_RAW_RETENTION_DAYS = 120
QUOTE_SNAPSHOT_AGGREGATE_RETENTION_DAYS = 1095
QUOTE_MARKET_MORNING_START = time(9, 30)
QUOTE_MARKET_MORNING_END = time(11, 30)
QUOTE_MARKET_AFTERNOON_START = time(13, 0)
QUOTE_MARKET_AFTERNOON_END = time(15, 0)
_NON_ST_NAME_PREDICATE = "not match(upper(s.name), '^(\\\\*ST|S\\\\*ST|SST|ST)([^A-Z]|$)')"
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
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Return read-only coverage metrics for the ClickHouse stock database."""
    source = ClickHouseStockDataSource(
        host=host if host is not None else "localhost" if client is not None else None,
        user=user,
        password=password,
        database=database if database is not None else "stock" if client is not None else None,
    )
    db_info = {
        "type": "clickhouse",
        "host": source.host,
        "database": source.database,
        "exists": True,
        "size_bytes": 0,
    }
    clickhouse = client or source._client_instance()

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
        research_summary = _stock_research_summary(clickhouse) if "stock_research_status" in available_tables else _empty_research_summary()
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
        "research_summary": research_summary,
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
            research_summary=research_summary,
            quality=quality,
        ),
    }


def persist_clickhouse_quality_snapshot(
    *,
    client: Any | None = None,
    quality: dict[str, Any] | None = None,
    checked_at: datetime | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, Any]:
    """Persist the current ClickHouse data quality result for historical review."""
    source = ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
    clickhouse = client or source._client_instance()
    snapshot_time = checked_at or datetime.now()
    quality_payload = quality or inspect_clickhouse_database(
        client=clickhouse,
        host=source.host,
        user=source.user,
        password=source.password,
        database=source.database,
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
    research_summary: dict[str, Any] | None = None,
    quality: dict[str, Any],
) -> list[dict[str, Any]]:
    non_st_count = int(stock_summary.get("non_st_stock_count") or 0)
    expected_all = int(stock_summary.get("stock_count") or 0)
    quote_quality = quality.get("quote_snapshots") or {}
    scheduled = quality.get("scheduled_checks") or {}
    fund_tail_nav_issues = _fund_tail_nav_freshness_issues(tables)
    fund_tail_nav_status = _table_presence_status(tables.get("fund_tail_nav"))
    if fund_tail_nav_status == "ok" and fund_tail_nav_issues:
        fund_tail_nav_status = "warning"
    definitions = [
        {
            "key": "research_universe",
            "name": "默认研究股票池",
            "category": "研究口径",
            "table": "stock_research_status",
            "source": "stock_master_sync 生成的研究池状态",
            "update_mechanism": "股票主数据更新后同步生成研究池标签，并审计日线与 5m 缺口。",
            "consumer": "健康矩阵、数据日历、策略候选池、回测样本选择",
            "quality_rules": ["研究池纳入规则", "未纳入原因标签", "日线缺口", "5m 缺口"],
            "repair_action_keys": ["stock_master_sync", "daily_history_backfill", "minute5_sync"],
            "expected_symbols": int((research_summary or {}).get("total") or 0),
            "symbols": int((research_summary or {}).get("eligible") or 0),
            "status": _research_summary_status(research_summary),
            "issues": _research_summary_issues(research_summary),
        },
        {
            "key": "stocks",
            "name": "股票基础信息",
            "category": "基础数据",
            "table": "stocks",
            "source": "ClickHouse / stocks",
            "update_mechanism": "股票主数据同步任务（stock_master_sync）按调度从腾讯股票池接口拉取并更新，作为股票池和 ST 过滤基准。",
            "consumer": "全市场扫描、股票名称展示、非 ST 标的池",
            "quality_rules": ["基础表存在"],
            "repair_action_keys": [],
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
            "quality_rules": ["基础表存在", "交易日连续性", "最新交易日判断"],
            "repair_action_keys": [],
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
            "quality_rules": ["最新交易日覆盖率", "重复日线主键", "OHLC 合法性", "日线新鲜度"],
            "repair_action_keys": ["daily_from_minute5", "daily_history_backfill", "daily_historical_invalid_prices"],
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
            "quality_rules": ["基础表存在", "最新时间", "标的覆盖"],
            "repair_action_keys": [],
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
            "quality_rules": ["最新完整 5m 桶覆盖率", "当前最新桶覆盖率", "重复分钟主键"],
            "repair_action_keys": ["minute5_sync"],
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
            "quality_rules": ["最新快照覆盖率", "10 秒采集节拍", "原始快照缺失轮次"],
            "repair_action_keys": ["quote_snapshot_sync"],
            "quality_key": ("quote_snapshots", "raw"),
            "expected_symbols": quote_quality.get("expected_symbols", non_st_count),
        },
        {
            "key": "stock_quote_snapshots_1m",
            "name": "1m 快照聚合",
            "category": "聚合数据",
            "table": "stock_quote_snapshots_1m",
            "source": "stock_quote_snapshots 聚合",
            "update_mechanism": "快照采集任务每轮写入后自动滚动聚合，保留长周期。",
            "consumer": "盘中复盘、短线统计、快照降采样",
            "quality_rules": ["最新聚合桶覆盖率", "聚合重复主键", "保留周期"],
            "repair_action_keys": ["quote_snapshot_sync", "quote_rollup_optimize"],
            "quality_key": ("quote_snapshots", "rollups", "1m"),
            "expected_symbols": quote_quality.get("expected_symbols", non_st_count),
        },
        {
            "key": "stock_quote_snapshots_5m",
            "name": "5m 快照聚合",
            "category": "聚合数据",
            "table": "stock_quote_snapshots_5m",
            "source": "stock_quote_snapshots 聚合",
            "update_mechanism": "快照采集任务每轮写入后自动滚动聚合，可作为 5m 分钟线实时兜底。",
            "consumer": "尾盘选股 5m 兜底、个股趋势、盘中验证",
            "quality_rules": ["最新聚合桶覆盖率", "聚合重复主键", "5m 兜底可用性"],
            "repair_action_keys": ["quote_snapshot_sync", "quote_rollup_optimize"],
            "quality_key": ("quote_snapshots", "rollups", "5m"),
            "expected_symbols": quote_quality.get("expected_symbols", non_st_count),
        },
        {
            "key": "index_daily",
            "name": "指数日线",
            "category": "基准数据",
            "table": "index_daily",
            "source": "AKShare 指数日线 / ClickHouse",
            "update_mechanism": "日常维护或专项补齐同步指数行情。",
            "consumer": "市场环境、基准对照、策略过滤",
            "quality_rules": ["基础表存在", "指数覆盖", "最新交易日"],
            "repair_action_keys": [],
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
            "quality_rules": ["基础表存在", "报告期覆盖", "标的覆盖"],
            "repair_action_keys": [],
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
            "update_mechanism": "基金尾盘建议生成时先刷新净值 CSV 并导入 ClickHouse，再刷新当日代理行情。",
            "consumer": "基金尾盘建议、基金复盘",
            "quality_rules": ["净值表存在", "净值日期不落后代理行情", "基金覆盖"],
            "repair_action_keys": [],
            "status": fund_tail_nav_status,
            "issues": fund_tail_nav_issues,
        },
        {
            "key": "fund_tail_proxy",
            "name": "基金代理行情",
            "category": "基金尾盘",
            "table": "fund_tail_proxy",
            "source": "代理指数/ETF 行情 / ClickHouse",
            "update_mechanism": "基金尾盘数据导入任务写入，用于估计基金盘中表现。",
            "consumer": "基金尾盘建议、代理趋势判断",
            "quality_rules": ["代理行情存在", "最新日期", "基金覆盖"],
            "repair_action_keys": [],
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
            "quality_rules": ["基准行情存在", "最新日期"],
            "repair_action_keys": [],
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
            "quality_rules": ["质量快照表存在", "最近检查结果", "定时检查告警"],
            "repair_action_keys": ["quality_snapshot"],
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
    symbols = int(definition["symbols"]) if "symbols" in definition else _quality_symbol_count(quality_row, table)
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
        "quality_rules": [str(rule) for rule in definition.get("quality_rules", [])],
        "repair_action_keys": [str(key) for key in definition.get("repair_action_keys", [])],
        "latest": _dataset_latest(table, quality_row),
        "range": table.get("date_range"),
        "rows": int(table.get("row_count") or quality_row.get("row_count") or 0),
        "symbols": symbols,
        "expected_symbols": expected,
        "coverage_ratio": coverage,
        "status": status,
        "issues": [str(issue) for issue in definition.get("issues", quality_row.get("issues", []))],
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


def _fund_tail_nav_freshness_issues(tables: dict[str, dict[str, Any]]) -> list[str]:
    nav_latest = _table_latest_date(tables.get("fund_tail_nav"))
    proxy_latest = _table_latest_date(tables.get("fund_tail_proxy"))
    if not nav_latest or not proxy_latest or nav_latest >= proxy_latest:
        return []
    nav_date = datetime.fromisoformat(nav_latest).date()
    proxy_date = datetime.fromisoformat(proxy_latest).date()
    if (proxy_date - nav_date).days <= 1:
        return []
    return [f"fund_tail_nav_stale_vs_proxy:{nav_latest}<{proxy_latest}"]


def _table_latest_date(table: dict[str, Any] | None) -> str | None:
    if not table:
        return None
    latest = (table.get("date_range") or {}).get("end")
    if latest is None:
        return None
    return str(latest).split(" ")[0]


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
    rows = conn.execute("select symbol, name from stocks").fetchall()
    stock_count = len(rows)
    st_stock_count = sum(1 for row in rows if is_st(str(row[1] or "")))
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
    rows = client.execute("select symbol, name from stocks")
    stock_count = len(rows)
    st_stock_count = 0
    for row in rows:
        values = tuple(row)
        name = str(values[1] if len(values) > 1 else "")
        if is_st(name):
            st_stock_count += 1
    return {
        "stock_count": stock_count,
        "non_st_stock_count": stock_count - st_stock_count,
        "st_stock_count": st_stock_count,
    }


def _empty_research_summary() -> dict[str, Any]:
    return {
        "total": 0,
        "eligible": 0,
        "excluded": 0,
        "daily_missing": 0,
        "minute5_missing": 0,
        "reason_counts": {},
    }


def _stock_research_summary(client: Any) -> dict[str, Any]:
    try:
        rows = client.execute(
            """
            select symbol, name, research_eligible, excluded_reasons, daily_missing, minute5_missing
            from stock_research_status final
            """
        )
    except Exception:  # noqa: BLE001 - optional table should not break data center.
        return _empty_research_summary()
    total = len(rows)
    eligible = 0
    daily_missing = 0
    minute5_missing = 0
    reason_counts: dict[str, int] = {}
    for _symbol, _name, research_eligible, excluded_reasons, row_daily_missing, row_minute5_missing in rows:
        if int(research_eligible or 0):
            eligible += 1
        if int(row_daily_missing or 0):
            daily_missing += 1
        if int(row_minute5_missing or 0):
            minute5_missing += 1
        for reason in _json_list(excluded_reasons):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "total": total,
        "eligible": eligible,
        "excluded": total - eligible,
        "daily_missing": daily_missing,
        "minute5_missing": minute5_missing,
        "reason_counts": reason_counts,
    }


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _research_summary_status(summary: dict[str, Any] | None) -> str:
    if not summary or int(summary.get("total") or 0) <= 0:
        return "missing"
    if int(summary.get("daily_missing") or 0) > 0 or int(summary.get("minute5_missing") or 0) > 0:
        return "warning"
    return "ok"


def _research_summary_issues(summary: dict[str, Any] | None) -> list[str]:
    if not summary or int(summary.get("total") or 0) <= 0:
        return ["research_universe_missing"]
    issues = []
    if int(summary.get("daily_missing") or 0) > 0:
        issues.append(f"research_daily_missing_{int(summary.get('daily_missing') or 0)}_symbols")
    if int(summary.get("minute5_missing") or 0) > 0:
        issues.append(f"research_minute5_missing_{int(summary.get('minute5_missing') or 0)}_symbols")
    return issues


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
    strategy_tradable_symbols = _strategy_tradable_symbol_count(
        client=client,
        latest=minute5_latest or daily_latest,
        fallback=non_st_count,
    )
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
    daily_expected_symbols = strategy_tradable_symbols
    minute5_expected_symbols = strategy_tradable_symbols
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
    daily_duplicates = _safe_daily_duplicate_stats(client)
    daily_check.update(daily_duplicates)
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
    if daily_check.get("extra_rows", 0) > 0:
        issues.append(f"daily_kline_duplicate_{daily_check['extra_rows']}_extra_rows")
        if daily_check["status"] == "ok":
            daily_check["status"] = "warning"
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
    ignored_issues = list(scheduled_checks.get("ignored_issues") or [])
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
        "expected_strategy_tradable_symbols": strategy_tradable_symbols,
        "daily": daily_check,
        "minute5": minute5_check,
        "quote_snapshots": quote_snapshot_check,
        "scheduled_checks": scheduled_checks,
        "issues": issues,
        "ignored_issues": ignored_issues,
    }


def _safe_minute5_duplicate_stats(client: Any) -> dict[str, int]:
    try:
        return minute5_duplicate_stats(client=client)
    except Exception:  # noqa: BLE001 - keep data dashboard best-effort.
        return {"duplicate_groups": 0, "extra_rows": 0}


def _safe_daily_duplicate_stats(client: Any) -> dict[str, int]:
    try:
        return daily_duplicate_stats(client=client)
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
            ("scheduled_historical_invalid_prices", scheduled.get("historical_invalid_prices") or {}),
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
    if name == "scheduled_historical_invalid_prices":
        return f"bad_rows={details.get('bad_rows')}, affected_symbols={details.get('affected_symbols')}"
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
    historical_invalid = _daily_historical_invalid_price_check(client=client)
    freshness = _daily_freshness_check(
        client=client,
        latest=latest_daily_date,
        as_of=as_of_date,
        max_lag_days=max_lag_days,
    )
    issues = [*anomalies["issues"], *historical_invalid["issues"], *freshness["issues"]]
    ignored_issues = [*completeness["issues"]]
    statuses = {anomalies["status"], historical_invalid["status"], freshness["status"]}
    status = "missing" if "missing" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": status,
        "completeness_30d": {
            **{key: value for key, value in completeness.items() if key != "issues"},
            "status": "ignored" if completeness["issues"] else completeness["status"],
        },
        "today_anomalies": {key: value for key, value in anomalies.items() if key != "issues"},
        "historical_invalid_prices": {key: value for key, value in historical_invalid.items() if key != "issues"},
        "freshness": {key: value for key, value in freshness.items() if key != "issues"},
        "issues": issues,
        "ignored_issues": ignored_issues,
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
            f"""
            select count() as affected_symbols
            from (
                select s.symbol, countDistinct(k.date) as daily_days
                from stocks s
                inner join daily_kline active
                    on s.symbol = active.symbol
                    and active.date = %(latest)s
                    and active.volume >= 1
                    and active.amount >= 1
                left join daily_kline k
                    on s.symbol = k.symbol
                    and k.date >= %(window_start)s
                    and k.date <= %(latest)s
                where {_NON_ST_NAME_PREDICATE}
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
            f"""
            select s.symbol, any(s.name) as name, countDistinct(k.date) as daily_days
            from stocks s
            inner join daily_kline active
                on s.symbol = active.symbol
                and active.date = %(latest)s
                and active.volume >= 1
                and active.amount >= 1
            left join daily_kline k
                on s.symbol = k.symbol
                and k.date >= %(window_start)s
                and k.date <= %(latest)s
            where {_NON_ST_NAME_PREDICATE}
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


def _daily_historical_invalid_price_check(*, client: Any, sample_limit: int = 20) -> dict[str, Any]:
    try:
        rows = client.execute(
            """
            with historical_invalid_prices as (
                select symbol, date, open, high, low, close
                from daily_kline
                where open <= 0 or high <= 0 or low <= 0 or close <= 0
            )
            select
                count() as bad_rows,
                uniqExact(symbol) as affected_symbols,
                min(date) as start_date,
                max(date) as end_date
            from historical_invalid_prices
            """
        )
        bad_rows, affected_symbols, start_date, end_date = rows[0] if rows else (0, 0, None, None)
        samples = client.execute(
            """
            with historical_invalid_prices as (
                select symbol, date, open, high, low, close
                from daily_kline
                where open <= 0 or high <= 0 or low <= 0 or close <= 0
            )
            select
                p.symbol,
                any(s.name) as name,
                count() as bad_rows,
                min(p.date) as start_date,
                max(p.date) as end_date
            from historical_invalid_prices p
            left join stocks s on p.symbol = s.symbol
            group by symbol
            order by bad_rows desc, symbol
            limit %(limit)s
            """,
            {"limit": int(sample_limit)},
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "warning",
            "bad_rows": 0,
            "affected_symbols": 0,
            "start_date": None,
            "end_date": None,
            "samples": [],
            "error": str(exc),
            "issues": ["daily_kline_historical_invalid_prices_check_failed"],
        }
    bad_count = int(bad_rows or 0)
    issues = [f"daily_kline_historical_invalid_prices_{bad_count}_rows"] if bad_count > 0 else []
    return {
        "status": "warning" if bad_count > 0 else "ok",
        "bad_rows": bad_count,
        "affected_symbols": int(affected_symbols or 0),
        "start_date": _format_status_value(start_date),
        "end_date": _format_status_value(end_date),
        "samples": [
            {
                "symbol": format_symbol(str(symbol)),
                "name": str(name or ""),
                "bad_rows": int(rows or 0),
                "start_date": _format_status_value(first_date),
                "end_date": _format_status_value(last_date),
            }
            for symbol, name, rows, first_date, last_date in samples
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
    raw["issues"] = _quote_raw_issues(raw)

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
    issues.extend(raw["issues"])
    for rollup in rollups.values():
        issues.extend(rollup["issues"])

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
    duplicate_stats = _quote_rollup_duplicate_stats(client=client, table=table)
    layer_status = _quote_layer_status(
        latest=latest,
        missing_symbols=missing_symbols,
        row_count=row_count,
    )
    if layer_status == "ok" and duplicate_stats["extra_rows"] > 0:
        layer_status = "warning"
    issues = _quote_rollup_issues(
        label=label,
        status=layer_status,
        missing_symbols=missing_symbols,
        extra_rows=duplicate_stats["extra_rows"],
    )
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
        "duplicate_groups": duplicate_stats["duplicate_groups"],
        "extra_rows": duplicate_stats["extra_rows"],
        "status": layer_status,
        "issues": issues,
    }


def _quote_raw_issues(raw: dict[str, Any]) -> list[str]:
    issues = []
    if raw["status"] == "missing":
        issues.append("stock_quote_snapshots_missing")
    elif int(raw.get("missing_symbols") or 0) > 0:
        issues.append(f"stock_quote_snapshots_missing_{raw['missing_symbols']}_symbols")
    if float(raw.get("missing_rate") or 0) > 0.2:
        issues.append(f"stock_quote_snapshots_interval_missing_rate_{raw['missing_rate']:.2f}")
    return issues


def _quote_rollup_issues(*, label: str, status: str, missing_symbols: int, extra_rows: int) -> list[str]:
    issues = []
    if status == "missing":
        issues.append(f"stock_quote_snapshots_{label}_missing")
    elif missing_symbols > 0:
        issues.append(f"stock_quote_snapshots_{label}_missing_{missing_symbols}_symbols")
    if extra_rows > 0:
        issues.append(f"stock_quote_snapshots_{label}_duplicate_{extra_rows}_extra_rows")
    return issues


def _quote_rollup_duplicate_stats(*, client: Any, table: str) -> dict[str, int]:
    try:
        rows = client.execute(
            f"""
            select count() as duplicate_groups, sum(c - 1) as extra_rows
            from (
                select symbol, bucket_start, source, count() as c
                from {table} final
                group by symbol, bucket_start, source
                having count() > 1
            )
            """
        )
    except Exception:  # noqa: BLE001 - keep rollup quality inspection best-effort.
        return {"duplicate_groups": 0, "extra_rows": 0}
    duplicate_groups, extra_rows = rows[0] if rows else (0, 0)
    return {"duplicate_groups": int(duplicate_groups or 0), "extra_rows": int(extra_rows or 0)}


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
    timestamps = sorted(value for value in parsed if value is not None and _is_quote_market_session(value))
    observed = len(timestamps)
    if observed < 2:
        return {
            "observed_rounds": observed,
            "expected_rounds": observed,
            "missing_rounds": 0,
            "missing_rate": 0.0,
            "actual_avg_interval_seconds": None,
        }
    missing_rounds = 0
    gaps = []
    for index in range(1, observed):
        previous = timestamps[index - 1]
        current = timestamps[index]
        if not _same_quote_market_segment(previous, current):
            continue
        gap = max(0.0, (current - previous).total_seconds())
        gaps.append(gap)
        missing_rounds += max(0, round(gap / expected_interval_seconds) - 1)
    expected_rounds = observed + missing_rounds
    return {
        "observed_rounds": observed,
        "expected_rounds": expected_rounds,
        "missing_rounds": missing_rounds,
        "missing_rate": round(missing_rounds / expected_rounds, 6) if expected_rounds else 0.0,
        "actual_avg_interval_seconds": round(sum(gaps) / len(gaps), 3) if gaps else None,
    }


def _is_quote_market_session(value: datetime) -> bool:
    current = value.time()
    return (
        QUOTE_MARKET_MORNING_START <= current <= QUOTE_MARKET_MORNING_END
        or QUOTE_MARKET_AFTERNOON_START <= current <= QUOTE_MARKET_AFTERNOON_END
    )


def _same_quote_market_segment(left: datetime, right: datetime) -> bool:
    if left.date() != right.date():
        return False
    left_time = left.time()
    right_time = right.time()
    return (
        QUOTE_MARKET_MORNING_START <= left_time <= QUOTE_MARKET_MORNING_END
        and QUOTE_MARKET_MORNING_START <= right_time <= QUOTE_MARKET_MORNING_END
    ) or (
        QUOTE_MARKET_AFTERNOON_START <= left_time <= QUOTE_MARKET_AFTERNOON_END
        and QUOTE_MARKET_AFTERNOON_START <= right_time <= QUOTE_MARKET_AFTERNOON_END
    )


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
    non_st_filter = f"and {_NON_ST_NAME_PREDICATE}" if non_st_only else ""
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
    non_st_filter = f"and {_NON_ST_NAME_PREDICATE}" if non_st_only else ""
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
    non_st_filter = f"and {_NON_ST_NAME_PREDICATE}" if non_st_only else ""
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


def _strategy_tradable_symbol_count(*, client: Any, latest: Any, fallback: int) -> int:
    if not latest:
        return fallback
    try:
        latest_rows = client.execute(
            """
            select max(date)
            from daily_kline
            where date <= toDate(%(latest)s)
                and volume >= 1
                and amount >= 1
            """,
            {"latest": latest},
        )
        latest_daily = latest_rows[0][0] if latest_rows else None
        if not latest_daily:
            return fallback
        rows = resolve_strategy_universe(
            client,
            StrategyUniverseOptions(
                trade_date=latest_daily,
                min_daily_bars=1,
                require_latest_daily=True,
                require_minute5=False,
                include_st=False,
                min_amount=0,
                markets=("SH", "SZ"),
            ),
        )
    except Exception:  # noqa: BLE001 - fallback keeps health checks available.
        return fallback
    active = len(rows)
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


def fetch_stock_list(client: Any | None = None) -> dict[str, Any]:
    """Return all stocks with their latest daily bar date.

    数据源为 ClickHouse `stock` 库。`is_st` 由 `is_st(name)` 推导(stocks 表无此列)。
    LEFT JOIN 保留有 stocks 记录但无任何日线的股票,其 `last_daily_date` 为 None。
    """
    if client is None:
        source = ClickHouseStockDataSource.from_env()
        if source is None:
            raise RuntimeError(
                "ClickHouse 未配置(STOCK_CLICKHOUSE_HOST 未设置),无法读取股票列表"
            )
        client = source._client_instance()

    try:
        rows = client.execute(
            """
            select
                s.symbol,
                s.name,
                s.industry,
                s.market,
                s.list_date,
                max(d.date) as last_daily_date,
                any(rs.research_eligible) as research_eligible,
                any(rs.excluded_reasons) as excluded_reasons,
                any(rs.daily_missing) as daily_missing,
                any(rs.minute5_missing) as minute5_missing
            from stocks s
            left join daily_kline d on d.symbol = s.symbol
            left join (
                select symbol, research_eligible, excluded_reasons, daily_missing, minute5_missing
                from stock_research_status final
            ) rs on rs.symbol = s.symbol
            group by s.symbol, s.name, s.industry, s.market, s.list_date
            order by s.symbol
            """
        )
    except Exception:
        rows = client.execute(
            """
            select
                s.symbol,
                s.name,
                s.industry,
                s.market,
                s.list_date,
                max(d.date) as last_daily_date
            from stocks s
            left join daily_kline d on d.symbol = s.symbol
            group by s.symbol, s.name, s.industry, s.market, s.list_date
            order by s.symbol
            """
        )

    items: list[dict[str, Any]] = []
    for row in rows:
        values = tuple(row)
        name = str(values[1] or "") if len(values) > 1 else ""
        list_date = values[4] if len(values) > 4 else None
        last_daily = values[5] if len(values) > 5 else None
        research_eligible = values[6] if len(values) > 6 else None
        items.append(
            {
                "symbol": str(values[0] or ""),
                "name": name,
                "industry": str(values[2] or "") if len(values) > 2 else "",
                "market": str(values[3] or "") if len(values) > 3 else "",
                "list_date": str(list_date) if list_date is not None else None,
                "last_daily_date": str(last_daily) if last_daily is not None else None,
                "is_st": is_st(name),
                "research_eligible": None if research_eligible is None else bool(research_eligible),
                "excluded_reasons": _json_list(values[7]) if len(values) > 7 else [],
                "daily_missing": None if len(values) <= 8 or values[8] is None else bool(values[8]),
                "minute5_missing": None if len(values) <= 9 or values[9] is None else bool(values[9]),
            }
        )

    return {"items": items, "total": len(items)}
