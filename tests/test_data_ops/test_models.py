from __future__ import annotations

import json

import pytest

from src.data_ops.models import (
    VALID_TASK_STATUSES,
    DataOpsTaskConfig,
    DataOpsTaskStatus,
    default_task_configs,
    parse_schedule_config,
    serialize_schedule_config,
)


def test_default_task_configs_cover_first_runner_tasks() -> None:
    configs = default_task_configs()

    assert [config.task_key for config in configs] == [
        "post_close_maintenance",
        "minute5_intraday_sync",
        "quote_snapshot_capture",
        "quote_rollup_refresh",
        "quality_snapshot",
    ]
    assert all(config.enabled for config in configs)


def test_schedule_config_serializes_stably() -> None:
    payload = {"interval_seconds": 60, "window": {"start": "09:30", "end": "15:00"}}

    encoded = serialize_schedule_config(payload)

    assert encoded == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert parse_schedule_config(encoded) == payload


def test_rejects_invalid_task_status() -> None:
    assert "running" in VALID_TASK_STATUSES

    with pytest.raises(ValueError, match="invalid data ops task status"):
        DataOpsTaskStatus(task_key="x", enabled=True, status="unknown")


def test_task_config_round_trips_schedule_config() -> None:
    config = DataOpsTaskConfig(
        task_key="quote_snapshot_capture",
        enabled=True,
        schedule_kind="interval",
        schedule_config={"interval_seconds": 10},
    )

    assert config.schedule_config_json == '{"interval_seconds":10}'
