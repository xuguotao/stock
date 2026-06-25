"""FastAPI application factory for the dashboard backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline
from src.data.clickhouse_quote_snapshot_sync import sync_clickhouse_quote_snapshots
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.clickhouse_table_maintenance import optimize_quote_snapshot_rollups
from src.data.clickhouse_daily_sync import sync_clickhouse_daily_from_minute5, sync_clickhouse_index_daily
from src.data.fund_tail_market_data import refresh_fund_tail_proxy_quotes
from src.data.clickhouse_research_dataset import build_clickhouse_research_dataset
from src.data.fund_tail_repository import ClickHouseFundTailRepository
from src.data.tail_signal_repository import ClickHouseTailSignalRepository
from src.core.constants import format_symbol
from src.ml.tail_dataset_audit import audit_tail_ml_data
from src.trading.scheduler import TradingScheduler
from src.web.backend.backtests import TailBacktestRequest, run_tail_backtest
from src.web.backend.data_sync import DEFAULT_REMOTE_STOCK_DB, sync_stock_database
from src.web.backend.data_ops_scheduler import DataOpsScheduler, DataOpsSchedulerConfig
from src.web.backend.data_status import (
    inspect_clickhouse_database,
    inspect_stock_database,
    persist_clickhouse_quality_snapshot,
)
from src.web.backend.data_health_repair import build_data_health_repair_plan
from src.web.backend.data_reliability import build_data_reliability_report
from src.web.backend.datasets import DatasetService
from src.web.backend.fund_tail import (
    FundTailAdviceRequest,
    FundTailDownloader,
    FundTailOpportunityRequest,
    FundTailOpportunityRefresher,
    FundTailPaths,
    FundTailProxyRefresher,
    PROXY_INDEXES,
    FundWatchlistItemRequest,
    delete_fund_watchlist_item,
    list_fund_universe_from_repository,
    list_fund_universe,
    list_fund_watchlist,
    load_latest_fund_tail_report,
    load_latest_fund_tail_opportunities,
    run_local_fund_tail_advice,
    run_local_fund_tail_opportunities,
    upsert_fund_watchlist_item,
)
from src.web.backend.jobs import JobStore
from src.web.backend.minute5_monitor import Minute5MonitorConfig, Minute5UpdateMonitor
from src.web.backend.quote_snapshot_monitor import QuoteSnapshotMonitor, QuoteSnapshotMonitorConfig
from src.web.backend.stock_trend import analyze_stock_trend
from src.web.backend.tail_live import TailLiveSelectionRequest, run_tail_live_selection
from src.web.backend.tail_replay_backtest import TailReplayBacktestRequest, run_tail_replay_backtest
from src.web.backend.watchlist_monitor import get_watchlist_config, get_watchlist_report


class CreateJobRequest(BaseModel):
    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class SyncStockDbRequest(BaseModel):
    remote: str = DEFAULT_REMOTE_STOCK_DB
    backup: bool = True


class SyncMinute5Request(BaseModel):
    trade_date: date
    limit: int = Field(default=0, ge=0)
    symbols: list[str] | None = None
    include_st: bool = False


class DailyMaintenanceRequest(BaseModel):
    trade_date: date | None = None
    retry_no_data: bool = True
    run_strategy_review: bool = True
    strategy_limit: int = Field(default=500, ge=1)
    strategy_top_n: int = Field(default=10, ge=1)
    strategy_universe: str = "default"
    bars_cache_dir: str = "data/cache/bars"
    output_dir: str = "reports/tail_session"


class DataHealthRepairRequest(BaseModel):
    action_keys: list[str] | None = None


class Minute5MonitorRequest(BaseModel):
    trade_date: date | None = None
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    limit: int = Field(default=0, ge=0)
    include_st: bool = False


class QuoteSnapshotMonitorRequest(BaseModel):
    interval_seconds: int = Field(default=10, ge=10, le=3600)
    limit: int = Field(default=0, ge=0)
    include_st: bool = False
    chunk_size: int = Field(default=850, ge=50, le=1000)
    timeout_seconds: int = Field(default=8, ge=3, le=60)


class BuildClickHouseDatasetRequest(BaseModel):
    start: date
    end: date
    name: str = Field(default="daily_clickhouse")
    symbols: list[str] | None = None
    limit: int = Field(default=0, ge=0)


class TailSignalOutcomeReviewRequest(BaseModel):
    signal_date: date | None = None
    start: date | None = None
    end: date | None = None
    mode: Literal["single_date", "pending"] = "single_date"


class FundTailProxyRefreshRequest(BaseModel):
    trade_date: date


def create_app(
    *,
    db_path: str | Path = "data/web/jobs.sqlite3",
    dataset_root: str | Path = "data/research",
    fund_tail_data_dir: str | Path = "data/fund_tail",
    fund_tail_report_path: str | Path = "reports/fund_tail_backtest.csv",
    fund_tail_raw_report_path: str | Path = "reports/fund_tail_backtest_raw.csv",
    fund_tail_advice_dir: str | Path = "reports/fund_tail_advice",
    fund_tail_markdown_path: str | Path = "reports/fund_tail_advice/latest.md",
    fund_tail_opportunity_candidate_path: str | Path = "config/fund_tail_candidates.csv",
    fund_tail_opportunity_data_dir: str | Path = "data/fund_tail_opportunities",
    fund_tail_opportunity_advice_report_path: str | Path = "reports/fund_tail_opportunity_backtest.csv",
    fund_tail_opportunity_raw_report_path: str | Path = "reports/fund_tail_opportunity_backtest_raw.csv",
    fund_tail_opportunity_report_path: str | Path = "reports/fund_tail_opportunities.csv",
    fund_tail_opportunity_markdown_path: str | Path = "reports/fund_tail_opportunities/latest.md",
    fund_tail_repository=None,
    stock_db_path: str | Path = "data/stock.db",
    run_jobs_inline: bool = False,
    tail_live_runner=run_tail_live_selection,
    tail_replay_runner=run_tail_replay_backtest,
    fund_tail_downloader: FundTailDownloader | None = None,
    fund_tail_proxy_refresher: FundTailProxyRefresher | None = None,
    fund_tail_opportunity_refresher: FundTailOpportunityRefresher | None = None,
    stock_db_sync_runner=sync_stock_database,
    minute5_sync_runner=sync_clickhouse_minute5_kline,
    minute5_monitor_session_checker=None,
    auto_start_minute5_monitor: bool = True,
    minute5_auto_interval_seconds: int = 60,
    quote_snapshot_sync_runner=sync_clickhouse_quote_snapshots,
    quote_snapshot_session_checker=None,
    auto_start_quote_snapshot_monitor: bool = True,
    quote_snapshot_interval_seconds: int = 10,
    data_status_runner=inspect_clickhouse_database,
    daily_repair_runner=sync_clickhouse_daily_from_minute5,
    index_daily_sync_runner=sync_clickhouse_index_daily,
    quality_snapshot_writer=persist_clickhouse_quality_snapshot,
    quote_rollup_optimizer=optimize_quote_snapshot_rollups,
    auto_start_data_ops_scheduler: bool = True,
    data_ops_interval_seconds: int = 60,
    data_ops_maintenance_runner=None,
    clickhouse_dataset_builder=build_clickhouse_research_dataset,
    tail_signal_repository=None,
    tail_ml_audit_runner=audit_tail_ml_data,
    stock_trend_runner=analyze_stock_trend,
    watchlist_monitor_runner=get_watchlist_report,
    watchlist_config_runner=get_watchlist_config,
) -> FastAPI:
    """Create a configured FastAPI app."""
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if application.state.auto_start_minute5_monitor:
            application.state.minute5_monitor.start(
                Minute5MonitorConfig(
                    trade_date=None,
                    interval_seconds=application.state.minute5_auto_interval_seconds,
                    limit=0,
                    include_st=False,
                ),
                mode="auto",
            )
        if application.state.auto_start_quote_snapshot_monitor:
            application.state.quote_snapshot_monitor.start(
                QuoteSnapshotMonitorConfig(
                    interval_seconds=application.state.quote_snapshot_interval_seconds,
                    limit=0,
                    include_st=False,
                    chunk_size=850,
                    timeout_seconds=8,
                ),
                mode="auto",
            )
        if application.state.auto_start_data_ops_scheduler:
            application.state.data_ops_scheduler.start()
        try:
            yield
        finally:
            application.state.data_ops_scheduler.stop()
            application.state.quote_snapshot_monitor.stop()
            application.state.minute5_monitor.stop()

    app = FastAPI(title="A-Share Quant Dashboard API", lifespan=lifespan)
    store = JobStore(db_path)
    store.mark_running_jobs_interrupted("服务重启，任务进程已中断")
    datasets = DatasetService(dataset_root)
    fund_tail_paths = FundTailPaths(
        data_dir=Path(fund_tail_data_dir),
        report_path=Path(fund_tail_report_path),
        raw_report_path=Path(fund_tail_raw_report_path),
        advice_dir=Path(fund_tail_advice_dir),
        markdown_path=Path(fund_tail_markdown_path),
        opportunity_candidate_path=Path(fund_tail_opportunity_candidate_path),
        opportunity_data_dir=Path(fund_tail_opportunity_data_dir),
        opportunity_advice_report_path=Path(fund_tail_opportunity_advice_report_path),
        opportunity_raw_report_path=Path(fund_tail_opportunity_raw_report_path),
        opportunity_report_path=Path(fund_tail_opportunity_report_path),
        opportunity_markdown_path=Path(fund_tail_opportunity_markdown_path),
    )
    app.state.job_store = store
    app.state.dataset_service = datasets
    app.state.fund_tail_paths = fund_tail_paths
    app.state.stock_db_path = Path(stock_db_path)
    app.state.run_jobs_inline = run_jobs_inline
    app.state.tail_live_runner = tail_live_runner
    app.state.tail_replay_runner = tail_replay_runner
    app.state.fund_tail_downloader = fund_tail_downloader
    app.state.fund_tail_proxy_refresher = (
        fund_tail_proxy_refresher
        if fund_tail_proxy_refresher is not None
        else _default_fund_tail_proxy_refresher if fund_tail_downloader is None else None
    )
    app.state.fund_tail_opportunity_refresher = fund_tail_opportunity_refresher
    app.state.fund_tail_repository = (
        fund_tail_repository
        if fund_tail_repository is not None
        else _default_fund_tail_repository(fund_tail_data_dir)
    )
    app.state.stock_db_sync_runner = stock_db_sync_runner
    app.state.minute5_sync_runner = minute5_sync_runner
    app.state.quote_snapshot_sync_runner = quote_snapshot_sync_runner
    app.state.data_status_runner = data_status_runner
    app.state.daily_repair_runner = daily_repair_runner
    app.state.index_daily_sync_runner = index_daily_sync_runner
    app.state.quality_snapshot_writer = quality_snapshot_writer
    app.state.quote_rollup_optimizer = quote_rollup_optimizer
    app.state.clickhouse_dataset_builder = clickhouse_dataset_builder
    app.state.tail_signal_repository = tail_signal_repository or ClickHouseTailSignalRepository()
    app.state.tail_ml_audit_runner = tail_ml_audit_runner
    app.state.stock_trend_runner = stock_trend_runner
    app.state.watchlist_monitor_runner = watchlist_monitor_runner
    app.state.watchlist_config_runner = watchlist_config_runner
    app.state.minute5_monitor = Minute5UpdateMonitor(
        runner=app.state.minute5_sync_runner,
        stock_db_path=app.state.stock_db_path,
        session_checker=minute5_monitor_session_checker,
    )
    app.state.auto_start_minute5_monitor = auto_start_minute5_monitor
    app.state.minute5_auto_interval_seconds = minute5_auto_interval_seconds
    app.state.quote_snapshot_monitor = QuoteSnapshotMonitor(
        runner=app.state.quote_snapshot_sync_runner,
        session_checker=quote_snapshot_session_checker,
    )
    app.state.auto_start_quote_snapshot_monitor = auto_start_quote_snapshot_monitor
    app.state.quote_snapshot_interval_seconds = quote_snapshot_interval_seconds
    app.state.auto_start_data_ops_scheduler = auto_start_data_ops_scheduler

    def _auto_data_maintenance() -> dict[str, Any]:
        payload = DailyMaintenanceRequest(run_strategy_review=False)
        job = store.create_job("daily_maintenance", {"auto": True, **payload.model_dump(mode="json")})
        _run_daily_maintenance_job(
            store,
            app.state.minute5_sync_runner,
            app.state.data_status_runner,
            app.state.tail_live_runner,
            app.state.tail_signal_repository,
            app.state.stock_db_path,
            job.id,
            payload,
            daily_repair_runner=app.state.daily_repair_runner,
            index_daily_sync_runner=app.state.index_daily_sync_runner,
            quality_snapshot_writer=app.state.quality_snapshot_writer,
        )
        completed = store.get_job(job.id)
        return completed.to_dict() if completed is not None else {"job_id": job.id, "status": "missing"}

    app.state.data_ops_scheduler = DataOpsScheduler(
        maintenance_runner=data_ops_maintenance_runner or _auto_data_maintenance,
        config=DataOpsSchedulerConfig(interval_seconds=data_ops_interval_seconds),
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/jobs")
    def create_job(payload: CreateJobRequest) -> dict[str, Any]:
        return store.create_job(payload.kind, payload.params).to_dict()

    @app.get("/api/jobs")
    def list_jobs(limit: int = 50) -> dict[str, Any]:
        return {"items": [job.to_dict() for job in store.list_jobs(limit=limit)]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job.to_dict()

    @app.get("/api/datasets")
    def list_datasets() -> dict[str, Any]:
        return {"items": [dataset.to_dict() for dataset in datasets.list_datasets()]}

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        dataset = datasets.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return dataset

    @app.post("/api/datasets/build-clickhouse")
    def create_clickhouse_dataset_build(
        payload: BuildClickHouseDatasetRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("dataset_build", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_clickhouse_dataset_build_job(
                store,
                app.state.clickhouse_dataset_builder,
                datasets.dataset_root,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_clickhouse_dataset_build_job,
                store,
                app.state.clickhouse_dataset_builder,
                datasets.dataset_root,
                job.id,
                payload,
            )

        return {"job_id": job.id}

    @app.get("/api/data/status")
    def get_data_status() -> dict[str, Any]:
        return app.state.data_status_runner()

    @app.get("/api/data/health-repair-plan")
    def get_data_health_repair_plan() -> dict[str, Any]:
        return build_data_health_repair_plan(app.state.data_status_runner())

    @app.get("/api/data/reliability")
    def get_data_reliability() -> dict[str, Any]:
        status = app.state.data_status_runner()
        repair_plan = build_data_health_repair_plan(status)
        report = build_data_reliability_report(
            status=status,
            minute5_monitor=app.state.minute5_monitor.status(),
            quote_monitor=app.state.quote_snapshot_monitor.status(),
            scheduler=app.state.data_ops_scheduler.status(),
            repair_plan=repair_plan,
        )
        return {**report, "data_status": status, "repair_plan": repair_plan}

    @app.post("/api/data/health-repair")
    def create_data_health_repair(
        payload: DataHealthRepairRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("data_health_repair", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_data_health_repair_job(
                store,
                app.state.minute5_sync_runner,
                app.state.quote_snapshot_sync_runner,
                app.state.data_status_runner,
                app.state.stock_db_path,
                job.id,
                payload,
                daily_repair_runner=app.state.daily_repair_runner,
                quality_snapshot_writer=app.state.quality_snapshot_writer,
                quote_rollup_optimizer=app.state.quote_rollup_optimizer,
            )
        else:
            background_tasks.add_task(
                _run_data_health_repair_job,
                store,
                app.state.minute5_sync_runner,
                app.state.quote_snapshot_sync_runner,
                app.state.data_status_runner,
                app.state.stock_db_path,
                job.id,
                payload,
                daily_repair_runner=app.state.daily_repair_runner,
                quality_snapshot_writer=app.state.quality_snapshot_writer,
                quote_rollup_optimizer=app.state.quote_rollup_optimizer,
            )

        return {"job_id": job.id}

    @app.get("/api/stocks/{symbol}/trend")
    def get_stock_trend(
        symbol: str,
        trade_date: date | None = None,
        daily_window: int = 90,
        granularity: str = "5m",
    ) -> dict[str, Any]:
        return app.state.stock_trend_runner(
            symbol,
            trade_date=trade_date,
            daily_window=daily_window,
            granularity=granularity,
        )

    @app.get("/api/watchlist-monitor/report")
    def get_watchlist_monitor_report(trade_date: date | None = None) -> dict[str, Any]:
        return app.state.watchlist_monitor_runner(trade_date=trade_date)

    @app.get("/api/watchlist-monitor/config")
    def get_watchlist_monitor_config() -> dict[str, Any]:
        return app.state.watchlist_config_runner()

    @app.post("/api/data/sync-stock-db")
    def create_stock_db_sync(
        payload: SyncStockDbRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("stock_db_sync", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_stock_db_sync_job(store, app.state.stock_db_sync_runner, app.state.stock_db_path, job.id, payload)
        else:
            background_tasks.add_task(
                _run_stock_db_sync_job,
                store,
                app.state.stock_db_sync_runner,
                app.state.stock_db_path,
                job.id,
                payload,
            )

        return {"job_id": job.id}

    @app.post("/api/data/sync-minute5")
    def create_minute5_sync(
        payload: SyncMinute5Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("minute5_sync", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_minute5_sync_job(
                store,
                app.state.minute5_sync_runner,
                app.state.stock_db_path,
                app.state.data_status_runner,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_minute5_sync_job,
                store,
                app.state.minute5_sync_runner,
                app.state.stock_db_path,
                app.state.data_status_runner,
                job.id,
                payload,
            )

        return {"job_id": job.id}

    @app.get("/api/data/minute5-monitor")
    def get_minute5_monitor_status() -> dict[str, Any]:
        return app.state.minute5_monitor.status()

    @app.post("/api/data/minute5-monitor/start")
    def start_minute5_monitor(payload: Minute5MonitorRequest) -> dict[str, Any]:
        config = Minute5MonitorConfig(
            trade_date=payload.trade_date,
            interval_seconds=payload.interval_seconds,
            limit=payload.limit,
            include_st=payload.include_st,
        )
        return app.state.minute5_monitor.start(
            config,
            run_first_cycle_inline=app.state.run_jobs_inline,
        )

    @app.post("/api/data/minute5-monitor/stop")
    def stop_minute5_monitor() -> dict[str, Any]:
        return app.state.minute5_monitor.stop()

    @app.get("/api/data/quote-snapshot-monitor")
    def get_quote_snapshot_monitor_status() -> dict[str, Any]:
        return app.state.quote_snapshot_monitor.status()

    @app.post("/api/data/quote-snapshot-monitor/start")
    def start_quote_snapshot_monitor(payload: QuoteSnapshotMonitorRequest) -> dict[str, Any]:
        config = QuoteSnapshotMonitorConfig(
            interval_seconds=payload.interval_seconds,
            limit=payload.limit,
            include_st=payload.include_st,
            chunk_size=payload.chunk_size,
            timeout_seconds=payload.timeout_seconds,
        )
        return app.state.quote_snapshot_monitor.start(
            config,
            run_first_cycle_inline=app.state.run_jobs_inline,
        )

    @app.post("/api/data/quote-snapshot-monitor/stop")
    def stop_quote_snapshot_monitor() -> dict[str, Any]:
        return app.state.quote_snapshot_monitor.stop()

    @app.get("/api/data/ops-scheduler")
    def get_data_ops_scheduler_status() -> dict[str, Any]:
        return app.state.data_ops_scheduler.status()

    @app.post("/api/data/ops-scheduler/start")
    def start_data_ops_scheduler() -> dict[str, Any]:
        return app.state.data_ops_scheduler.start()

    @app.post("/api/data/ops-scheduler/stop")
    def stop_data_ops_scheduler() -> dict[str, Any]:
        return app.state.data_ops_scheduler.stop()

    @app.post("/api/data/ops-scheduler/run-once")
    def run_data_ops_scheduler_once() -> dict[str, Any]:
        return app.state.data_ops_scheduler.run_once(force=True)

    @app.post("/api/data/daily-maintenance")
    def create_daily_maintenance(
        payload: DailyMaintenanceRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("daily_maintenance", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_daily_maintenance_job(
                store,
                app.state.minute5_sync_runner,
                app.state.data_status_runner,
                app.state.tail_live_runner,
                app.state.tail_signal_repository,
                app.state.stock_db_path,
                job.id,
                payload,
                daily_repair_runner=app.state.daily_repair_runner,
                index_daily_sync_runner=app.state.index_daily_sync_runner,
                quality_snapshot_writer=app.state.quality_snapshot_writer,
            )
        else:
            background_tasks.add_task(
                _run_daily_maintenance_job,
                store,
                app.state.minute5_sync_runner,
                app.state.data_status_runner,
                app.state.tail_live_runner,
                app.state.tail_signal_repository,
                app.state.stock_db_path,
                job.id,
                payload,
                daily_repair_runner=app.state.daily_repair_runner,
                index_daily_sync_runner=app.state.index_daily_sync_runner,
                quality_snapshot_writer=app.state.quality_snapshot_writer,
            )

        return {"job_id": job.id}

    @app.get("/api/fund-tail/universe")
    def get_fund_tail_universe() -> dict[str, Any]:
        if app.state.fund_tail_repository is not None:
            return {"items": list_fund_universe_from_repository(app.state.fund_tail_repository)}
        return {"items": list_fund_universe(fund_tail_paths.data_dir)}

    @app.get("/api/fund-tail/report")
    def get_fund_tail_report() -> dict[str, Any]:
        return load_latest_fund_tail_report(
            fund_tail_paths.report_path,
            fund_tail_paths.markdown_path,
            app.state.fund_tail_repository,
        )

    @app.get("/api/fund-tail/opportunities/latest")
    def get_fund_tail_opportunities() -> dict[str, Any]:
        return load_latest_fund_tail_opportunities(
            fund_tail_paths.opportunity_report_path,
            fund_tail_paths.opportunity_markdown_path,
        )

    @app.get("/api/fund-tail/watchlist")
    def get_fund_tail_watchlist() -> dict[str, Any]:
        if app.state.fund_tail_repository is None:
            raise HTTPException(status_code=503, detail="Fund watchlist requires ClickHouse repository")
        return {"items": list_fund_watchlist(app.state.fund_tail_repository)}

    @app.post("/api/fund-tail/refresh-proxy")
    def refresh_fund_tail_proxy(payload: FundTailProxyRefreshRequest) -> dict[str, Any]:
        if app.state.fund_tail_repository is None:
            raise HTTPException(status_code=503, detail="Fund proxy refresh requires ClickHouse repository")
        if app.state.fund_tail_proxy_refresher is None:
            raise HTTPException(status_code=503, detail="Fund proxy refresher is not configured")
        fund_codes = app.state.fund_tail_repository.advice_fund_codes_from_watchlist()
        proxy_refresh = app.state.fund_tail_proxy_refresher(
            repository=app.state.fund_tail_repository,
            fund_codes=fund_codes,
            trade_date=payload.trade_date,
        )
        return {
            "proxy_refresh": proxy_refresh,
            "items": list_fund_watchlist(app.state.fund_tail_repository),
            "universe": list_fund_universe_from_repository(app.state.fund_tail_repository),
        }

    @app.post("/api/fund-tail/watchlist")
    def create_fund_tail_watchlist_item(payload: FundWatchlistItemRequest) -> dict[str, Any]:
        if app.state.fund_tail_repository is None:
            raise HTTPException(status_code=503, detail="Fund watchlist requires ClickHouse repository")
        return {"item": upsert_fund_watchlist_item(app.state.fund_tail_repository, payload)}

    @app.put("/api/fund-tail/watchlist/{fund_code}")
    def update_fund_tail_watchlist_item(fund_code: str, payload: FundWatchlistItemRequest) -> dict[str, Any]:
        if app.state.fund_tail_repository is None:
            raise HTTPException(status_code=503, detail="Fund watchlist requires ClickHouse repository")
        payload = FundWatchlistItemRequest(**{**payload.model_dump(), "fund_code": fund_code})
        return {"item": upsert_fund_watchlist_item(app.state.fund_tail_repository, payload)}

    @app.delete("/api/fund-tail/watchlist/{fund_code}")
    def delete_fund_tail_watchlist_item_api(fund_code: str) -> dict[str, int]:
        if app.state.fund_tail_repository is None:
            raise HTTPException(status_code=503, detail="Fund watchlist requires ClickHouse repository")
        return delete_fund_watchlist_item(app.state.fund_tail_repository, fund_code)

    @app.post("/api/fund-tail/advice")
    def create_fund_tail_advice(
        payload: FundTailAdviceRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("fund_tail_advice", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_fund_tail_advice_job(
                store,
                fund_tail_paths,
                job.id,
                payload,
                app.state.fund_tail_downloader,
                app.state.fund_tail_repository,
                app.state.fund_tail_proxy_refresher,
            )
        else:
            background_tasks.add_task(
                _run_fund_tail_advice_job,
                store,
                fund_tail_paths,
                job.id,
                payload,
                app.state.fund_tail_downloader,
                app.state.fund_tail_repository,
                app.state.fund_tail_proxy_refresher,
            )

        return {"job_id": job.id}

    @app.post("/api/fund-tail/opportunities")
    def create_fund_tail_opportunities(
        payload: FundTailOpportunityRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("fund_tail_opportunities", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_fund_tail_opportunities_job(
                store,
                fund_tail_paths,
                job.id,
                payload,
                app.state.fund_tail_repository,
                app.state.fund_tail_opportunity_refresher,
            )
        else:
            background_tasks.add_task(
                _run_fund_tail_opportunities_job,
                store,
                fund_tail_paths,
                job.id,
                payload,
                app.state.fund_tail_repository,
                app.state.fund_tail_opportunity_refresher,
            )

        return {"job_id": job.id}

    @app.post("/api/backtests/tail-session")
    def create_tail_backtest(
        payload: TailBacktestRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        if not payload.sample and payload.dataset_id:
            dataset_path = datasets.resolve_dataset_path(payload.dataset_id)
            if dataset_path is None:
                raise HTTPException(status_code=404, detail="Dataset not found")
            payload = payload.model_copy(update={"dataset_path": str(dataset_path)})

        job = store.create_job("tail_session_backtest", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_tail_backtest_job(store, job.id, payload)
        else:
            background_tasks.add_task(_run_tail_backtest_job, store, job.id, payload)

        return {"job_id": job.id}

    @app.post("/api/tail-session/live-selection")
    def create_tail_live_selection(
        payload: TailLiveSelectionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("tail_session_live_selection", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_tail_live_selection_job(
                store,
                app.state.tail_live_runner,
                app.state.minute5_sync_runner,
                app.state.quote_snapshot_sync_runner,
                app.state.stock_db_path,
                app.state.tail_signal_repository,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_tail_live_selection_job,
                store,
                app.state.tail_live_runner,
                app.state.minute5_sync_runner,
                app.state.quote_snapshot_sync_runner,
                app.state.stock_db_path,
                app.state.tail_signal_repository,
                job.id,
                payload,
            )

        return {"job_id": job.id}

    @app.post("/api/tail-session/replay-backtest")
    def create_tail_replay_backtest(
        payload: TailReplayBacktestRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("tail_session_replay_backtest", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_tail_replay_backtest_job(store, app.state.tail_replay_runner, job.id, payload)
        else:
            background_tasks.add_task(_run_tail_replay_backtest_job, store, app.state.tail_replay_runner, job.id, payload)

        return {"job_id": job.id}

    @app.get("/api/tail-session/signal-stats")
    def get_tail_signal_stats(start: date | None = None, end: date | None = None) -> dict[str, Any]:
        return app.state.tail_signal_repository.signal_stats(start=start, end=end)

    @app.get("/api/ml/tail/audit")
    def get_tail_ml_audit() -> dict[str, Any]:
        return app.state.tail_ml_audit_runner()

    @app.post("/api/tail-session/review-outcomes")
    def review_tail_signal_outcomes(payload: TailSignalOutcomeReviewRequest) -> dict[str, Any]:
        if payload.mode == "pending":
            return app.state.tail_signal_repository.compute_pending_selected_outcomes(start=payload.start, end=payload.end)
        if payload.signal_date is None:
            raise HTTPException(status_code=400, detail="signal_date is required for single-date review")
        return app.state.tail_signal_repository.compute_selected_outcomes(signal_date=payload.signal_date)

    return app


def _default_fund_tail_repository(fund_tail_data_dir: str | Path):
    return ClickHouseFundTailRepository() if Path(fund_tail_data_dir) == Path("data/fund_tail") else None


def _default_fund_tail_proxy_refresher(**kwargs) -> dict[str, Any]:
    return refresh_fund_tail_proxy_quotes(proxy_specs=PROXY_INDEXES, **kwargs)


app = create_app()


def _run_tail_backtest_job(store: JobStore, job_id: str, payload: TailBacktestRequest) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "任务启动"))
    try:
        result = run_tail_backtest(
            payload,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        )
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "任务失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "回测完成"))


def _run_tail_replay_backtest_job(store: JobStore, runner, job_id: str, payload: TailReplayBacktestRequest) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "尾盘时段回放回测启动"))
    try:
        result = runner(
            payload,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        )
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "任务失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "尾盘时段回放回测完成"))


def _run_fund_tail_advice_job(
    store: JobStore,
    paths: FundTailPaths,
    job_id: str,
    payload: FundTailAdviceRequest,
    downloader: FundTailDownloader | None,
    repository,
    proxy_refresher: FundTailProxyRefresher | None,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(10, "starting", "生成基金尾盘建议"))
    try:
        kwargs: dict[str, Any] = {
            "progress": lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            )
        }
        if downloader is not None:
            kwargs["downloader"] = downloader
        if proxy_refresher is not None:
            kwargs["proxy_refresher"] = proxy_refresher
        if repository is not None:
            kwargs["repository"] = repository
        result = run_local_fund_tail_advice(paths, payload, **kwargs)
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "任务失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "建议生成完成"))


def _run_fund_tail_opportunities_job(
    store: JobStore,
    paths: FundTailPaths,
    job_id: str,
    payload: FundTailOpportunityRequest,
    repository,
    opportunity_refresher,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(10, "starting", "发现基金尾盘机会"))
    try:
        result = run_local_fund_tail_opportunities(
            paths,
            payload,
            repository=repository,
            opportunity_refresher=opportunity_refresher,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        )
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "任务失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "机会发现完成"))


def _run_tail_live_selection_job(
    store: JobStore,
    runner,
    minute5_runner,
    quote_snapshot_runner,
    stock_db_path: Path,
    signal_repository,
    job_id: str,
    payload: TailLiveSelectionRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "今日尾盘选股启动"))
    try:
        job_started = perf_counter()
        stage_timings: dict[str, float] = {}
        data_refresh = None
        data_refresh_kind = None
        refresh_mode = _effective_tail_data_refresh_mode(payload)
        if refresh_mode == "snapshot":
            data_refresh_kind = "quote_snapshot_sync"
            stage_started = perf_counter()
            freshness = (
                _fresh_quote_snapshot_available(
                    trade_date=payload.trade_date,
                    symbols=payload.symbols,
                    limit=payload.limit,
                )
                if payload.data_refresh_mode == "auto"
                else {"fresh": False, "reason": "forced_snapshot_refresh"}
            )
            if freshness.get("fresh"):
                data_refresh = {
                    "skipped": True,
                    "skip_reason": "fresh_quote_snapshot",
                    "message": "已有足够新鲜的行情快照，跳过重复刷新",
                    **freshness,
                }
                store.update_job(
                    job_id,
                    status="running",
                    progress=_progress(35, "quote_snapshot_fresh", "行情快照足够新鲜，跳过重复刷新"),
                )
            else:
                store.update_job(job_id, status="running", progress=_progress(10, "quote_snapshot_sync", "快速刷新行情快照和5m聚合"))
                data_refresh = quote_snapshot_runner(
                    limit=0,
                    include_st=False,
                    progress=lambda percent, stage, message: store.update_job(
                        job_id,
                        status="running",
                        progress=_progress(10 + int(percent * 0.25), stage, message),
                    ),
                )
            stage_timings["quote_snapshot_sync"] = _elapsed(stage_started)
        elif refresh_mode == "standard_minute5":
            store.update_job(job_id, status="running", progress=_progress(10, "minute5_sync", "先补齐当前 5m 分钟线"))
            stage_started = perf_counter()
            data_refresh = minute5_runner(
                db_path=stock_db_path,
                trade_date=payload.trade_date,
                limit=payload.limit,
                symbols=payload.symbols,
                include_st=False,
                progress=lambda percent, stage, message: store.update_job(
                    job_id,
                    status="running",
                    progress=_progress(10 + int(percent * 0.35), stage, message),
                ),
            )
            data_refresh_kind = "minute5_sync"
            stage_timings["minute5_sync"] = _elapsed(stage_started)
        stage_started = perf_counter()
        result = runner(
            payload,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(45 + int(percent * 0.5), stage, message),
            ),
        )
        stage_timings["strategy_scan"] = _elapsed(stage_started)
        if data_refresh is not None:
            result["data_refresh"] = data_refresh
            diagnostics = result.setdefault("diagnostics", {})
            diagnostics["data_refresh_mode"] = payload.data_refresh_mode
            diagnostics["effective_data_refresh_mode"] = refresh_mode
            if data_refresh_kind == "minute5_sync":
                diagnostics["minute5_sync"] = _minute5_sync_diagnostic(data_refresh)
            elif data_refresh_kind == "quote_snapshot_sync":
                diagnostics["quote_snapshot_sync"] = _quote_snapshot_sync_diagnostic(data_refresh)
        else:
            diagnostics = result.setdefault("diagnostics", {})
            diagnostics["data_refresh_mode"] = payload.data_refresh_mode
            diagnostics["effective_data_refresh_mode"] = refresh_mode
        result["stage_timings"] = {**stage_timings, **(result.get("stage_timings") or {})}
        stage_started = perf_counter()
        result["persistence"] = _persist_tail_signal_result(signal_repository, job_id, result)
        result["stage_timings"]["persistence"] = _elapsed(stage_started)
        result["stage_timings"]["total"] = _elapsed(job_started)
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "任务失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "今日尾盘选股完成"))


def _effective_tail_data_refresh_mode(payload: TailLiveSelectionRequest) -> str:
    if payload.data_refresh_mode == "standard_minute5":
        return "standard_minute5"
    if payload.data_refresh_mode == "snapshot":
        return "snapshot"
    if payload.data_refresh_mode == "none":
        return "none"
    return "snapshot" if payload.auto_sync_minute5 else "none"


def _fresh_quote_snapshot_available(
    *,
    trade_date: date,
    symbols: list[str] | None,
    limit: int,
    max_age_seconds: int = 45,
    min_all_market_symbols: int = 4500,
) -> dict[str, Any]:
    if trade_date != date.today():
        return {"fresh": False, "reason": "not_today"}
    expected_symbols = len(symbols or [])
    if expected_symbols == 0:
        expected_symbols = limit if limit > 0 else min_all_market_symbols
    if expected_symbols <= 0:
        return {"fresh": False, "reason": "empty_expected_symbols"}
    try:
        client = ClickHouseStockDataSource()._client_instance()
        normalized_symbols = tuple(format_symbol(symbol) for symbol in symbols or [])
        latest = _latest_quote_snapshot_at(client, trade_date=trade_date, symbols=normalized_symbols)
        if latest is None:
            return {"fresh": False, "reason": "missing_snapshot"}
        covered = _quote_snapshot_batch_coverage(client, snapshot_at=latest, symbols=normalized_symbols)
    except Exception as exc:  # noqa: BLE001 - stale check should not block a manual refresh fallback.
        return {"fresh": False, "reason": "freshness_check_failed", "error": str(exc)}

    age_seconds = max(0.0, (datetime.now() - latest).total_seconds())
    required = max(1, int(expected_symbols * 0.95))
    fresh = covered >= required and age_seconds <= max_age_seconds
    reason = "fresh" if fresh else "stale_or_incomplete_snapshot"
    return {
        "fresh": fresh,
        "reason": reason,
        "latest_snapshot_at": latest.isoformat(sep=" ", timespec="seconds"),
        "covered_symbols": covered,
        "expected_symbols": expected_symbols,
        "required_symbols": required,
        "age_seconds": round(age_seconds, 3),
        "max_age_seconds": max_age_seconds,
    }


def _latest_quote_snapshot_at(client: Any, *, trade_date: date, symbols: tuple[str, ...]) -> datetime | None:
    symbol_filter = "and symbol in %(symbols)s" if symbols else ""
    params: dict[str, Any] = {"trade_date": trade_date}
    if symbols:
        params["symbols"] = symbols
    rows = client.execute(
        f"""
        select max(snapshot_at)
        from stock_quote_snapshots
        where toDate(snapshot_at) = %(trade_date)s
        {symbol_filter}
        """,
        params,
    )
    if not rows or rows[0][0] is None:
        return None
    return rows[0][0] if isinstance(rows[0][0], datetime) else datetime.fromisoformat(str(rows[0][0]))


def _quote_snapshot_batch_coverage(client: Any, *, snapshot_at: datetime, symbols: tuple[str, ...]) -> int:
    symbol_filter = "and symbol in %(symbols)s" if symbols else ""
    params: dict[str, Any] = {"snapshot_at": snapshot_at}
    if symbols:
        params["symbols"] = symbols
    rows = client.execute(
        f"""
        select countDistinct(symbol)
        from stock_quote_snapshots
        where snapshot_at = %(snapshot_at)s
        {symbol_filter}
        """,
        params,
    )
    return int(rows[0][0] or 0) if rows else 0


def _minute5_sync_diagnostic(sync_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": sync_result.get("trade_date"),
        "target_symbols": sync_result.get("target_symbols", 0),
        "skipped": sync_result.get("skipped", 0),
        "success": sync_result.get("success", 0),
        "no_data": sync_result.get("no_data", 0),
        "failed": sync_result.get("failed", 0),
        "inserted_rows": sync_result.get("inserted_rows", 0),
        "latest_datetime": ((sync_result.get("coverage_after") or {}).get("date_range") or {}).get("end"),
    }


def _quote_snapshot_sync_diagnostic(sync_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "skipped": bool(sync_result.get("skipped", False)),
        "skip_reason": sync_result.get("skip_reason"),
        "target_symbols": sync_result.get("target_symbols", sync_result.get("requested_symbols", 0)),
        "covered_symbols": sync_result.get("covered_symbols"),
        "expected_symbols": sync_result.get("expected_symbols"),
        "age_seconds": sync_result.get("age_seconds"),
        "inserted_rows": sync_result.get("inserted_rows", sync_result.get("inserted", 0)),
        "failed": sync_result.get("failed", 0),
        "latest_snapshot_at": sync_result.get("latest_snapshot_at"),
        "latest_bucket": sync_result.get("latest_bucket"),
    }


def _persist_tail_signal_result(signal_repository, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    signals = signal_repository.save_selection_result(job_id=job_id, result=result)
    symbols = [
        str(row.get("symbol"))
        for row in result.get("selections", []) or []
        if row.get("symbol")
    ]
    outcomes = signal_repository.compute_and_save_outcomes(
        signal_date=date.fromisoformat(str(result["trade_date"])),
        symbols=symbols,
    )
    return {"signals": signals, "outcomes": outcomes}


def _run_stock_db_sync_job(
    store: JobStore,
    runner,
    stock_db_path: Path,
    job_id: str,
    payload: SyncStockDbRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "旧 Stock DB 同步启动"))
    try:
        sync_result = runner(
            payload.remote,
            stock_db_path,
            payload.backup,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        )
        result = {
            "legacy": True,
            "sync": sync_result,
            "status": inspect_stock_database(stock_db_path),
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "旧 Stock DB 同步失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "旧 Stock DB 同步完成"))


def _run_minute5_sync_job(
    store: JobStore,
    runner,
    stock_db_path: Path,
    data_status_runner,
    job_id: str,
    payload: SyncMinute5Request,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "5m 分钟线更新启动"))
    try:
        sync_result = runner(
            db_path=stock_db_path,
            trade_date=payload.trade_date,
            limit=payload.limit,
            symbols=payload.symbols,
            include_st=payload.include_st,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        )
        result = {
            "sync": sync_result,
            "status": data_status_runner(),
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "5m 分钟线更新失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "5m 分钟线更新完成"))


def _run_data_health_repair_job(
    store: JobStore,
    minute5_runner,
    quote_snapshot_runner,
    data_status_runner,
    stock_db_path: Path,
    job_id: str,
    payload: DataHealthRepairRequest,
    *,
    daily_repair_runner=None,
    quality_snapshot_writer=None,
    quote_rollup_optimizer=None,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "planning", "生成数据健康修复计划"))
    try:
        before_status = data_status_runner()
        plan = build_data_health_repair_plan(before_status)
        requested = set(payload.action_keys or [])
        repairs = []
        skipped = []
        auto_actions = [
            action for action in plan["actions"]
            if action.get("auto_repair")
            and action.get("key") != "quality_snapshot"
            and (not requested or action["key"] in requested)
        ]
        wants_quality_snapshot = quality_snapshot_writer is not None and bool(auto_actions)
        total = max(1, len(auto_actions))

        for index, action in enumerate(auto_actions, start=1):
            key = str(action["key"])
            base_percent = 10 + int((index - 1) / total * 75)
            store.update_job(job_id, status="running", progress=_progress(base_percent, key, str(action["title"])))
            if key == "minute5_sync":
                trade_date = _parse_optional_date(action.get("trade_date"))
                if trade_date is None:
                    skipped.append({"key": key, "reason": "缺少可修复的 5m 交易日"})
                    continue
                result = minute5_runner(
                    db_path=stock_db_path,
                    trade_date=trade_date,
                    limit=0,
                    symbols=action.get("symbols") or None,
                    include_st=False,
                    progress=lambda percent, stage, message: store.update_job(
                        job_id,
                        status="running",
                        progress=_progress(min(84, base_percent + int(percent * 0.2)), stage, message),
                    ),
                )
                repairs.append({"key": key, "result": result})
            elif key == "daily_from_minute5":
                trade_date = _parse_optional_date(action.get("trade_date"))
                if trade_date is None or daily_repair_runner is None:
                    skipped.append({"key": key, "reason": "缺少日线修复器或交易日"})
                    continue
                repairs.append({"key": key, "result": daily_repair_runner(trade_date=trade_date)})
            elif key == "quote_snapshot_sync":
                result = quote_snapshot_runner(
                    symbols=None,
                    limit=0,
                    include_st=False,
                    progress=lambda percent, stage, message: store.update_job(
                        job_id,
                        status="running",
                        progress=_progress(min(88, base_percent + int(percent * 0.2)), stage, message),
                    ),
                )
                repairs.append({"key": key, "result": result})
            elif key == "quote_rollup_optimize":
                if quote_rollup_optimizer is None:
                    skipped.append({"key": key, "reason": "缺少快照聚合去重修复器"})
                    continue
                repairs.append({"key": key, "result": quote_rollup_optimizer()})
            else:
                skipped.append({"key": key, "reason": "未知自动修复动作"})

        after_status = data_status_runner()
        if wants_quality_snapshot:
            store.update_job(job_id, status="running", progress=_progress(90, "quality_snapshot", "写入修复后的质量快照"))
            if quality_snapshot_writer is None:
                skipped.append({"key": "quality_snapshot", "reason": "缺少质量快照写入器"})
            else:
                repairs.append({"key": "quality_snapshot", "result": quality_snapshot_writer(quality=after_status.get("quality"))})
        result = {
            "before": before_status,
            "before_plan": plan,
            "after": after_status,
            "after_plan": build_data_health_repair_plan(after_status),
            "repairs": repairs,
            "skipped": skipped,
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "数据健康修复失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "数据健康修复完成"))


def _run_daily_maintenance_job(
    store: JobStore,
    minute5_runner,
    data_status_runner,
    tail_live_runner,
    signal_repository,
    stock_db_path: Path,
    job_id: str,
    payload: DailyMaintenanceRequest,
    *,
    daily_repair_runner=None,
    index_daily_sync_runner=None,
    quality_snapshot_writer=None,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "checking", "检查 ClickHouse 数据状态"))
    try:
        before_status = data_status_runner()
        trade_date = payload.trade_date or _resolve_trade_date(before_status)
        store.update_job(job_id, status="running", progress=_progress(20, "minute5_sync", f"补齐 {trade_date.isoformat()} 5m 分钟线"))
        sync_result = minute5_runner(
            db_path=stock_db_path,
            trade_date=trade_date,
            limit=0,
            symbols=None,
            include_st=False,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(20 + int(percent * 0.5), stage, message),
            ),
        )
        retry_result = None
        retry_symbols = list(sync_result.get("no_data_symbols") or [])
        if payload.retry_no_data and retry_symbols:
            store.update_job(job_id, status="running", progress=_progress(75, "retry", f"重试 {len(retry_symbols)} 个缺失标的"))
            retry_result = minute5_runner(
                db_path=stock_db_path,
                trade_date=trade_date,
                limit=0,
                symbols=retry_symbols,
                include_st=False,
                progress=lambda percent, stage, message: store.update_job(
                    job_id,
                    status="running",
                    progress=_progress(75 + int(percent * 0.1), stage, message),
                ),
            )
        daily_repair = None
        if daily_repair_runner is not None:
            store.update_job(job_id, status="running", progress=_progress(84, "daily_repair", "用 5m 分钟线修复日线"))
            daily_repair = daily_repair_runner(trade_date=trade_date)
        index_daily = None
        if index_daily_sync_runner is not None:
            start = trade_date - timedelta(days=6)
            store.update_job(job_id, status="running", progress=_progress(86, "index_daily", "补齐指数日线"))
            index_daily = index_daily_sync_runner(start=start, end=trade_date)
        after_status = data_status_runner()
        health_snapshot = None
        if quality_snapshot_writer is not None:
            store.update_job(job_id, status="running", progress=_progress(88, "quality_snapshot", "写入数据质量快照"))
            health_snapshot = quality_snapshot_writer(quality=after_status.get("quality"))
        strategy_review = None
        if payload.run_strategy_review:
            store.update_job(job_id, status="running", progress=_progress(90, "strategy_review", "复核尾盘策略链路"))
            strategy_review = _run_strategy_review(
                tail_live_runner=tail_live_runner,
                signal_repository=signal_repository,
                job_id=job_id,
                trade_date=trade_date,
                payload=payload,
                progress=lambda percent, stage, message: store.update_job(
                    job_id,
                    status="running",
                    progress=_progress(min(99, 90 + int(percent * 0.09)), stage, message),
                ),
            )
        result = {
            "trade_date": trade_date.isoformat(),
            "before_status": before_status,
            "sync": sync_result,
            "retry": retry_result,
            "daily_repair": daily_repair,
            "index_daily": index_daily,
            "health_snapshot": health_snapshot,
            "after_status": after_status,
            "verification": _maintenance_verification(after_status),
            "strategy_review": strategy_review,
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "日常维护失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "日常维护完成"))


def _run_clickhouse_dataset_build_job(
    store: JobStore,
    builder,
    dataset_root: Path,
    job_id: str,
    payload: BuildClickHouseDatasetRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(10, "building_dataset", "从 ClickHouse 构建回测数据集"))
    try:
        dataset_root.mkdir(parents=True, exist_ok=True)
        dataset_name = _safe_dataset_name(payload.name)
        output_path = dataset_root / f"{dataset_name}.parquet"
        manifest_path = dataset_root / f"{dataset_name}_manifest.json"
        manifest = builder(
            start=payload.start,
            end=payload.end,
            output_path=output_path,
            manifest_path=manifest_path,
            symbols=payload.symbols,
            limit=payload.limit,
        )
        result = {
            "dataset_id": output_path.name,
            "dataset_path": str(output_path),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "数据集构建失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "数据集构建完成"))


def _safe_dataset_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name.strip())
    if not cleaned:
        raise ValueError("dataset name is empty")
    return cleaned


def _resolve_trade_date(status: dict[str, Any], *, now: datetime | None = None) -> date:
    _ = status
    current = now or datetime.now()
    scheduler = TradingScheduler()
    current_date = current.date()
    if scheduler.is_trading_day(current_date):
        if current.time() >= time(15, 5):
            return current_date
        return scheduler.prev_trading_day(current_date)
    return scheduler.prev_trading_day(current_date)


def _run_strategy_review(
    *,
    tail_live_runner,
    signal_repository,
    job_id: str,
    trade_date: date,
    payload: DailyMaintenanceRequest,
    progress,
) -> dict[str, Any]:
    request = TailLiveSelectionRequest(
        trade_date=trade_date,
        symbols=None,
        limit=payload.strategy_limit,
        universe=payload.strategy_universe,
        bars_cache_dir=payload.bars_cache_dir,
        liquidity_min_bars=120,
        confirmations=2,
        top_n=payload.strategy_top_n,
        ignore_session=True,
        output_dir=payload.output_dir,
    )
    result = tail_live_runner(request, progress=progress)
    persistence = _persist_tail_signal_result(signal_repository, job_id, result)
    ranked = result.get("ranked_signals") or []
    selections = result.get("selections") or []
    diagnostics = result.get("diagnostics") or {}
    return {
        "mode": result.get("mode"),
        "scanned_count": result.get("scanned_count"),
        "ranked_count": len(ranked),
        "selected_count": result.get("selected_count", len(selections)),
        "empty_reason": diagnostics.get("empty_reason", ""),
        "persistence": persistence,
    }


def _maintenance_verification(status: dict[str, Any]) -> dict[str, Any]:
    health = status.get("health") or {}
    return {
        "daily_latest_date": health.get("daily_latest_date"),
        "daily_symbols": health.get("daily_symbol_count", 0),
        "minute5_latest_datetime": health.get("minute5_latest_datetime"),
        "minute5_complete_symbols": health.get("minute5_symbol_count", 0),
        "status": health.get("status", "unknown"),
    }


def _parse_optional_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _progress(percent: int, stage: str, message: str) -> dict[str, Any]:
    return {"percent": percent, "stage": stage, "message": message}


def _elapsed(started_at: float) -> float:
    return round(max(0.0, perf_counter() - started_at), 4)
