"""File-backed job metadata store."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
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
    """Persist job state in a local JSON file."""

    def __init__(self, db_path: str | Path = "data/web/jobs.json") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        if not self.db_path.exists():
            self._write_rows([])

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
        with self._lock:
            rows = self._read_rows()
            rows.append(_job_to_row(job))
            self._write_rows(rows)
        return job

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        with self._lock:
            rows = self._read_rows()
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [self._row_to_job(row) for row in rows[:limit]]

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            rows = self._read_rows()
        for row in rows:
            if row.get("id") == job_id:
                return self._row_to_job(row)
        return None

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
        with self._lock:
            rows = self._read_rows()
            for row in rows:
                if row.get("id") != job_id:
                    continue
                row["status"] = status
                row["result"] = result
                row["error"] = error
                if progress is not None:
                    row["progress"] = progress
                if heartbeat_at is not None:
                    row["heartbeat_at"] = heartbeat_at
                row["updated_at"] = updated_at
                self._write_rows(rows)
                return self._row_to_job(row)
        raise KeyError(job_id)

    def mark_running_jobs_interrupted(self, reason: str) -> int:
        """Mark jobs left running by a previous server process as failed."""
        updated_at = _now()
        progress = _progress(100, "interrupted", reason)
        marked = 0
        with self._lock:
            rows = self._read_rows()
            for row in rows:
                if row.get("status") != "running":
                    continue
                row["status"] = "failed"
                row["result"] = None
                row["error"] = reason
                row["progress"] = progress
                row["heartbeat_at"] = None
                row["updated_at"] = updated_at
                marked += 1
            if marked:
                self._write_rows(rows)
        return marked

    def _read_rows(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.db_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        tmp_path = self.db_path.with_suffix(self.db_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.db_path)

    def _row_to_job(self, row: dict[str, Any]) -> JobRecord:
        status = str(row.get("status") or "")
        heartbeat_at = row.get("heartbeat_at")
        return JobRecord(
            id=str(row.get("id") or ""),
            kind=str(row.get("kind") or ""),
            status=status,
            params=dict(row.get("params") or {}),
            result=row.get("result") if isinstance(row.get("result"), dict) else None,
            error=str(row["error"]) if row.get("error") is not None else None,
            progress=dict(row.get("progress") or _progress(0, "unknown", "未记录进度")),
            heartbeat_at=str(heartbeat_at) if heartbeat_at else None,
            health=_job_health(status, str(heartbeat_at) if heartbeat_at else None),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


def _job_to_row(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "params": job.params,
        "result": job.result,
        "error": job.error,
        "progress": job.progress,
        "heartbeat_at": job.heartbeat_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


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
