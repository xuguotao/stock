"""Tests for xdxr_sync task configuration."""
from __future__ import annotations

from src.data_ops.models import default_task_configs


def test_xdxr_sync_in_default_configs():
    """xdxr_sync should be in default task configs."""
    configs = default_task_configs()
    task_keys = [c.task_key for c in configs]
    assert "xdxr_sync" in task_keys, f"xdxr_sync not found in: {task_keys}"


def test_xdxr_sync_schedule():
    """xdxr_sync should be scheduled daily at 15:30."""
    configs = default_task_configs()
    xdxr_config = next(c for c in configs if c.task_key == "xdxr_sync")
    assert xdxr_config.schedule_kind == "daily_time"
    assert xdxr_config.schedule_config["time"] == "15:30"
    assert xdxr_config.enabled is True
