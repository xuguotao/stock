"""Task handlers for the standalone data operations runner."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.mootdx_source import MootdxSource
from src.data_ops.mootdx_tasks import MOOTDX_TASK_BY_KEY
from src.trading.scheduler import TradingScheduler

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
    stock_readiness_snapshot_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    stock_readiness_repair_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    mootdx_sync_runner: Callable[..., dict[str, Any]] | None = None,
    stock_universe_profile_runner: Callable[..., dict[str, Any]] | None = None,
    research_adjustment_refresh_runner: Callable[..., dict[str, Any]] | None = None,
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
    if stock_readiness_snapshot_runner is None:
        from src.data.stock_data_readiness import run_readiness_snapshot

        stock_readiness_snapshot_runner = run_readiness_snapshot
    if stock_readiness_repair_runner is None:
        from src.data.stock_data_readiness import run_readiness_repair

        stock_readiness_repair_runner = run_readiness_repair
    if mootdx_sync_runner is None:
        from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data

        mootdx_sync_runner = sync_mootdx_offline_data
    if stock_universe_profile_runner is None:
        from src.data.stock_universe_profile import refresh_stock_universe_profiles

        stock_universe_profile_runner = lambda **kwargs: refresh_stock_universe_profiles(
            client=ClickHouseStockDataSource()._client_instance(), **kwargs
        )
    if research_adjustment_refresh_runner is None:
        from src.data.research_adjustment_refresh import refresh_research_adjustments
        research_adjustment_refresh_runner = lambda **_kwargs: refresh_research_adjustments(
            client=ClickHouseStockDataSource()._client_instance()
        )

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
        "stock_readiness_snapshot": stock_readiness_snapshot_runner,
        "stock_readiness_repair": stock_readiness_repair_runner,
        **{
            task_key: lambda params, definition=definition: run_mootdx_sync(
                params,
                mootdx_sync_runner,
                task=definition.sync_task,
                daily_reconcile=definition.daily_reconcile,
            )
            for task_key, definition in MOOTDX_TASK_BY_KEY.items()
            if task_key != "stock_universe_profile_refresh"
        },
        "stock_universe_profile_refresh": lambda params: run_stock_universe_profile_refresh(params, stock_universe_profile_runner),
        "research_adjustment_refresh": lambda _params: research_adjustment_refresh_runner(),
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


def run_mootdx_sync(
    params: dict[str, Any],
    runner: Callable[..., dict[str, Any]],
    *,
    task: str,
    daily_reconcile: bool = False,
) -> dict[str, Any]:
    progress = params.get("progress")
    trade_date = _trade_date(params)
    manual_reconcile = False
    if task == "stock_kline_daily" and params.get("manual_trigger") and not TradingScheduler().is_trading_day(trade_date):
        trade_date = _latest_trade_calendar_date() or _latest_daily_trade_date() or trade_date
        manual_reconcile = True
    result = runner(
        tasks=[task],
        source=_mootdx_source_from_params(params),
        trade_date=trade_date,
        limit=int(params.get("limit") or 0),
        include_beijing=bool(params.get("include_beijing") or False),
        daily_reconcile=daily_reconcile or manual_reconcile,
        progress=progress if callable(progress) else None,
    )
    audit = ((result.get("diagnostics") or {}).get(task) or {}).get("audit") or {}
    failed = result.get("failed") or {}
    if failed:
        raise RuntimeError(f"mootdx {task} failed: {failed.get(task) or failed}")
    if audit.get("status") == "failed":
        reasons = ", ".join(str(reason) for reason in audit.get("reasons") or [])
        raise RuntimeError(f"mootdx {task} audit failed: {reasons or 'unknown'}")
    return result


def _mootdx_source_from_params(params: dict[str, Any]) -> MootdxSource:
    """Build one reusable source for the full task run from task configuration."""
    server = _mootdx_server(params.get("server"))
    return MootdxSource(
        rate_limit=float(params.get("rate_limit") or 0.02),
        timeout=int(params.get("timeout") or 15),
        bestip=bool(params.get("bestip") or False),
        server=server,
        include_beijing=bool(params.get("include_beijing") or False),
    )


def _mootdx_server(value: Any) -> tuple[str, int] | None:
    if value is None or not str(value).strip():
        return None
    host, separator, port = str(value).strip().partition(":")
    if not separator or not host or not port.isdigit():
        raise ValueError("Mootdx 服务器必须为 host:port 格式")
    return host, int(port)


def run_stock_universe_profile_refresh(params: dict[str, Any], runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    from src.data.stock_universe_profile import StockUniverseProfileRules

    progress = params.get("progress")
    return runner(
        rules=StockUniverseProfileRules.from_mapping(params),
        rule_version=max(1, int(params.get("rule_version") or 1)),
        symbols=params.get("symbols"),
        progress=progress if callable(progress) else None,
    )


def _latest_daily_trade_date() -> date | None:
    try:
        rows = ClickHouseStockDataSource()._client_instance().execute(
            "select max(trade_date) from mootdx_stock_kline final where frequency = 'daily'"
        )
    except Exception:  # noqa: BLE001 - manual execution still records the normal source error if unavailable.
        return None
    value = rows[0][0] if rows and rows[0] else None
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _latest_trade_calendar_date() -> date | None:
    try:
        rows = ClickHouseStockDataSource()._client_instance().execute(
            "select max(date) from trade_calendar where is_open = 1 and date <= today()"
        )
    except Exception:  # noqa: BLE001
        return None
    value = rows[0][0] if rows and rows[0] else None
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


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
