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
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into jobs (id, kind, status, params, result, error, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.kind,
                    job.status,
                    json.dumps(job.params, ensure_ascii=False),
                    None,
                    None,
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
    ) -> JobRecord:
        updated_at = _now()
        with self._connect() as conn:
            conn.execute(
                """
                update jobs
                set status = ?, result = ?, error = ?, updated_at = ?
                where id = ?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                    updated_at,
                    job_id,
                ),
            )
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

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
                    created_at text not null,
                    updated_at text not null
                )
                """
            )

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
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
