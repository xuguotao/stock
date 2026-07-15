"""Tests for retired xdxr_sync task configuration."""
from __future__ import annotations

from src.data_ops.models import default_task_configs


def test_xdxr_sync_is_not_in_default_configs():
    """xdxr_sync should not be scheduled by data_ops by default."""
    configs = default_task_configs()
    task_keys = [c.task_key for c in configs]
    assert "xdxr_sync" not in task_keys
