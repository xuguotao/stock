"""FastAPI application factory for the dashboard backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.web.backend.backtests import TailBacktestRequest, run_tail_backtest
from src.web.backend.datasets import DatasetService
from src.web.backend.fund_tail import (
    FundTailAdviceRequest,
    FundTailPaths,
    list_fund_universe,
    load_latest_fund_tail_report,
    run_local_fund_tail_advice,
)
from src.web.backend.jobs import JobStore
from src.web.backend.tail_live import TailLiveSelectionRequest, run_tail_live_selection


class CreateJobRequest(BaseModel):
    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


def create_app(
    *,
    db_path: str | Path = "data/web/jobs.sqlite3",
    dataset_root: str | Path = "data/research",
    fund_tail_data_dir: str | Path = "data/fund_tail",
    fund_tail_report_path: str | Path = "reports/fund_tail_backtest.csv",
    fund_tail_raw_report_path: str | Path = "reports/fund_tail_backtest_raw.csv",
    fund_tail_advice_dir: str | Path = "reports/fund_tail_advice",
    fund_tail_markdown_path: str | Path = "reports/fund_tail_advice/latest.md",
    run_jobs_inline: bool = False,
    tail_live_runner=run_tail_live_selection,
) -> FastAPI:
    """Create a configured FastAPI app."""
    app = FastAPI(title="A-Share Quant Dashboard API")
    store = JobStore(db_path)
    datasets = DatasetService(dataset_root)
    fund_tail_paths = FundTailPaths(
        data_dir=Path(fund_tail_data_dir),
        report_path=Path(fund_tail_report_path),
        raw_report_path=Path(fund_tail_raw_report_path),
        advice_dir=Path(fund_tail_advice_dir),
        markdown_path=Path(fund_tail_markdown_path),
    )
    app.state.job_store = store
    app.state.dataset_service = datasets
    app.state.fund_tail_paths = fund_tail_paths
    app.state.run_jobs_inline = run_jobs_inline
    app.state.tail_live_runner = tail_live_runner

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

    @app.get("/api/fund-tail/universe")
    def get_fund_tail_universe() -> dict[str, Any]:
        return {"items": list_fund_universe(fund_tail_paths.data_dir)}

    @app.get("/api/fund-tail/report")
    def get_fund_tail_report() -> dict[str, Any]:
        return load_latest_fund_tail_report(
            fund_tail_paths.report_path,
            fund_tail_paths.markdown_path,
        )

    @app.post("/api/fund-tail/advice")
    def create_fund_tail_advice(
        payload: FundTailAdviceRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = store.create_job("fund_tail_advice", payload.model_dump(mode="json"))

        if app.state.run_jobs_inline:
            _run_fund_tail_advice_job(store, fund_tail_paths, job.id, payload)
        else:
            background_tasks.add_task(_run_fund_tail_advice_job, store, fund_tail_paths, job.id, payload)

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
            _run_tail_live_selection_job(store, app.state.tail_live_runner, job.id, payload)
        else:
            background_tasks.add_task(_run_tail_live_selection_job, store, app.state.tail_live_runner, job.id, payload)

        return {"job_id": job.id}

    return app


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


def _run_fund_tail_advice_job(
    store: JobStore,
    paths: FundTailPaths,
    job_id: str,
    payload: FundTailAdviceRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(10, "running", "生成基金尾盘建议"))
    try:
        result = run_local_fund_tail_advice(paths, payload)
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc), progress=_progress(100, "failed", "任务失败"))
        return
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "建议生成完成"))


def _run_tail_live_selection_job(
    store: JobStore,
    runner,
    job_id: str,
    payload: TailLiveSelectionRequest,
) -> None:
    store.update_job(job_id, status="running", progress=_progress(5, "starting", "今日尾盘选股启动"))
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
    store.update_job(job_id, status="success", result=result, progress=_progress(100, "completed", "今日尾盘选股完成"))


def _progress(percent: int, stage: str, message: str) -> dict[str, Any]:
    return {"percent": percent, "stage": stage, "message": message}
