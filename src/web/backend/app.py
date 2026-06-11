"""FastAPI application factory for the dashboard backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.web.backend.backtests import TailBacktestRequest, run_tail_backtest
from src.web.backend.datasets import DatasetService
from src.web.backend.jobs import JobStore


class CreateJobRequest(BaseModel):
    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


def create_app(
    *,
    db_path: str | Path = "data/web/jobs.sqlite3",
    dataset_root: str | Path = "data/research",
    run_jobs_inline: bool = False,
) -> FastAPI:
    """Create a configured FastAPI app."""
    app = FastAPI(title="A-Share Quant Dashboard API")
    store = JobStore(db_path)
    datasets = DatasetService(dataset_root)
    app.state.job_store = store
    app.state.dataset_service = datasets
    app.state.run_jobs_inline = run_jobs_inline

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

    return app


app = create_app()


def _run_tail_backtest_job(store: JobStore, job_id: str, payload: TailBacktestRequest) -> None:
    store.update_job(job_id, status="running")
    try:
        result = run_tail_backtest(payload)
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc))
        return
    store.update_job(job_id, status="success", result=result)
