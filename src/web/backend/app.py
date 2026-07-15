"""FastAPI application factory for the dashboard backend."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_history_window, sync_clickhouse_minute5_kline
from src.data.clickhouse_quote_snapshot_sync import sync_clickhouse_quote_snapshots
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.clickhouse_table_maintenance import optimize_quote_snapshot_rollups
from src.data.clickhouse_daily_sync import sync_clickhouse_daily_from_minute5, sync_clickhouse_index_daily
from src.data.mootdx_clickhouse_sync import sync_mootdx_offline_data, verify_mootdx_daily_gaps
from src.data.stock_data_readiness import run_readiness_repair, run_readiness_snapshot
from src.data.fund_tail_market_data import refresh_fund_tail_proxy_quotes
from src.data.clickhouse_research_dataset import build_clickhouse_research_dataset
from src.data.fund_tail_repository import ClickHouseFundTailRepository
from src.data.tail_signal_repository import ClickHouseTailSignalRepository
from src.core.constants import format_symbol
from src.ml.tail_dataset_audit import audit_tail_ml_data
from src.ml.tail_dataset import build_tail_ml_samples_from_clickhouse
from src.ml.tail_inference import TailModelInference
from src.ml.tail_model import train_tail_model_artifact
from src.ml.tail_model_registry import evaluate_promotion_gate
from src.ml.tail_rule_baseline import evaluate_tail_rule_baseline
from src.trading.scheduler import TradingScheduler
from src.web.backend.backtests import TailBacktestRequest, run_tail_backtest
from src.web.backend.data_ops_scheduler import DataOpsScheduler, DataOpsSchedulerConfig
from src.web.backend.mootdx_monitor import MootdxMonitorService
from src.web.backend.mootdx_quality import MootdxQualityService
from src.data_ops.models import DataOpsTaskConfig
from src.data_ops.repository import ClickHouseDataOpsRepository
from src.web.backend.data_quality_calendar import DataQualityCalendarService
from src.web.backend.minute5_quality import Minute5QualityService
from src.web.backend.data_status import (
    fetch_stock_list,
    inspect_clickhouse_database,
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
    lookup_fund_metadata,
    run_local_fund_tail_advice,
    run_local_fund_tail_opportunities,
    upsert_fund_watchlist_item,
)
from src.web.backend.jobs import JobRecord, JobStore
from src.web.backend.minute5_monitor import Minute5MonitorConfig, Minute5UpdateMonitor
from src.web.backend.quote_snapshot_monitor import QuoteSnapshotMonitor, QuoteSnapshotMonitorConfig
from src.web.backend.stock_trend import analyze_stock_trend
from src.web.backend.stock_readiness import build_readiness_summary, parse_dimensions, query_readiness
from src.web.backend.tail_live import TailLiveSelectionRequest, run_tail_live_selection
from src.web.backend.tail_replay_backtest import TailReplayBacktestRequest, run_tail_replay_backtest
from src.web.backend.watchlist_monitor import get_watchlist_config, get_watchlist_report

TAIL_RESULT_ENRICHMENT_RANK_LIMIT = 300
_STOCK_UNIVERSE_RULE_KEYS = (
    "lookback_days",
    "min_trading_days",
    "min_average_amount",
    "min_listing_age_days",
    "include_beijing",
)


class CreateJobRequest(BaseModel):
    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class SyncMinute5Request(BaseModel):
    trade_date: date
    limit: int = Field(default=0, ge=0)
    symbols: list[str] | None = None
    include_st: bool = False


class Minute5InvalidRepairRequest(BaseModel):
    trade_date: date
    symbols: list[str] | None = None
    mode: Literal["refetch", "delete_and_refetch"] = "delete_and_refetch"
    limit: int = Field(default=1000, ge=1, le=5000)


class Minute5MissingRepairRequest(BaseModel):
    trade_date: date
    symbols: list[str] | None = None
    limit: int = Field(default=10000, ge=1, le=10000)


class DailyMaintenanceRequest(BaseModel):
    trade_date: date | None = None
    retry_no_data: bool = True
    run_strategy_review: bool = True
    strategy_limit: int = Field(default=500, ge=1)
    strategy_top_n: int = Field(default=10, ge=1)
    strategy_universe: str = "default"
    bars_cache_dir: str = "data/cache/bars"
    output_dir: str = "reports/tail_session"


class TailModelTrainRequest(BaseModel):
    start: date
    end: date
    version: str | None = None
    train_days: int = Field(default=60, ge=20)
    validation_days: int = Field(default=10, ge=5)
    top_n: int = Field(default=2, ge=1, le=10)
    symbols: list[str] | None = None


class DataHealthRepairRequest(BaseModel):
    action_keys: list[str] | None = None


class DataOpsTaskConfigRequest(BaseModel):
    enabled: bool
    schedule_kind: str
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    max_runtime_seconds: int = Field(default=1800, ge=1)
    stale_after_seconds: int = Field(default=300, ge=1)


class MootdxDailyGapRepairItem(BaseModel):
    symbol: str = Field(min_length=9, max_length=16)
    start_date: date
    end_date: date
    evidence: str = Field(min_length=1, max_length=300)


class MootdxDailyGapRepairRequest(BaseModel):
    items: list[MootdxDailyGapRepairItem] = Field(min_length=1, max_length=100)


class MootdxUniverseProfileFiltersRequest(BaseModel):
    filters: list[dict[str, Any]] = Field(default_factory=list)


class MootdxDailyGapReviewRequest(BaseModel):
    symbol: str = Field(min_length=9, max_length=16)
    start_date: date
    end_date: date
    reason: str = Field(min_length=2, max_length=300)


class DataQualityCalendarGenerateRequest(BaseModel):
    start: date
    end: date
    source_keys: list[str] | None = None


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


class StockReadinessRepairRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=lambda: ["daily", "minute5"])
    start: date
    end: date


class StockReadinessSnapshotRequest(BaseModel):
    dimensions: list[str] = Field(default_factory=lambda: ["daily", "minute5"])
    start: date
    end: date
    symbols: list[str] | None = None
    limit: int = Field(default=0, ge=0)


def create_app(
    *,
    db_path: str | Path = "data/web/jobs.json",
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
    run_jobs_inline: bool = False,
    tail_live_runner=run_tail_live_selection,
    tail_replay_runner=run_tail_replay_backtest,
    fund_tail_downloader: FundTailDownloader | None = None,
    fund_tail_proxy_refresher: FundTailProxyRefresher | None = None,
    fund_tail_opportunity_refresher: FundTailOpportunityRefresher | None = None,
    fund_tail_metadata_lookup_runner=lookup_fund_metadata,
    minute5_sync_runner=sync_clickhouse_minute5_kline,
    minute5_invalid_repair_runner=sync_clickhouse_minute5_history_window,
    minute5_monitor_session_checker=None,
    auto_start_minute5_monitor: bool = False,
    minute5_auto_interval_seconds: int = 60,
    quote_snapshot_sync_runner=sync_clickhouse_quote_snapshots,
    quote_snapshot_session_checker=None,
    auto_start_quote_snapshot_monitor: bool = False,
    quote_snapshot_interval_seconds: int = 10,
    data_status_runner=inspect_clickhouse_database,
    stock_list_runner=fetch_stock_list,
    daily_repair_runner=sync_clickhouse_daily_from_minute5,
    index_daily_sync_runner=sync_clickhouse_index_daily,
    quality_snapshot_writer=persist_clickhouse_quality_snapshot,
    quote_rollup_optimizer=optimize_quote_snapshot_rollups,
    auto_start_data_ops_scheduler: bool = False,
    data_ops_interval_seconds: int = 60,
    data_ops_maintenance_runner=None,
    data_ops_repository=None,
    mootdx_daily_gap_repair_runner=sync_mootdx_offline_data,
    mootdx_daily_gap_verify_runner=verify_mootdx_daily_gaps,
    mootdx_monitor_service=None,
    mootdx_quality_service=None,
    data_quality_calendar_service=None,
    minute5_quality_service=None,
    clickhouse_dataset_builder=build_clickhouse_research_dataset,
    tail_signal_repository=None,
    tail_ml_audit_runner=audit_tail_ml_data,
    tail_ml_sample_builder=build_tail_ml_samples_from_clickhouse,
    tail_model_trainer=train_tail_model_artifact,
    tail_model_root: str | Path = "models/tail_session",
    stock_trend_runner=analyze_stock_trend,
    watchlist_monitor_runner=get_watchlist_report,
    watchlist_config_runner=get_watchlist_config,
    stock_readiness_client=None,
    stock_readiness_snapshot_runner=run_readiness_snapshot,
    stock_readiness_repair_runner=run_readiness_repair,
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
    app.state.run_jobs_inline = run_jobs_inline
    app.state.tail_live_runner = tail_live_runner
    app.state.tail_replay_runner = tail_replay_runner
    app.state.fund_tail_downloader = fund_tail_downloader
    app.state.fund_tail_metadata_lookup_runner = fund_tail_metadata_lookup_runner
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
    app.state.minute5_sync_runner = minute5_sync_runner
    app.state.minute5_invalid_repair_runner = minute5_invalid_repair_runner
    app.state.quote_snapshot_sync_runner = quote_snapshot_sync_runner
    app.state.data_status_runner = data_status_runner
    app.state.stock_list_runner = stock_list_runner
    app.state.daily_repair_runner = daily_repair_runner
    app.state.index_daily_sync_runner = index_daily_sync_runner
    app.state.quality_snapshot_writer = quality_snapshot_writer
    app.state.quote_rollup_optimizer = quote_rollup_optimizer
    app.state.clickhouse_dataset_builder = clickhouse_dataset_builder
    app.state.tail_signal_repository = tail_signal_repository or ClickHouseTailSignalRepository()
    app.state.tail_ml_audit_runner = tail_ml_audit_runner
    app.state.tail_ml_sample_builder = tail_ml_sample_builder
    app.state.tail_model_trainer = tail_model_trainer
    app.state.tail_model_root = Path(tail_model_root)
    app.state.stock_trend_runner = stock_trend_runner
    app.state.watchlist_monitor_runner = watchlist_monitor_runner
    app.state.watchlist_config_runner = watchlist_config_runner
    app.state.stock_readiness_client = stock_readiness_client
    app.state.stock_readiness_snapshot_runner = stock_readiness_snapshot_runner
    app.state.stock_readiness_repair_runner = stock_readiness_repair_runner
    app.state.minute5_monitor = Minute5UpdateMonitor(
        runner=app.state.minute5_sync_runner,
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
    app.state.data_ops_repository = data_ops_repository or ClickHouseDataOpsRepository()
    app.state.mootdx_daily_gap_repair_runner = mootdx_daily_gap_repair_runner
    app.state.mootdx_daily_gap_verify_runner = mootdx_daily_gap_verify_runner
    app.state.mootdx_monitor_service = mootdx_monitor_service or MootdxMonitorService(repository=app.state.data_ops_repository)
    app.state.mootdx_quality_service = mootdx_quality_service or MootdxQualityService(job_store=store)
    app.state.data_quality_calendar = data_quality_calendar_service or DataQualityCalendarService()
    app.state.minute5_quality = minute5_quality_service or Minute5QualityService()

    def _auto_data_maintenance() -> dict[str, Any]:
        payload = DailyMaintenanceRequest(run_strategy_review=False)
        job = store.create_job("daily_maintenance", {"auto": True, **payload.model_dump(mode="json")})
        _run_daily_maintenance_job(
            store,
            app.state.minute5_sync_runner,
            app.state.data_status_runner,
            app.state.tail_live_runner,
            app.state.tail_signal_repository,
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
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/jobs")
    def create_job(payload: CreateJobRequest) -> dict[str, Any]:
        return store.create_job(payload.kind, payload.params).to_dict()

    @app.get("/api/jobs")
    def list_jobs(limit: int = 50) -> dict[str, Any]:
        return {"items": [_job_list_item(job) for job in store.list_jobs(limit=limit)]}

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
    def get_data_status(as_of: date | None = None) -> dict[str, Any]:
        if as_of is not None:
            return app.state.data_status_runner(as_of=as_of)
        return app.state.data_status_runner()

    @app.get("/api/data/quality-calendar")
    def get_data_quality_calendar(start: date, end: date, source_keys: str | None = None) -> dict[str, Any]:
        selected = [key for key in source_keys.split(",") if key] if source_keys else None
        return app.state.data_quality_calendar.list(start=start, end=end, source_keys=selected)

    @app.post("/api/data/quality-calendar/generate")
    def generate_data_quality_calendar(payload: DataQualityCalendarGenerateRequest) -> dict[str, Any]:
        return app.state.data_quality_calendar.generate(
            start=payload.start,
            end=payload.end,
            source_keys=payload.source_keys,
        )

    @app.get("/api/data/minute5-quality/summary")
    def get_minute5_quality_summary() -> dict[str, Any]:
        return app.state.minute5_quality.summary()

    @app.get("/api/data/minute5-quality/days")
    def get_minute5_quality_days(start: date | None = None, end: date | None = None, limit: int = 90) -> dict[str, Any]:
        return app.state.minute5_quality.days(start=start, end=end, limit=limit)

    @app.get("/api/data/minute5-quality/buckets")
    def get_minute5_quality_buckets(trade_date: date) -> dict[str, Any]:
        return app.state.minute5_quality.buckets(trade_date=trade_date)

    @app.get("/api/data/minute5-quality/sample")
    def get_minute5_quality_sample(
        trade_date: date | None = None,
        mode: Literal["random", "invalid", "low_coverage"] = "random",
        limit: int = 20,
    ) -> dict[str, Any]:
        return app.state.minute5_quality.sample(trade_date=trade_date, mode=mode, limit=limit)

    @app.get("/api/data/minute5-quality/symbol-bars")
    def get_minute5_quality_symbol_bars(symbol: str, trade_date: date) -> dict[str, Any]:
        return app.state.minute5_quality.symbol_bars(symbol=symbol, trade_date=trade_date)

    @app.get("/api/data/minute5-quality/missing-symbols")
    def get_minute5_quality_missing_symbols(
        trade_date: date,
        bucket: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return app.state.minute5_quality.missing_symbols(trade_date=trade_date, bucket=bucket, limit=limit)

    @app.get("/api/data/minute5-quality/invalid-rows")
    def get_minute5_quality_invalid_rows(trade_date: date, limit: int = 200) -> dict[str, Any]:
        return app.state.minute5_quality.invalid_rows(trade_date=trade_date, limit=limit)

    @app.get("/api/data/minute5-quality/backfill-plan")
    def get_minute5_quality_backfill_plan(start: date, end: date, limit: int = 90) -> dict[str, Any]:
        return app.state.minute5_quality.backfill_plan(start=start, end=end, limit=limit)

    @app.post("/api/data/minute5-quality/repair-invalid")
    def create_minute5_invalid_repair(
        payload: Minute5InvalidRepairRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job = store.create_job("minute5_invalid_repair", payload.model_dump(mode="json"))
        if app.state.run_jobs_inline:
            _run_minute5_invalid_repair_job(
                store,
                app.state.minute5_quality,
                app.state.minute5_invalid_repair_runner,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_minute5_invalid_repair_job,
                store,
                app.state.minute5_quality,
                app.state.minute5_invalid_repair_runner,
                job.id,
                payload,
            )
        return {"job_id": job.id}

    @app.post("/api/data/minute5-quality/repair-missing")
    def create_minute5_missing_repair(
        payload: Minute5MissingRepairRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job = store.create_job("minute5_missing_repair", payload.model_dump(mode="json"))
        if app.state.run_jobs_inline:
            _run_minute5_missing_repair_job(
                store,
                app.state.minute5_quality,
                app.state.minute5_invalid_repair_runner,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_minute5_missing_repair_job,
                store,
                app.state.minute5_quality,
                app.state.minute5_invalid_repair_runner,
                job.id,
                payload,
            )
        return {"job_id": job.id}

    @app.get("/api/stocks")
    def list_stocks() -> dict[str, Any]:
        return app.state.stock_list_runner()

    @app.get("/api/stock-readiness/summary")
    def get_stock_readiness_summary(start: date, end: date, dimensions: str | None = None) -> dict[str, Any]:
        return build_readiness_summary(
            _stock_readiness_client(app),
            start=start,
            end=end,
            dimensions=parse_dimensions(dimensions),
        )

    @app.get("/api/stock-readiness")
    def get_stock_readiness(
        start: date,
        end: date,
        dimensions: str | None = None,
        status: str = "all",
        market: str = "all",
        board: str = "all",
        q: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        return query_readiness(
            _stock_readiness_client(app),
            start=start,
            end=end,
            dimensions=parse_dimensions(dimensions),
            status=status,
            market=market,
            board=board,
            q=q,
            page=page,
            page_size=page_size,
        )

    @app.post("/api/stock-readiness/snapshot")
    def create_stock_readiness_snapshot(
        payload: StockReadinessSnapshotRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job = store.create_job("stock_readiness_snapshot", payload.model_dump(mode="json"))
        if app.state.run_jobs_inline:
            _run_stock_readiness_snapshot_job(
                store,
                app.state.stock_readiness_snapshot_runner,
                _stock_readiness_client(app),
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_stock_readiness_snapshot_job,
                store,
                app.state.stock_readiness_snapshot_runner,
                _stock_readiness_client(app),
                job.id,
                payload,
            )
        return {"job_id": job.id}

    @app.post("/api/stock-readiness/repair")
    def create_stock_readiness_repair(
        payload: StockReadinessRepairRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job = store.create_job("stock_readiness_repair", payload.model_dump(mode="json"))
        if app.state.run_jobs_inline:
            _run_stock_readiness_repair_job(
                store,
                app.state.stock_readiness_repair_runner,
                _stock_readiness_client(app),
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_stock_readiness_repair_job,
                store,
                app.state.stock_readiness_repair_runner,
                _stock_readiness_client(app),
                job.id,
                payload,
            )
        return {"job_id": job.id}

    @app.get("/api/data/health-repair-plan")
    def get_data_health_repair_plan() -> dict[str, Any]:
        return build_data_health_repair_plan(app.state.data_status_runner())

    @app.get("/api/data/reliability")
    def get_data_reliability() -> dict[str, Any]:
        status = app.state.data_status_runner()
        repair_plan = build_data_health_repair_plan(status)
        task_statuses = _safe_data_ops_task_statuses(app.state.data_ops_repository)
        report = build_data_reliability_report(
            status=status,
            minute5_monitor=app.state.minute5_monitor.status(),
            quote_monitor=app.state.quote_snapshot_monitor.status(),
            scheduler=app.state.data_ops_scheduler.status(),
            repair_plan=repair_plan,
            data_ops_tasks=task_statuses,
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
            granularity="5m",
        )

    @app.get("/api/watchlist-monitor/report")
    def get_watchlist_monitor_report(trade_date: date | None = None) -> dict[str, Any]:
        return app.state.watchlist_monitor_runner(trade_date=trade_date)

    @app.get("/api/watchlist-monitor/config")
    def get_watchlist_monitor_config() -> dict[str, Any]:
        return app.state.watchlist_config_runner()

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
                app.state.data_status_runner,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_minute5_sync_job,
                store,
                app.state.minute5_sync_runner,
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

    @app.get("/api/data/ops-tasks")
    def get_data_ops_tasks() -> dict[str, Any]:
        repository = app.state.data_ops_repository
        repository.ensure_tables()
        repository.seed_default_configs()
        return {"items": [_data_ops_status_item(status) for status in repository.list_task_statuses()]}

    @app.put("/api/data/ops-tasks/{task_key}/config")
    def update_data_ops_task_config(task_key: str, payload: DataOpsTaskConfigRequest) -> dict[str, Any]:
        repository = app.state.data_ops_repository
        configs = {config.task_key: config for config in repository.list_task_configs()}
        if task_key not in configs:
            raise HTTPException(status_code=404, detail="Data ops task not found")
        existing = configs[task_key]
        schedule_config = dict(payload.schedule_config)
        if task_key == "stock_universe_profile_refresh":
            current_rules = {key: existing.schedule_config.get(key) for key in _STOCK_UNIVERSE_RULE_KEYS}
            next_rules = {key: schedule_config.get(key) for key in _STOCK_UNIVERSE_RULE_KEYS}
            current_version = max(1, int(existing.schedule_config.get("rule_version") or 1))
            schedule_config["rule_version"] = current_version + 1 if current_rules != next_rules else current_version
        repository.upsert_task_config(
            DataOpsTaskConfig(
                task_key=task_key,
                enabled=payload.enabled,
                schedule_kind=payload.schedule_kind,
                schedule_config=schedule_config,
                max_runtime_seconds=payload.max_runtime_seconds,
                stale_after_seconds=payload.stale_after_seconds,
                manual_trigger=existing.manual_trigger,
                manual_triggered_at=existing.manual_triggered_at,
            )
        )
        statuses = {status.task_key: status for status in repository.list_task_statuses()}
        return {"item": _data_ops_status_item(statuses[task_key])}

    @app.post("/api/data/ops-tasks/{task_key}/run-once")
    def run_data_ops_task_once(task_key: str) -> dict[str, Any]:
        repository = app.state.data_ops_repository
        if task_key not in {config.task_key for config in repository.list_task_configs()}:
            raise HTTPException(status_code=404, detail="Data ops task not found")
        repository.request_manual_run(task_key)
        return {"task_key": task_key, "manual_trigger": True}

    @app.get("/api/data/mootdx/monitor")
    def get_mootdx_monitor(audit_limit: int = 50) -> dict[str, Any]:
        return app.state.mootdx_monitor_service.snapshot(audit_limit=audit_limit)

    @app.get("/api/data/mootdx/monitor/audits/{run_id}")
    def get_mootdx_monitor_audit(run_id: str) -> dict[str, Any]:
        item = app.state.mootdx_monitor_service.audit_detail(run_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Mootdx audit not found")
        return {"item": item}

    @app.get("/api/data/mootdx/catalog-quality")
    def get_mootdx_catalog_quality(event_limit: int = 200) -> dict[str, Any]:
        return app.state.mootdx_quality_service.catalog_quality(event_limit=event_limit)

    @app.get("/api/data/mootdx/catalog-quality/events")
    def get_mootdx_catalog_change_events(
        event_date: date | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        return {"items": app.state.mootdx_quality_service.catalog_change_events(
            event_date=event_date,
            event_type=event_type,
            limit=limit,
        )}

    @app.post("/api/data/mootdx/catalog-quality/universe-profiles")
    def get_mootdx_universe_profiles(payload: MootdxUniverseProfileFiltersRequest, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return app.state.mootdx_quality_service.universe_profiles(filters=payload.filters, limit=limit, offset=offset)

    @app.get("/api/data/mootdx/daily-quality")
    def get_mootdx_daily_quality(lookback_days: int = 30, missing_limit: int = 200) -> dict[str, Any]:
        return app.state.mootdx_quality_service.daily_quality(
            lookback_days=lookback_days,
            missing_limit=missing_limit,
        )

    @app.post("/api/data/mootdx/daily-quality/repair")
    def create_mootdx_daily_gap_repair(
        payload: MootdxDailyGapRepairRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job = store.create_job("mootdx_daily_gap_repair", payload.model_dump(mode="json"))
        if app.state.run_jobs_inline:
            _run_mootdx_daily_gap_repair_job(
                store,
                app.state.mootdx_daily_gap_repair_runner,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_mootdx_daily_gap_repair_job,
                store,
                app.state.mootdx_daily_gap_repair_runner,
                job.id,
                payload,
            )
        return {"job_id": job.id}

    @app.post("/api/data/mootdx/daily-quality/verify")
    def create_mootdx_daily_gap_verify(
        payload: MootdxDailyGapRepairRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job = store.create_job("mootdx_daily_gap_verify", payload.model_dump(mode="json"))
        runner = _run_mootdx_daily_gap_verify_job
        args = (store, app.state.mootdx_daily_gap_verify_runner, job.id, payload)
        if app.state.run_jobs_inline:
            runner(*args)
        else:
            background_tasks.add_task(runner, *args)
        return {"job_id": job.id}

    @app.post("/api/data/mootdx/daily-quality/review-no-repair")
    def review_mootdx_daily_gap_no_repair(payload: MootdxDailyGapReviewRequest) -> dict[str, str]:
        job = store.create_job("mootdx_daily_gap_review", payload.model_dump(mode="json"))
        store.update_job(
            job.id,
            status="success",
            result={"decision": "no_repair"},
            progress=_progress(100, "completed", "已记录人工核验结论"),
        )
        return {"job_id": job.id}

    @app.get("/api/data/ops-scheduler")
    def get_data_ops_scheduler_status() -> dict[str, Any]:
        return {**app.state.data_ops_scheduler.status(), "deprecated": True}

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
            try:
                return {"items": list_fund_universe_from_repository(app.state.fund_tail_repository)}
            except Exception as exc:  # noqa: BLE001 - keep the fund-tail page diagnosable when ClickHouse is down.
                return _fund_tail_degraded_response(exc, items=[])
        return {"items": list_fund_universe(fund_tail_paths.data_dir)}

    @app.get("/api/fund-tail/report")
    def get_fund_tail_report() -> dict[str, Any]:
        try:
            return load_latest_fund_tail_report(
                fund_tail_paths.report_path,
                fund_tail_paths.markdown_path,
                app.state.fund_tail_repository,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to local report if repository access fails.
            payload = load_latest_fund_tail_report(
                fund_tail_paths.report_path,
                fund_tail_paths.markdown_path,
                None,
            )
            return _fund_tail_degraded_response(exc, **payload)

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
        try:
            return {"items": list_fund_watchlist(app.state.fund_tail_repository)}
        except Exception as exc:  # noqa: BLE001 - keep read-only page load from failing hard.
            return _fund_tail_degraded_response(exc, items=[])

    @app.get("/api/fund-tail/funds/{fund_code}")
    def get_fund_tail_metadata(fund_code: str) -> dict[str, Any]:
        try:
            return {"item": app.state.fund_tail_metadata_lookup_runner(fund_code)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Fund metadata lookup failed: {exc}") from exc

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
                app.state.tail_signal_repository,
                app.state.tail_model_root,
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
                app.state.tail_signal_repository,
                app.state.tail_model_root,
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
        try:
            return app.state.tail_ml_audit_runner()
        except Exception as exc:  # noqa: BLE001 - degrade optional ML audit without blanking data center.
            return {
                "status": "blocked",
                "as_of": date.today().isoformat(),
                "summary": {},
                "issues": ["tail_ml_audit_failed"],
                "error": str(exc),
            }

    @app.get("/api/ml/tail/models")
    def get_tail_ml_models() -> dict[str, Any]:
        return _list_tail_model_manifests(app.state.tail_model_root)

    @app.post("/api/ml/tail/models/{version}/promote")
    def promote_tail_ml_model(version: str) -> dict[str, Any]:
        try:
            return _promote_tail_model_manifest(app.state.tail_model_root, version)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ml/tail/train")
    def create_tail_ml_train(
        payload: TailModelTrainRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("tail_ml_train", payload.model_dump(mode="json"))
        if app.state.run_jobs_inline:
            _run_tail_ml_train_job(
                store,
                app.state.tail_ml_sample_builder,
                app.state.tail_model_trainer,
                app.state.tail_model_root,
                job.id,
                payload,
            )
        else:
            background_tasks.add_task(
                _run_tail_ml_train_job,
                store,
                app.state.tail_ml_sample_builder,
                app.state.tail_model_trainer,
                app.state.tail_model_root,
                job.id,
                payload,
            )
        return {"job_id": job.id}

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


def _stock_readiness_client(app: FastAPI):
    if app.state.stock_readiness_client is not None:
        return app.state.stock_readiness_client
    return ClickHouseStockDataSource()._client_instance()


def _default_fund_tail_proxy_refresher(**kwargs) -> dict[str, Any]:
    return refresh_fund_tail_proxy_quotes(proxy_specs=PROXY_INDEXES, **kwargs)


def _list_tail_model_manifests(model_root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if model_root.exists():
        for manifest_path in sorted(model_root.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                manifest = {
                    "version": manifest_path.parent.name,
                    "status": "invalid",
                    "error": str(exc),
                    "metrics": {},
                    "feature_columns": [],
                }
            manifest.setdefault("version", manifest_path.parent.name)
            manifest["artifact_dir"] = str(manifest_path.parent)
            items.append(manifest)
    items.sort(key=lambda item: str(item.get("created_at") or item.get("version") or ""), reverse=True)
    return {"model_root": str(model_root), "items": items}


def _load_promoted_tail_model_scorer(model_root: Path) -> TailModelInference | None:
    manifests = _list_tail_model_manifests(model_root)["items"]
    for manifest in manifests:
        if manifest.get("status") != "promoted":
            continue
        model_path = Path(str(manifest["artifact_dir"])) / "model.joblib"
        if model_path.exists():
            return TailModelInference(model_path)
    return None


def _promote_tail_model_manifest(model_root: Path, version: str) -> dict[str, Any]:
    target_path = model_root / version / "manifest.json"
    if not target_path.exists():
        raise FileNotFoundError(f"Tail model manifest not found: {version}")
    promoted_manifest: dict[str, Any] | None = None
    for manifest_path in model_root.glob("*/manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("version", manifest_path.parent.name)
        if manifest_path == target_path:
            manifest["status"] = "promoted"
            promoted_manifest = manifest
        elif manifest.get("status") == "promoted":
            manifest["status"] = "ready"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if promoted_manifest is None:
        raise FileNotFoundError(f"Tail model manifest not found: {version}")
    promoted_manifest["artifact_dir"] = str(target_path.parent)
    return promoted_manifest


app = create_app()


def _run_tail_ml_train_job(
    store: JobStore,
    sample_builder,
    model_trainer,
    model_root: Path,
    job_id: str,
    payload: TailModelTrainRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "尾盘模型训练启动"))
    try:
        store.update_job(job_id, status="running", progress=_progress(20, "building_samples", "构建尾盘训练样本"))
        dataset = sample_builder(start=payload.start, end=payload.end, symbols=payload.symbols)
        training_samples, dropped_null_labels = _tail_training_samples_with_complete_labels(dataset.samples)
        dataset_summary = dict(dataset.summary)
        dataset_summary["dropped_null_label_rows"] = dropped_null_labels
        dataset_summary["training_sample_rows"] = int(len(training_samples))
        if training_samples.empty:
            raise ValueError("tail ML training samples are empty")

        version = payload.version or f"tail-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        store.update_job(job_id, status="running", progress=_progress(65, "training_model", "训练尾盘模型"))
        manifest = model_trainer(
            training_samples,
            version=version,
            output_root=model_root,
            train_days=payload.train_days,
            validation_days=payload.validation_days,
            top_n=payload.top_n,
        )
        baseline_report = evaluate_tail_rule_baseline(training_samples, top_ns=(payload.top_n,))
        baseline_metrics = _tail_baseline_metrics_for_top_n(baseline_report, top_n=payload.top_n)
        promotion_decision = evaluate_promotion_gate(
            model_metrics=dict(manifest.get("metrics") or {}),
            baseline_metrics=baseline_metrics,
            audit_status={"status": "ready", "issues": []},
        )
        manifest = {
            **manifest,
            "baseline_metrics": baseline_metrics,
            "promotion_decision": promotion_decision,
        }
        _write_tail_model_manifest_if_present(manifest)
        result = {
            "version": version,
            "dataset_summary": dataset_summary,
            "manifest": manifest,
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "尾盘模型训练失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "尾盘模型训练完成"))


TAIL_TRAIN_LABEL_COLUMNS = [
    "next_open_return",
    "next_high_return",
    "next_low_return",
    "hit_next_high_1pct",
    "drawdown_breach_2pct",
]


def _tail_training_samples_with_complete_labels(samples) -> tuple[Any, int]:
    if samples.empty:
        return samples, 0
    label_columns = [column for column in TAIL_TRAIN_LABEL_COLUMNS if column in samples]
    if not label_columns:
        return samples, 0
    mask = samples[label_columns].notna().all(axis=1)
    return samples.loc[mask].copy(), int((~mask).sum())


def _tail_baseline_metrics_for_top_n(baseline_report: dict[str, Any], *, top_n: int) -> dict[str, Any]:
    for row in baseline_report.get("by_top_n") or []:
        if int(row.get("top_n") or 0) == top_n:
            return dict(row)
    return {}


def _write_tail_model_manifest_if_present(manifest: dict[str, Any]) -> None:
    artifact_dir = manifest.get("artifact_dir")
    if not artifact_dir:
        return
    manifest_path = Path(str(artifact_dir)) / "manifest.json"
    if not manifest_path.exists():
        return
    payload = {key: value for key, value in manifest.items() if key != "artifact_dir"}
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    signal_repository,
    tail_model_root: Path,
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
        model_scorer = _load_promoted_tail_model_scorer(tail_model_root) if payload.strategy_mode != "rule" else None
        progress_callback = lambda percent, stage, message: store.update_job(
            job_id,
            status="running",
            progress=_progress(45 + int(percent * 0.5), stage, message),
        )
        if payload.strategy_mode == "rule":
            result = runner(payload, progress=progress_callback)
        else:
            result = runner(payload, progress=progress_callback, model_scorer=model_scorer)
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
        stage_started = perf_counter()
        store.update_job(job_id, status="running", progress=_progress(88, "historical_calibration", "校准候选历史胜率"))
        _apply_tail_historical_calibration(signal_repository, result)
        _apply_tail_historical_selection(result)
        stage_timings["historical_calibration"] = _elapsed(stage_started)
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


def _apply_tail_historical_calibration(signal_repository, result: dict[str, Any]) -> None:
    calibrate = getattr(signal_repository, "historical_calibration_for_signal", None)
    if not callable(calibrate):
        return
    cache_key_for_signal = getattr(signal_repository, "historical_calibration_cache_key", None)
    if not callable(cache_key_for_signal):
        cache_key_for_signal = None

    cache: dict[Any, dict[str, Any]] = {}
    for section in ("ranked_signals", "selections", "preview_signals", "watchlist_signals", "weak_signals"):
        rows = result.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not _should_calibrate_tail_history(section, row):
                continue
            credibility = row.get("credibility")
            if not isinstance(credibility, dict):
                continue
            v2_score = _number_or_none(row.get("v2_score") or credibility.get("score"))
            volume_ratio = _number_or_none(row.get("volume_ratio"))
            tail_return = _number_or_none(row.get("tail_return"))
            key = (
                cache_key_for_signal(v2_score=v2_score, volume_ratio=volume_ratio, tail_return=tail_return)
                if cache_key_for_signal is not None
                else (v2_score, volume_ratio, tail_return)
            )
            if key not in cache:
                try:
                    cache[key] = calibrate(
                        v2_score=v2_score,
                        volume_ratio=volume_ratio,
                        tail_return=tail_return,
                    )
                except Exception as exc:
                    cache[key] = {
                        "status": "校准失败",
                        "sample_count": 0,
                        "note": f"历史校准查询失败：{exc}",
                    }
            credibility["history"] = cache[key]
            _update_tail_calibrated_credibility(credibility, cache[key])
    result.setdefault("diagnostics", {})["historical_calibration_rank_limit"] = TAIL_RESULT_ENRICHMENT_RANK_LIMIT


def _should_calibrate_tail_history(section: str, row: dict[str, Any]) -> bool:
    if section in {"selections", "preview_signals"}:
        return True
    if section != "ranked_signals":
        return False
    if row.get("status") in {"selected", "preview"}:
        return True
    if row.get("final_candidate_rank") is not None:
        return True
    rank = row.get("rank")
    if rank is None:
        return True
    try:
        return int(rank) <= TAIL_RESULT_ENRICHMENT_RANK_LIMIT
    except (TypeError, ValueError):
        return False


def _apply_tail_historical_selection(result: dict[str, Any]) -> None:
    ranked = result.get("ranked_signals")
    if result.get("mode") != "selection" or not isinstance(ranked, list):
        return
    selected_count = int(result.get("selected_count") or len(result.get("selections") or []) or 0)
    if selected_count <= 0:
        return
    candidates = [
        row for row in ranked
        if isinstance(row, dict)
        and row.get("final_candidate_rank") is not None
        and _row_buyable(row)
        and _has_ready_historical_calibration(row)
    ]
    if len(candidates) <= selected_count:
        result.setdefault("diagnostics", {})["historical_calibration_selection_applied"] = False
        return

    selected_symbols = {
        str(row.get("symbol"))
        for row in sorted(candidates, key=_historical_selection_score, reverse=True)[:selected_count]
    }
    for row in ranked:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol")) in selected_symbols:
            row["status"] = "selected"
            row["filter_reason"] = None
        elif row.get("status") == "selected":
            row["status"] = "filtered"
            row["filter_reason"] = "outside_historical_calibration_top_n"
    ranked.sort(key=lambda row: _historical_ranked_display_key(row, selected_symbols=selected_symbols))
    for index, row in enumerate(ranked, start=1):
        if isinstance(row, dict):
            row["rank"] = index
    result["selections"] = [row for row in ranked if isinstance(row, dict) and str(row.get("symbol")) in selected_symbols]
    result["selected_count"] = len(result["selections"])
    diagnostics = result.setdefault("diagnostics", {})
    diagnostics["historical_calibration_selection_applied"] = True
    diagnostics["historical_calibration_selected_symbols"] = sorted(selected_symbols)


def _has_ready_historical_calibration(row: dict[str, Any]) -> bool:
    credibility = row.get("credibility") or {}
    history = credibility.get("history") or {}
    return (
        isinstance(credibility, dict)
        and history.get("status") == "ready"
        and int(history.get("sample_count") or 0) >= 10
        and _number_or_none(credibility.get("calibrated_probability")) is not None
    )


def _row_buyable(row: dict[str, Any]) -> bool:
    tradability = row.get("tradability")
    return not isinstance(tradability, dict) or bool(tradability.get("buyable", True))


def _historical_selection_score(row: dict[str, Any]) -> tuple[float, float, float, float]:
    credibility = row.get("credibility") or {}
    history = credibility.get("history") or {}
    calibrated = _number_or_none(credibility.get("calibrated_probability")) or 0.0
    avg_return = _number_or_none(history.get("avg_close_return") or credibility.get("historical_avg_return")) or 0.0
    max_win = _number_or_none(history.get("max_win_rate")) or 0.0
    rule_score = (_number_or_none(credibility.get("rule_score") or credibility.get("score")) or 0.0) / 100
    return (
        calibrated * 0.55 + max(0.0, avg_return) * 3.0 + max_win * 0.15 + rule_score * 0.15,
        avg_return,
        rule_score,
        -float(row.get("raw_rank") or row.get("rank") or 999999),
    )


def _historical_ranked_display_key(row: Any, *, selected_symbols: set[str]) -> tuple[Any, ...]:
    if not isinstance(row, dict):
        return (3, 0)
    symbol = str(row.get("symbol"))
    candidate = row.get("final_candidate_rank") is not None and _has_ready_historical_calibration(row)
    score = _historical_selection_score(row)[0] if candidate else 0.0
    return (
        0 if symbol in selected_symbols else 1 if candidate else 2,
        -score,
        row.get("raw_rank") or row.get("rank") or 999999,
    )


def _number_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _update_tail_calibrated_credibility(credibility: dict[str, Any], history: dict[str, Any]) -> None:
    sample_size = int(history.get("sample_count") or 0)
    historical_hit_rate = _number_or_none(history.get("close_win_rate"))
    historical_avg_return = _number_or_none(history.get("avg_close_return"))
    rule_score = _number_or_none(credibility.get("rule_score") or credibility.get("score")) or 0.0
    credibility["rule_score"] = rule_score
    credibility["rule_grade"] = credibility.get("rule_grade") or credibility.get("grade") or _tail_rule_grade(rule_score)
    credibility["history_status"] = str(history.get("status") or "pending")
    credibility["sample_size"] = sample_size
    credibility["historical_hit_rate"] = historical_hit_rate
    credibility["historical_avg_return"] = historical_avg_return
    if history.get("status") == "ready" and sample_size >= 10 and historical_hit_rate is not None:
        credibility["calibrated_probability"] = round(historical_hit_rate * 0.7 + (rule_score / 100) * 0.3, 2)
    else:
        credibility["calibrated_probability"] = None


def _tail_rule_grade(score: float) -> str:
    if score >= 75:
        return "高"
    if score >= 55:
        return "中"
    return "低"


def _run_stock_readiness_snapshot_job(
    store: JobStore,
    runner,
    client,
    job_id: str,
    payload: StockReadinessSnapshotRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "策略数据就绪度快照启动"))
    try:
        result = runner({
            **payload.model_dump(mode="python"),
            "client": client,
            "progress": lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        })
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "策略数据就绪度快照失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "策略数据就绪度快照完成"))


def _run_stock_readiness_repair_job(
    store: JobStore,
    runner,
    client,
    job_id: str,
    payload: StockReadinessRepairRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "策略数据就绪度回补启动"))
    try:
        result = runner({
            **payload.model_dump(mode="python"),
            "client": client,
            "progress": lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(percent, stage, message),
            ),
        })
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "策略数据就绪度回补失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "策略数据就绪度回补完成"))


def _run_minute5_sync_job(
    store: JobStore,
    runner,
    data_status_runner,
    job_id: str,
    payload: SyncMinute5Request,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "5m 分钟线更新启动"))
    try:
        sync_result = runner(
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


def _run_minute5_invalid_repair_job(
    store: JobStore,
    quality_service,
    repair_runner,
    job_id: str,
    payload: Minute5InvalidRepairRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "scanning", "扫描异常 5m 分钟线"))
    try:
        before = quality_service.invalid_rows(payload.trade_date, limit=payload.limit)
        before_items = list(before.get("items") or [])
        requested = {format_symbol(symbol).split(".")[0] for symbol in (payload.symbols or [])}
        symbols = []
        for item in before_items:
            symbol = format_symbol(str(item.get("symbol") or "")).split(".")[0]
            if not symbol or (requested and symbol not in requested):
                continue
            if symbol not in symbols:
                symbols.append(symbol)

        if not symbols:
            result = {
                "trade_date": payload.trade_date.isoformat(),
                "mode": payload.mode,
                "symbols": [],
                "before": before,
                "delete": None,
                "sync": None,
                "after": before,
            }
            store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "没有需要修复的异常分钟线"))
            return

        delete_result = None
        if payload.mode == "delete_and_refetch":
            store.update_job(job_id, status="running", progress=_progress(20, "deleting", f"删除 {len(symbols)} 只异常标的当日分钟线"))
            delete_result = quality_service.delete_symbol_day_rows(payload.trade_date, symbols)

        def _progress_callback(percent, stage, message, **extra):
            progress = _progress(25 + int(percent * 0.65), stage, message)
            progress.update(extra)
            store.update_job(job_id, status="running", progress=progress)

        sync_result = repair_runner(
            start=payload.trade_date,
            end=payload.trade_date,
            limit=0,
            symbols=symbols,
            include_st=True,
            progress=_progress_callback,
        )
        store.update_job(job_id, status="running", progress=_progress(92, "verifying", "复查异常分钟线"))
        after = quality_service.invalid_rows(payload.trade_date, limit=payload.limit)
        result = {
            "trade_date": payload.trade_date.isoformat(),
            "mode": payload.mode,
            "symbols": symbols,
            "before": before,
            "delete": delete_result,
            "sync": sync_result,
            "after": after,
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "异常分钟线修复失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "异常分钟线修复完成"))


def _run_mootdx_daily_gap_repair_job(
    store: JobStore,
    runner,
    job_id: str,
    payload: MootdxDailyGapRepairRequest,
) -> None:
    items = payload.items
    store.update_job(job_id, status="running", progress=_progress(2, "starting", f"准备回补 {len(items)} 个日线缺口"))
    results = []
    try:
        for index, item in enumerate(items, start=1):
            start_percent = 5 + int((index - 1) / len(items) * 85)
            store.update_job(
                job_id,
                status="running",
                progress=_progress(start_percent, "backfilling", f"回补 {item.symbol} {item.start_date} 至 {item.end_date}"),
            )
            sync = runner(
                symbols=[item.symbol],
                tasks=["stock_kline_daily"],
                trade_date=item.end_date,
                daily_mode="backfill",
                start_date=item.start_date,
                end_date=item.end_date,
                recheck_no_data=True,
                progress=None,
            )
            results.append({"item": item.model_dump(mode="json"), "sync": sync})
            if sync.get("failed"):
                raise RuntimeError(f"Mootdx 日线回补失败: {sync['failed']}")
    except Exception as exc:  # noqa: BLE001 - the job record is the operator-facing audit trail.
        store.update_job(job_id, status="failed", result={"items": results}, error=str(exc), progress=_progress(100, "failed", "日线定向回补失败"))
        return
    store.update_job(
        job_id,
        status="success",
        result={"items": results, "requested_items": len(items)},
        progress=_progress(100, "completed", "日线定向回补完成，请刷新缺口判断复核"),
    )


def _run_mootdx_daily_gap_verify_job(store: JobStore, runner, job_id: str, payload: MootdxDailyGapRepairRequest) -> None:
    items = payload.items
    store.update_job(job_id, status="running", progress=_progress(1, "starting", f"准备核验 {len(items)} 个缺口", processed=0, total=len(items)))
    try:
        def report(percent: int, stage: str, message: str) -> None:
            processed = min(len(items), max(0, round(percent / 100 * len(items))))
            store.update_job(job_id, status="running", progress=_progress(percent, stage, message, processed=processed, total=len(items)))
        result = runner(items=items, progress=report)
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "Baostock 核验失败", processed=0, total=len(items)))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "Baostock 核验完成", processed=len(items), total=len(items)))


def _run_minute5_missing_repair_job(
    store: JobStore,
    quality_service,
    repair_runner,
    job_id: str,
    payload: Minute5MissingRepairRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "scanning", "扫描缺口 5m 分钟线"))
    try:
        before = quality_service.missing_symbols(payload.trade_date, limit=payload.limit)
        before_items = list(before.get("items") or [])
        requested = {format_symbol(symbol).split(".")[0] for symbol in (payload.symbols or [])}
        symbols = []
        for item in before_items:
            symbol = format_symbol(str(item.get("symbol") or "")).split(".")[0]
            if not symbol or (requested and symbol not in requested):
                continue
            if symbol not in symbols:
                symbols.append(symbol)

        if not symbols:
            result = {
                "trade_date": payload.trade_date.isoformat(),
                "symbols": [],
                "before": before,
                "sync": None,
                "after": before,
            }
            store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "没有需要回补的缺口分钟线"))
            return

        sync_result = repair_runner(
            start=payload.trade_date,
            end=payload.trade_date,
            limit=0,
            symbols=symbols,
            include_st=True,
            progress=lambda percent, stage, message: store.update_job(
                job_id,
                status="running",
                progress=_progress(10 + int(percent * 0.8), stage, message),
            ),
        )
        store.update_job(job_id, status="running", progress=_progress(92, "verifying", "复查缺口分钟线"))
        after = quality_service.missing_symbols(payload.trade_date, limit=payload.limit)
        result = {
            "trade_date": payload.trade_date.isoformat(),
            "symbols": symbols,
            "before": before,
            "sync": sync_result,
            "after": after,
        }
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "缺口分钟线回补失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "缺口分钟线回补完成"))


def _run_data_health_repair_job(
    store: JobStore,
    minute5_runner,
    quote_snapshot_runner,
    data_status_runner,
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
        if _should_run_index_daily_sync(index_daily_sync_runner, before_status):
            start = trade_date - timedelta(days=6)
            store.update_job(job_id, status="running", progress=_progress(86, "index_daily", "补齐指数日线"))
            index_daily = index_daily_sync_runner(start=start, end=trade_date)
        after_status = data_status_runner()
        health_snapshot = None
        if _should_write_quality_snapshot(quality_snapshot_writer, after_status):
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


def _safe_data_ops_task_statuses(repository) -> list[dict[str, Any]]:
    try:
        repository.ensure_tables()
        repository.seed_default_configs()
        return [_data_ops_status_item(status) for status in repository.list_task_statuses()]
    except Exception as exc:  # noqa: BLE001 - dashboard should still show data health when task store is unavailable.
        return [{"task_key": "data_ops", "enabled": False, "status": "unavailable", "last_error": str(exc)}]


def _data_ops_status_item(status) -> dict[str, Any]:
    return {
        "task_key": status.task_key,
        "enabled": status.enabled,
        "status": status.status,
        "schedule_kind": status.schedule_kind,
        "schedule_config": status.schedule_config,
        "max_runtime_seconds": status.max_runtime_seconds,
        "stale_after_seconds": status.stale_after_seconds,
        "last_started_at": _iso_or_none(status.last_started_at),
        "last_finished_at": _iso_or_none(status.last_finished_at),
        "next_run_at": _iso_or_none(status.next_run_at),
        "last_result": status.last_result or {},
        "last_error": status.last_error or "",
        "heartbeat_at": _iso_or_none(status.heartbeat_at),
        "runner_id": status.runner_id,
        "progress_percent": status.progress_percent,
        "progress_stage": status.progress_stage,
        "progress_message": status.progress_message,
        "progress_processed": status.progress_processed,
        "progress_total": status.progress_total,
    }


def _iso_or_none(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def _fund_tail_degraded_response(error: Exception, **payload: Any) -> dict[str, Any]:
    payload["status"] = "degraded"
    payload["error"] = f"{type(error).__name__}: {error}"
    return payload


def _should_run_index_daily_sync(index_daily_sync_runner, status: dict[str, Any]) -> bool:
    if index_daily_sync_runner is None:
        return False
    if index_daily_sync_runner is not sync_clickhouse_index_daily:
        return True
    return "index_daily" in (status.get("tables") or {})


def _should_write_quality_snapshot(quality_snapshot_writer, status: dict[str, Any]) -> bool:
    if quality_snapshot_writer is None:
        return False
    if quality_snapshot_writer is not persist_clickhouse_quality_snapshot:
        return True
    return status.get("quality") is not None


def _parse_optional_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _job_list_item(job: JobRecord) -> dict[str, Any]:
    item = job.to_dict()
    result = item.get("result")
    if isinstance(result, dict):
        item["result"] = _job_result_summary(result)
    return item


def _job_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary_keys = (
        "mode",
        "trade_date",
        "scanned_count",
        "candidate_count",
        "confirmed_count",
        "selected_count",
        "preview_count",
        "empty_reason",
        "dataset_id",
    )
    summary = {key: result[key] for key in summary_keys if key in result}
    ranked = result.get("ranked_signals")
    selections = result.get("selections")
    if isinstance(ranked, list):
        summary["ranked_count"] = len(ranked)
    if isinstance(selections, list):
        summary.setdefault("selected_count", len(selections))
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, dict):
        summary["diagnostics"] = {
            key: diagnostics.get(key)
            for key in ("empty_reason", "latest_intraday_time", "scan_as_of_time")
            if key in diagnostics
        }
    persistence = result.get("persistence")
    if isinstance(persistence, dict):
        summary["persistence"] = persistence
    return summary


def _progress(percent: int, stage: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"percent": percent, "stage": stage, "message": message, **extra}


def _elapsed(started_at: float) -> float:
    return round(max(0.0, perf_counter() - started_at), 4)
