"""Pure scheduling decisions for data operations tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable

from src.data_ops.models import DataOpsTaskConfig, DataOpsTaskStatus


@dataclass(frozen=True)
class DataOpsDecision:
    run: bool
    skip_reason: str | None = None
    next_run_at: datetime | None = None


def should_run_task(
    config: DataOpsTaskConfig,
    status: DataOpsTaskStatus | None,
    now: datetime,
    *,
    is_trading_day: Callable[[date], bool],
) -> DataOpsDecision:
    if config.manual_trigger:
        return DataOpsDecision(run=True)
    if not config.enabled:
        return DataOpsDecision(run=False, skip_reason="disabled")
    last_finished = status.last_finished_at if status is not None else None
    last_started = status.last_started_at if status is not None else None
    if config.schedule_kind == "market_interval":
        if not is_trading_day(now.date()):
            return DataOpsDecision(run=False, skip_reason="non_trading_day")
        if not _is_market_session(now.time()):
            return DataOpsDecision(run=False, skip_reason="outside_market_session")
        return _interval_decision(config, now, last_started or last_finished)
    if config.schedule_kind == "daily_time":
        if not is_trading_day(now.date()):
            return DataOpsDecision(run=False, skip_reason="non_trading_day")
        target = _parse_time(str(config.schedule_config.get("time", "15:10")))
        if now.time() < target:
            return DataOpsDecision(run=False, skip_reason="before_daily_time")
        if last_finished and last_finished.date() == now.date():
            return DataOpsDecision(run=False, skip_reason="already_ran_today")
        return DataOpsDecision(run=True)
    if config.schedule_kind == "interval":
        return _interval_decision(config, now, last_started or last_finished)
    if config.schedule_kind == "manual":
        return DataOpsDecision(run=False, skip_reason="manual_only")
    return DataOpsDecision(run=False, skip_reason=f"unknown_schedule_{config.schedule_kind}")


def next_run_at(
    config: DataOpsTaskConfig,
    now: datetime,
    *,
    is_trading_day: Callable[[date], bool],
) -> datetime | None:
    if not config.enabled:
        return None
    if config.schedule_kind in {"interval", "market_interval"}:
        return now + timedelta(seconds=_interval_seconds(config))
    if config.schedule_kind == "daily_time":
        target_time = _parse_time(str(config.schedule_config.get("time", "15:10")))
        candidate = datetime.combine(now.date(), target_time)
        if candidate > now and is_trading_day(now.date()):
            return candidate
        return datetime.combine(now.date() + timedelta(days=1), target_time)
    return None


def _interval_decision(config: DataOpsTaskConfig, now: datetime, last_run_at: datetime | None) -> DataOpsDecision:
    interval = _interval_seconds(config)
    if last_run_at and now - last_run_at < timedelta(seconds=interval):
        return DataOpsDecision(
            run=False,
            skip_reason="interval_not_elapsed",
            next_run_at=last_run_at + timedelta(seconds=interval),
        )
    return DataOpsDecision(run=True)


def _interval_seconds(config: DataOpsTaskConfig) -> int:
    return int(config.schedule_config.get("interval_seconds") or 60)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _is_market_session(value: time) -> bool:
    return time(9, 30) <= value <= time(11, 30) or time(13, 0) <= value <= time(15, 0)
