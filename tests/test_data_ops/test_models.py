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
        "stock_master_sync",
        "post_close_maintenance",
        "minute5_intraday_sync",
        "quote_snapshot_capture",
        "quote_rollup_refresh",
        "quality_snapshot",
        "stock_readiness_snapshot",
        "stock_readiness_repair",
        "mootdx_stock_catalog_sync",
        "mootdx_daily_kline_sync",
        "mootdx_daily_kline_reconcile",
        "stock_universe_profile_refresh",
    ]
    assert all(config.enabled for config in configs if config.task_key != "stock_readiness_repair")
    assert next(config for config in configs if config.task_key == "stock_readiness_repair").enabled is False
    quote_snapshot = next(config for config in configs if config.task_key == "quote_snapshot_capture")
    assert quote_snapshot.schedule_config["chunk_size"] == 500
    assert quote_snapshot.schedule_config["quote_endpoint"] == "sqt_utf8"
    mootdx_catalog = next(config for config in configs if config.task_key == "mootdx_stock_catalog_sync")
    mootdx_daily = next(config for config in configs if config.task_key == "mootdx_daily_kline_sync")
    mootdx_reconcile = next(config for config in configs if config.task_key == "mootdx_daily_kline_reconcile")
    assert mootdx_catalog.schedule_config == {"time": "08:30", "rate_limit": 0.02, "timeout": 15, "bestip": False}
    assert mootdx_daily.schedule_config == {"time": "15:35", "rate_limit": 0.02, "timeout": 15, "bestip": False}
    assert mootdx_reconcile.schedule_config == {"time": "16:05", "rate_limit": 0.02, "timeout": 15, "bestip": False}
    universe_profile = next(config for config in configs if config.task_key == "stock_universe_profile_refresh")
    assert universe_profile.schedule_config["time"] == "16:15"
    assert universe_profile.schedule_config["min_average_amount"] == 10_000_000


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
