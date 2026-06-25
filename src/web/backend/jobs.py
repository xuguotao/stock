"""SQLite-backed job metadata store."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JobRecord:
    """Serializable job metadata."""

    id: str
    kind: str
    status: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    progress: dict[str, Any]
    heartbeat_at: str | None
    health: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "params": self.params,
            "result": self.result,
            "error": self.error,
            "progress": self.progress,
            "heartbeat_at": self.heartbeat_at,
            "health": self.health,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    """Persist job state in SQLite."""

    def __init__(self, db_path: str | Path = "data/web/jobs.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_job(self, kind: str, params: dict[str, Any]) -> JobRecord:
        now = _now()
        job = JobRecord(
            id=str(uuid.uuid4()),
            kind=kind,
            status="pending",
            params=params,
            result=None,
            error=None,
            progress=_progress(0, "pending", "等待执行"),
            heartbeat_at=None,
            health="pending",
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into jobs (id, kind, status, params, result, error, progress, heartbeat_at, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.kind,
                    job.status,
                    json.dumps(job.params, ensure_ascii=False),
                    None,
                    None,
                    json.dumps(job.progress, ensure_ascii=False),
                    job.heartbeat_at,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from jobs order by created_at desc limit ?",
                (limit,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row is not None else None

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        progress: dict[str, Any] | None = None,
    ) -> JobRecord:
        updated_at = _now()
        heartbeat_at = updated_at if status == "running" else None
        with self._connect() as conn:
            conn.execute(
                """
                update jobs
                set status = ?,
                    result = ?,
                    error = ?,
                    progress = coalesce(?, progress),
                    heartbeat_at = coalesce(?, heartbeat_at),
                    updated_at = ?
                where id = ?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                    json.dumps(progress, ensure_ascii=False) if progress is not None else None,
                    heartbeat_at,
                    updated_at,
                    job_id,
                ),
            )
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def mark_running_jobs_interrupted(self, reason: str) -> int:
        """Mark jobs left running by a previous server process as failed."""
        updated_at = _now()
        progress = _progress(100, "interrupted", reason)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                update jobs
                set status = 'failed',
                    result = null,
                    error = ?,
                    progress = ?,
                    heartbeat_at = null,
                    updated_at = ?
                where status = 'running'
                """,
                (
                    reason,
                    json.dumps(progress, ensure_ascii=False),
                    updated_at,
                ),
            )
            return int(cursor.rowcount)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists jobs (
                    id text primary key,
                    kind text not null,
                    status text not null,
                    params text not null,
                    result text,
                    error text,
                    progress text,
                    heartbeat_at text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            columns = {row["name"] for row in conn.execute("pragma table_info(jobs)").fetchall()}
            if "progress" not in columns:
                conn.execute("alter table jobs add column progress text")
                conn.execute(
                    "update jobs set progress = ? where progress is null",
                    (json.dumps(_progress(0, "unknown", "历史任务未记录进度"), ensure_ascii=False),),
                )
            if "heartbeat_at" not in columns:
                conn.execute("alter table jobs add column heartbeat_at text")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            kind=row["kind"],
            status=row["status"],
            params=json.loads(row["params"]),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            progress=json.loads(row["progress"]) if row["progress"] else _progress(0, "unknown", "未记录进度"),
            heartbeat_at=row["heartbeat_at"] if "heartbeat_at" in row.keys() else None,
            health=_job_health(
                row["status"],
                row["heartbeat_at"] if "heartbeat_at" in row.keys() else None,
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _progress(percent: int, stage: str, message: str) -> dict[str, Any]:
    return {"percent": percent, "stage": stage, "message": message}


def _job_health(status: str, heartbeat_at: str | None, *, stale_after_seconds: int = 180) -> str:
    if status == "running":
        if not heartbeat_at:
            return "stale"
        try:
            heartbeat = datetime.fromisoformat(heartbeat_at)
        except ValueError:
            return "stale"
        if (datetime.now() - heartbeat).total_seconds() > stale_after_seconds:
            return "stale"
        return "running"
    if status == "pending":
        return "pending"
    if status == "success":
        return "completed"
    if status == "failed":
        return "failed"
    return status
