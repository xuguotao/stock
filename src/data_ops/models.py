"""Models for independent data update tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

VALID_TASK_STATUSES = {"disabled", "idle", "running", "success", "failed", "stale", "skipped"}


def serialize_schedule_config(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_schedule_config(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("schedule_config must decode to an object")
    return parsed


@dataclass(frozen=True)
class DataOpsTaskConfig:
    task_key: str
    enabled: bool
    schedule_kind: str
    schedule_config: dict[str, Any] = field(default_factory=dict)
    max_runtime_seconds: int = 1800
    stale_after_seconds: int = 300
    manual_trigger: bool = False
    manual_triggered_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def schedule_config_json(self) -> str:
        return serialize_schedule_config(self.schedule_config)


@dataclass(frozen=True)
class DataOpsTaskRun:
    run_id: str
    task_key: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    result: dict[str, Any] | None = None
    error: str = ""

    def __post_init__(self) -> None:
        _validate_status(self.status)


@dataclass(frozen=True)
class DataOpsTaskStatus:
    task_key: str
    enabled: bool
    status: str
    schedule_kind: str = ""
    schedule_config: dict[str, Any] = field(default_factory=dict)
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    next_run_at: datetime | None = None
    last_result: dict[str, Any] | None = None
    last_error: str = ""
    heartbeat_at: datetime | None = None
    runner_id: str | None = None
    progress_percent: int | None = None
    progress_stage: str | None = None
    progress_message: str | None = None
    progress_processed: int | None = None
    progress_total: int | None = None

    def __post_init__(self) -> None:
        _validate_status(self.status)


def default_task_configs() -> list[DataOpsTaskConfig]:
    return [
        DataOpsTaskConfig(
            task_key="stock_master_sync",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "08:30"},
            max_runtime_seconds=600,
            stale_after_seconds=900,
        ),
        DataOpsTaskConfig(
            task_key="post_close_maintenance",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "15:10"},
            max_runtime_seconds=7200,
            stale_after_seconds=900,
        ),
        DataOpsTaskConfig(
            task_key="minute5_intraday_sync",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 60},
            max_runtime_seconds=300,
            stale_after_seconds=180,
        ),
        DataOpsTaskConfig(
            task_key="quote_snapshot_capture",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 10, "chunk_size": 500, "quote_endpoint": "sqt_utf8"},
            max_runtime_seconds=60,
            stale_after_seconds=60,
        ),
        DataOpsTaskConfig(
            task_key="quote_rollup_refresh",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 60},
            max_runtime_seconds=300,
            stale_after_seconds=180,
        ),
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 300},
            max_runtime_seconds=300,
            stale_after_seconds=180,
        ),
        DataOpsTaskConfig(
            task_key="xdxr_sync",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "15:30"},
            max_runtime_seconds=1800,
            stale_after_seconds=900,
        ),
        DataOpsTaskConfig(
            task_key="stock_readiness_snapshot",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={
                "time": "15:40",
                "lookback_days": 180,
                "dimensions": ["daily", "minute5"],
            },
            max_runtime_seconds=3600,
            stale_after_seconds=900,
        ),
        DataOpsTaskConfig(
            task_key="stock_readiness_repair",
            enabled=False,
            schedule_kind="manual",
            schedule_config={},
            max_runtime_seconds=3600,
            stale_after_seconds=900,
        ),
    ]


def _validate_status(status: str) -> None:
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"invalid data ops task status: {status}")


def encode_progress_message(
    *,
    percent: int,
    stage: str,
    message: str,
    processed: int | None = None,
    total: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "percent": int(percent),
        "stage": stage,
        "message": message,
    }
    if processed is not None:
        payload["processed"] = int(processed)
    if total is not None:
        payload["total"] = int(total)
    return serialize_schedule_config(payload)


def decode_progress_message(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {"message": value}
    return payload if isinstance(payload, dict) else {"message": str(value)}
