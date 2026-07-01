from __future__ import annotations

from datetime import datetime, timedelta

from src.data_ops.models import DataOpsTaskConfig, DataOpsTaskStatus
from src.data_ops.scheduler import should_run_task


def test_intraday_task_skips_on_non_trading_day() -> None:
    config = DataOpsTaskConfig(
        task_key="minute5_intraday_sync",
        enabled=True,
        schedule_kind="market_interval",
        schedule_config={"interval_seconds": 60},
    )

    decision = should_run_task(
        config,
        DataOpsTaskStatus(task_key=config.task_key, enabled=True, status="idle"),
        datetime(2026, 6, 13, 10, 0),
        is_trading_day=lambda value: False,
    )

    assert decision.run is False
    assert decision.skip_reason == "non_trading_day"


def test_intraday_task_runs_during_market_window() -> None:
    config = DataOpsTaskConfig(
        task_key="quote_snapshot_capture",
        enabled=True,
        schedule_kind="market_interval",
        schedule_config={"interval_seconds": 10},
    )

    decision = should_run_task(
        config,
        DataOpsTaskStatus(task_key=config.task_key, enabled=True, status="idle"),
        datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: True,
    )

    assert decision.run is True


def test_daily_time_task_runs_after_configured_time() -> None:
    config = DataOpsTaskConfig(
        task_key="post_close_maintenance",
        enabled=True,
        schedule_kind="daily_time",
        schedule_config={"time": "15:10"},
    )

    decision = should_run_task(
        config,
        DataOpsTaskStatus(task_key=config.task_key, enabled=True, status="idle"),
        datetime(2026, 6, 12, 15, 11),
        is_trading_day=lambda value: True,
    )

    assert decision.run is True


def test_manual_trigger_runs_outside_window() -> None:
    config = DataOpsTaskConfig(
        task_key="quality_snapshot",
        enabled=False,
        schedule_kind="interval",
        schedule_config={"interval_seconds": 300},
        manual_trigger=True,
    )

    decision = should_run_task(
        config,
        DataOpsTaskStatus(task_key=config.task_key, enabled=False, status="disabled"),
        datetime(2026, 6, 13, 8, 0),
        is_trading_day=lambda value: False,
    )

    assert decision.run is True
    assert decision.skip_reason is None


def test_interval_task_skips_until_interval_elapsed() -> None:
    now = datetime(2026, 6, 12, 10, 0)
    config = DataOpsTaskConfig(
        task_key="quality_snapshot",
        enabled=True,
        schedule_kind="interval",
        schedule_config={"interval_seconds": 300},
    )
    status = DataOpsTaskStatus(
        task_key=config.task_key,
        enabled=True,
        status="success",
        last_finished_at=now - timedelta(seconds=60),
    )

    decision = should_run_task(config, status, now, is_trading_day=lambda value: True)

    assert decision.run is False
    assert decision.skip_reason == "interval_not_elapsed"


def test_interval_task_uses_last_started_for_cadence() -> None:
    now = datetime(2026, 6, 12, 10, 0, 8)
    started = datetime(2026, 6, 12, 10, 0)
    finished = datetime(2026, 6, 12, 10, 0, 5)
    config = DataOpsTaskConfig(
        task_key="quote_snapshot_capture",
        enabled=True,
        schedule_kind="market_interval",
        schedule_config={"interval_seconds": 10},
    )
    status = DataOpsTaskStatus(
        task_key=config.task_key,
        enabled=True,
        status="success",
        last_started_at=started,
        last_finished_at=finished,
    )

    decision = should_run_task(config, status, now, is_trading_day=lambda value: True)

    assert decision.run is False
    assert decision.next_run_at == started + timedelta(seconds=10)

    due = should_run_task(config, status, started + timedelta(seconds=10), is_trading_day=lambda value: True)

    assert due.run is True
