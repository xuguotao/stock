"""Task handlers for the standalone data operations runner."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

TaskHandler = Callable[[dict[str, Any]], dict[str, Any]]


def build_default_handlers(
    *,
    minute5_runner: Callable[..., dict[str, Any]] | None = None,
    quote_snapshot_runner: Callable[..., dict[str, Any]] | None = None,
    quote_rollup_runner: Callable[..., dict[str, Any]] | None = None,
    data_status_runner: Callable[..., dict[str, Any]] | None = None,
    quality_snapshot_writer: Callable[..., dict[str, Any]] | None = None,
    daily_repair_runner: Callable[..., dict[str, Any]] | None = None,
    index_daily_sync_runner: Callable[..., dict[str, Any]] | None = None,
    stock_master_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, TaskHandler]:
    if stock_master_runner is None:
        from src.data.clickhouse_stock_master_sync import sync_clickhouse_stock_master

        stock_master_runner = sync_clickhouse_stock_master
    if minute5_runner is None:
        from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline

        minute5_runner = sync_clickhouse_minute5_kline
    if quote_snapshot_runner is None:
        from src.data.clickhouse_quote_snapshot_sync import sync_clickhouse_quote_snapshots

        quote_snapshot_runner = sync_clickhouse_quote_snapshots
    if quote_rollup_runner is None:
        from src.data.clickhouse_table_maintenance import optimize_quote_snapshot_rollups

        quote_rollup_runner = optimize_quote_snapshot_rollups
    if data_status_runner is None:
        from src.web.backend.data_status import inspect_clickhouse_database

        data_status_runner = inspect_clickhouse_database
    if quality_snapshot_writer is None:
        from src.web.backend.data_status import persist_clickhouse_quality_snapshot

        quality_snapshot_writer = persist_clickhouse_quality_snapshot
    if daily_repair_runner is None:
        from src.data.clickhouse_daily_sync import sync_clickhouse_daily_from_minute5

        daily_repair_runner = sync_clickhouse_daily_from_minute5
    if index_daily_sync_runner is None:
        from src.data.clickhouse_daily_sync import sync_clickhouse_index_daily

        index_daily_sync_runner = sync_clickhouse_index_daily

    return {
        "stock_master_sync": lambda params: run_stock_master_sync(params, stock_master_runner),
        "minute5_intraday_sync": lambda params: run_minute5_intraday_sync(params, minute5_runner),
        "quote_snapshot_capture": lambda params: run_quote_snapshot_capture(params, quote_snapshot_runner),
        "quote_rollup_refresh": lambda params: run_quote_rollup_refresh(params, quote_rollup_runner),
        "quality_snapshot": lambda params: run_quality_snapshot(params, data_status_runner, quality_snapshot_writer),
        "post_close_maintenance": lambda params: run_post_close_maintenance(
            params,
            minute5_runner=minute5_runner,
            data_status_runner=data_status_runner,
            quality_snapshot_writer=quality_snapshot_writer,
            daily_repair_runner=daily_repair_runner,
            index_daily_sync_runner=index_daily_sync_runner,
        ),
    }


def run_stock_master_sync(params: dict[str, Any], runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    progress = params.get("progress")
    if callable(progress):
        progress(20, "fetching", "同步股票主数据")
    result = runner()
    if callable(progress):
        progress(100, "completed", "股票主数据同步完成")
    return result


def run_minute5_intraday_sync(params: dict[str, Any], runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    trade_date = _trade_date(params)
    progress = params.get("progress")
    return runner(
        trade_date=trade_date,
        limit=int(params.get("limit") or 0),
        symbols=params.get("symbols"),
        include_st=bool(params.get("include_st") or False),
        progress=progress if callable(progress) else None,
    )


def run_quote_snapshot_capture(params: dict[str, Any], runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    progress = params.get("progress")
    return runner(
        limit=int(params.get("limit") or 0),
        include_st=bool(params.get("include_st") or False),
        chunk_size=int(params.get("chunk_size") or 500),
        timeout_seconds=int(params.get("timeout_seconds") or 8),
        quote_endpoint=str(params.get("quote_endpoint") or "sqt_utf8"),
        progress=progress if callable(progress) else None,
    )


def run_quote_rollup_refresh(params: dict[str, Any], runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    return runner()


def run_quality_snapshot(
    params: dict[str, Any],
    data_status_runner: Callable[..., dict[str, Any]],
    quality_snapshot_writer: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    progress = params.get("progress")
    if callable(progress):
        progress(20, "checking", "读取数据质量状态")
    status = data_status_runner()
    if callable(progress):
        progress(70, "writing", "写入数据质量快照")
    return quality_snapshot_writer(quality=status.get("quality"))


def run_post_close_maintenance(
    params: dict[str, Any],
    *,
    minute5_runner: Callable[..., dict[str, Any]],
    data_status_runner: Callable[..., dict[str, Any]],
    quality_snapshot_writer: Callable[..., dict[str, Any]],
    daily_repair_runner: Callable[..., dict[str, Any]],
    index_daily_sync_runner: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    trade_date = _trade_date(params)
    progress = params.get("progress")
    if callable(progress):
        progress(10, "minute5", "同步 5m 分钟线")
    minute5 = minute5_runner(
        trade_date=trade_date,
        limit=int(params.get("limit") or 0),
        symbols=None,
        include_st=False,
        progress=progress if callable(progress) else None,
    )
    if callable(progress):
        progress(55, "checking", "检查数据质量")
    status = data_status_runner()
    if callable(progress):
        progress(70, "quality_snapshot", "写入质量快照")
    quality = quality_snapshot_writer(quality=status.get("quality"))
    if callable(progress):
        progress(82, "daily_repair", "修复日线")
    daily = daily_repair_runner(trade_date=trade_date)
    if callable(progress):
        progress(92, "index_daily", "同步指数日线")
    index_daily = index_daily_sync_runner(start=trade_date - timedelta(days=6), end=trade_date)
    return {
        "trade_date": trade_date.isoformat(),
        "minute5": minute5,
        "quality_snapshot": quality,
        "daily_repair": daily,
        "index_daily": index_daily,
    }


def _trade_date(params: dict[str, Any]) -> date:
    value = params.get("trade_date")
    if isinstance(value, date):
        return value
    if value:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    return date.today()
