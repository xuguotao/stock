from __future__ import annotations

from src.data_ops.handlers import build_default_handlers
from src.data_ops.models import default_task_configs


def test_stock_readiness_snapshot_handler_is_registered() -> None:
    handlers = build_default_handlers(stock_readiness_snapshot_runner=lambda params: {"total": 0})

    assert "stock_readiness_snapshot" in handlers
    assert handlers["stock_readiness_snapshot"]({}) == {"total": 0}


def test_stock_readiness_repair_handler_is_registered() -> None:
    handlers = build_default_handlers(stock_readiness_repair_runner=lambda params: {"queued": 1})

    assert "stock_readiness_repair" in handlers
    assert handlers["stock_readiness_repair"]({"symbols": ["000001"]}) == {"queued": 1}


def test_stock_readiness_snapshot_default_config_exists() -> None:
    configs = {config.task_key: config for config in default_task_configs()}

    snapshot = configs["stock_readiness_snapshot"]
    assert snapshot.enabled is True
    assert snapshot.schedule_kind == "daily_time"
    assert snapshot.schedule_config == {
        "time": "15:40",
        "lookback_days": 180,
        "dimensions": ["daily", "minute5"],
    }
    assert snapshot.max_runtime_seconds >= 1800

    repair = configs["stock_readiness_repair"]
    assert repair.enabled is False
    assert repair.schedule_kind == "manual"
