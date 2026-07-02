"""ClickHouse repository for data operations task state."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data_ops.models import (
    DataOpsTaskConfig,
    DataOpsTaskStatus,
    decode_progress_message,
    default_task_configs,
    parse_schedule_config,
)


class ClickHouseDataOpsRepository:
    def __init__(
        self,
        *,
        client: Any | None = None,
        host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        self._source = None if client is not None else ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
        self._client = client
        self._started_runs: dict[str, dict[str, Any]] = {}

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._source._client_instance()
        return self._client

    def _execute(self, query: str, params: Any = None):
        try:
            return self.client.execute(query, params)
        except OSError:
            if self._source is None:
                raise
            self._client = self._source._client_instance()
            return self.client.execute(query, params)

    def ensure_tables(self) -> None:
        self._execute(
            """
            create table if not exists data_ops_task_config (
                task_key String,
                enabled UInt8,
                schedule_kind LowCardinality(String),
                schedule_config String,
                max_runtime_seconds UInt32,
                stale_after_seconds UInt32,
                manual_trigger UInt8,
                manual_triggered_at Nullable(DateTime),
                updated_at DateTime
            )
            engine = ReplacingMergeTree(updated_at)
            order by task_key
            """
        )
        self._execute(
            """
            create table if not exists data_ops_task_runs (
                run_id String,
                task_key String,
                status LowCardinality(String),
                started_at DateTime,
                finished_at Nullable(DateTime),
                duration_seconds Float64,
                result String,
                error String
            )
            engine = MergeTree
            partition by toYYYYMM(started_at)
            order by (task_key, started_at, run_id)
            """
        )
        self._execute(
            """
            create table if not exists data_ops_task_heartbeats (
                runner_id String,
                task_key String,
                heartbeat_at DateTime,
                status LowCardinality(String),
                message String
            )
            engine = ReplacingMergeTree(heartbeat_at)
            order by (runner_id, task_key)
            """
        )

    def seed_default_configs(self, *, now: datetime | None = None) -> None:
        existing = {config.task_key for config in self.list_task_configs()}
        for config in default_task_configs():
            if config.task_key not in existing:
                self.upsert_task_config(config, now=now)

    def list_task_configs(self) -> list[DataOpsTaskConfig]:
        if hasattr(self.client, "configs"):
            return [_config_from_dict(row) for row in self.client.configs.values()]
        rows = self._execute(
            """
            select task_key, enabled, schedule_kind, schedule_config, max_runtime_seconds,
                   stale_after_seconds, manual_trigger, manual_triggered_at, updated_at
            from data_ops_task_config final
            order by task_key
            """
        )
        return [
            DataOpsTaskConfig(
                task_key=str(row[0]),
                enabled=bool(row[1]),
                schedule_kind=str(row[2]),
                schedule_config=parse_schedule_config(row[3]),
                max_runtime_seconds=int(row[4]),
                stale_after_seconds=int(row[5]),
                manual_trigger=bool(row[6]),
                manual_triggered_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    def upsert_task_config(self, config: DataOpsTaskConfig, *, now: datetime | None = None) -> None:
        updated_at = now or datetime.now()
        row = {
            "task_key": config.task_key,
            "enabled": config.enabled,
            "schedule_kind": config.schedule_kind,
            "schedule_config": config.schedule_config_json,
            "max_runtime_seconds": config.max_runtime_seconds,
            "stale_after_seconds": config.stale_after_seconds,
            "manual_trigger": config.manual_trigger,
            "manual_triggered_at": config.manual_triggered_at,
            "updated_at": updated_at,
        }
        if hasattr(self.client, "configs"):
            self.client.configs[config.task_key] = row
            return
        self._execute(
            """
            insert into data_ops_task_config
            (task_key, enabled, schedule_kind, schedule_config, max_runtime_seconds,
             stale_after_seconds, manual_trigger, manual_triggered_at, updated_at)
            values
            """,
            [(
                row["task_key"],
                int(row["enabled"]),
                row["schedule_kind"],
                row["schedule_config"],
                int(row["max_runtime_seconds"]),
                int(row["stale_after_seconds"]),
                int(row["manual_trigger"]),
                row["manual_triggered_at"],
                row["updated_at"],
            )],
        )

    def request_manual_run(self, task_key: str, *, now: datetime | None = None) -> None:
        config = self._get_config(task_key)
        self.upsert_task_config(
            DataOpsTaskConfig(
                task_key=config.task_key,
                enabled=config.enabled,
                schedule_kind=config.schedule_kind,
                schedule_config=config.schedule_config,
                max_runtime_seconds=config.max_runtime_seconds,
                stale_after_seconds=config.stale_after_seconds,
                manual_trigger=True,
                manual_triggered_at=now or datetime.now(),
            ),
            now=now,
        )

    def consume_manual_trigger(self, task_key: str, *, now: datetime | None = None) -> bool:
        config = self._get_config(task_key)
        if not config.manual_trigger:
            return False
        self.upsert_task_config(
            DataOpsTaskConfig(
                task_key=config.task_key,
                enabled=config.enabled,
                schedule_kind=config.schedule_kind,
                schedule_config=config.schedule_config,
                max_runtime_seconds=config.max_runtime_seconds,
                stale_after_seconds=config.stale_after_seconds,
                manual_trigger=False,
                manual_triggered_at=None,
            ),
            now=now,
        )
        return True

    def start_run(self, task_key: str, runner_id: str, *, now: datetime | None = None) -> str:
        run_id = uuid.uuid4().hex
        started_at = now or datetime.now()
        row = {
            "run_id": run_id,
            "task_key": task_key,
            "status": "running",
            "started_at": started_at,
            "finished_at": None,
            "duration_seconds": 0.0,
            "result": "{}",
            "error": "",
        }
        if hasattr(self.client, "runs"):
            self.client.runs[run_id] = row
            return run_id
        self._started_runs[run_id] = row
        self._execute(
            """
            insert into data_ops_task_runs
            (run_id, task_key, status, started_at, finished_at, duration_seconds, result, error)
            values
            """,
            [tuple(row.values())],
        )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any],
        error: str,
        *,
        now: datetime | None = None,
    ) -> None:
        finished_at = now or datetime.now()
        if hasattr(self.client, "runs"):
            row = self.client.runs[run_id]
            row["status"] = status
            row["finished_at"] = finished_at
            row["duration_seconds"] = (finished_at - row["started_at"]).total_seconds()
            row["result"] = result
            row["error"] = error
            return
        # ClickHouse rows are append-only for run completion.
        running = self._run_row(run_id)
        started_at = running.get("started_at") or finished_at
        self._execute(
            """
            insert into data_ops_task_runs
            (run_id, task_key, status, started_at, finished_at, duration_seconds, result, error)
            values
            """,
            [(
                run_id,
                running.get("task_key", ""),
                status,
                started_at,
                finished_at,
                (finished_at - started_at).total_seconds(),
                json.dumps(result, ensure_ascii=False, default=str),
                error,
            )],
        )

    def write_heartbeat(
        self,
        runner_id: str,
        task_key: str,
        status: str,
        message: str,
        *,
        now: datetime | None = None,
    ) -> None:
        heartbeat_at = now or datetime.now()
        row = {
            "runner_id": runner_id,
            "task_key": task_key,
            "heartbeat_at": heartbeat_at,
            "status": status,
            "message": message,
        }
        if hasattr(self.client, "heartbeats"):
            self.client.heartbeats[(runner_id, task_key)] = row
            return
        self._execute(
            """
            insert into data_ops_task_heartbeats
            (runner_id, task_key, heartbeat_at, status, message)
            values
            """,
            [(runner_id, task_key, heartbeat_at, status, message)],
        )

    def list_task_statuses(self, *, now: datetime | None = None) -> list[DataOpsTaskStatus]:
        current = now or datetime.now()
        statuses = []
        for config in self.list_task_configs():
            latest_run = self._latest_run(config.task_key)
            heartbeat = self._latest_heartbeat(config.task_key)
            status = "disabled" if not config.enabled else "idle"
            if latest_run:
                status = str(latest_run["status"])
            heartbeat_at = heartbeat.get("heartbeat_at") if heartbeat else None
            heartbeat_status = str(heartbeat.get("status") or "") if heartbeat else ""
            if heartbeat_status == "running":
                status = "running"
            if (
                status == "running"
                and heartbeat_at
                and (current - heartbeat_at).total_seconds() > config.stale_after_seconds
            ):
                status = "stale"
            progress = decode_progress_message(heartbeat.get("message") if heartbeat else None)
            latest_error = str(latest_run.get("error") or "") if latest_run else ""
            latest_result = _decode_result(latest_run.get("result")) if latest_run else None
            if status == "running" and heartbeat_status == "running":
                latest_error = ""
                latest_result = {}
            statuses.append(
                DataOpsTaskStatus(
                    task_key=config.task_key,
                    enabled=config.enabled,
                    status=status,
                    schedule_kind=config.schedule_kind,
                    schedule_config=config.schedule_config,
                    last_started_at=latest_run.get("started_at") if latest_run else None,
                    last_finished_at=latest_run.get("finished_at") if latest_run else None,
                    last_result=latest_result,
                    last_error=latest_error,
                    heartbeat_at=heartbeat_at,
                    runner_id=heartbeat.get("runner_id") if heartbeat else None,
                    progress_percent=_int_or_none(progress.get("percent")),
                    progress_stage=str(progress.get("stage")) if progress.get("stage") is not None else None,
                    progress_message=str(progress.get("message")) if progress.get("message") is not None else None,
                    progress_processed=_int_or_none(progress.get("processed")),
                    progress_total=_int_or_none(progress.get("total")),
                )
            )
        return statuses

    def _get_config(self, task_key: str) -> DataOpsTaskConfig:
        for config in self.list_task_configs():
            if config.task_key == task_key:
                return config
        raise KeyError(task_key)

    def _latest_fake_run(self, task_key: str) -> dict[str, Any] | None:
        if not hasattr(self.client, "runs"):
            return None
        rows = [row for row in self.client.runs.values() if row["task_key"] == task_key]
        return max(rows, key=lambda row: row["started_at"]) if rows else None

    def _latest_fake_heartbeat(self, task_key: str) -> dict[str, Any] | None:
        if not hasattr(self.client, "heartbeats"):
            return None
        rows = [row for (_runner, key), row in self.client.heartbeats.items() if key == task_key]
        return max(rows, key=lambda row: row["heartbeat_at"]) if rows else None

    def _latest_run(self, task_key: str) -> dict[str, Any] | None:
        if hasattr(self.client, "runs"):
            return self._latest_fake_run(task_key)
        rows = self._execute(
            """
            select run_id, task_key, status, started_at, finished_at, duration_seconds, result, error
            from data_ops_task_runs
            where task_key = %(task_key)s
            order by started_at desc, isNull(finished_at) asc, finished_at desc
            limit 1
            """,
            {"task_key": task_key},
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "run_id": row[0],
            "task_key": row[1],
            "status": row[2],
            "started_at": row[3],
            "finished_at": row[4],
            "duration_seconds": row[5],
            "result": row[6],
            "error": row[7],
        }

    def _latest_heartbeat(self, task_key: str) -> dict[str, Any] | None:
        if hasattr(self.client, "heartbeats"):
            return self._latest_fake_heartbeat(task_key)
        rows = self._execute(
            """
            select runner_id, task_key, heartbeat_at, status, message
            from data_ops_task_heartbeats final
            where task_key = %(task_key)s
            order by heartbeat_at desc
            limit 1
            """,
            {"task_key": task_key},
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "runner_id": row[0],
            "task_key": row[1],
            "heartbeat_at": row[2],
            "status": row[3],
            "message": row[4],
        }

    def _run_row(self, run_id: str) -> dict[str, Any]:
        if hasattr(self.client, "runs"):
            return self.client.runs[run_id]
        return self._started_runs.get(run_id, {})


def _config_from_dict(row: dict[str, Any]) -> DataOpsTaskConfig:
    return DataOpsTaskConfig(
        task_key=str(row["task_key"]),
        enabled=bool(row["enabled"]),
        schedule_kind=str(row["schedule_kind"]),
        schedule_config=parse_schedule_config(row["schedule_config"]),
        max_runtime_seconds=int(row["max_runtime_seconds"]),
        stale_after_seconds=int(row["stale_after_seconds"]),
        manual_trigger=bool(row["manual_trigger"]),
        manual_triggered_at=row.get("manual_triggered_at"),
        updated_at=row.get("updated_at"),
    )


def _decode_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {"raw": str(value)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
