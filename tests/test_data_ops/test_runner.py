from __future__ import annotations

from datetime import datetime

from src.data_ops.models import DataOpsTaskConfig, DataOpsTaskStatus
from src.data_ops.runner import DataOpsRunner, DataOpsRunnerConfig, default_runner_loop_interval


class FakeRepository:
    def __init__(self, config: DataOpsTaskConfig | list[DataOpsTaskConfig]) -> None:
        self.configs = config if isinstance(config, list) else [config]
        self.statuses = [
            DataOpsTaskStatus(
                task_key=item.task_key,
                enabled=item.enabled,
                status="idle",
                schedule_kind=item.schedule_kind,
                schedule_config=item.schedule_config,
            )
            for item in self.configs
        ]
        self.ensure_called = False
        self.seed_called = False
        self.started: list[str] = []
        self.finished: list[tuple[str, str, dict, str]] = []
        self.heartbeats: list[tuple[str, str, str, str]] = []
        self.consumed: list[str] = []

    def ensure_tables(self):
        self.ensure_called = True

    def seed_default_configs(self):
        self.seed_called = True

    def list_task_configs(self):
        return self.configs

    def list_task_statuses(self, now=None):
        return self.statuses

    def start_run(self, task_key, runner_id, now=None):
        self.started.append(task_key)
        return "run-1"

    def finish_run(self, run_id, status, result, error, now=None):
        self.finished.append((run_id, status, result, error))

    def write_heartbeat(self, runner_id, task_key, status, message, now=None):
        self.heartbeats.append((runner_id, task_key, status, message))

    def consume_manual_trigger(self, task_key, now=None):
        self.consumed.append(task_key)
        return True


def test_runner_executes_due_task_once() -> None:
    repo = FakeRepository(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 0},
        )
    )
    runner = DataOpsRunner(
        repository=repo,
        handlers={"quality_snapshot": lambda params: {"rows": 3}},
        config=DataOpsRunnerConfig(runner_id="runner-a", once=True),
        clock=lambda: datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: True,
    )

    result = runner.run_once()

    assert repo.ensure_called is True
    assert repo.seed_called is True
    assert repo.started == ["quality_snapshot"]
    assert repo.finished == [("run-1", "success", {"rows": 3}, "")]
    assert result["executed"] == 1


def test_runner_records_failed_task() -> None:
    repo = FakeRepository(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 0},
        )
    )

    def fail(_params):
        raise RuntimeError("boom")

    runner = DataOpsRunner(
        repository=repo,
        handlers={"quality_snapshot": fail},
        config=DataOpsRunnerConfig(runner_id="runner-a", once=True),
        clock=lambda: datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: True,
    )

    result = runner.run_once()

    assert repo.finished == [("run-1", "failed", {}, "boom")]
    assert result["failed"] == 1


def test_runner_consumes_manual_trigger_after_execution() -> None:
    repo = FakeRepository(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=False,
            schedule_kind="manual",
            schedule_config={},
            manual_trigger=True,
        )
    )
    runner = DataOpsRunner(
        repository=repo,
        handlers={"quality_snapshot": lambda params: {"rows": 1}},
        config=DataOpsRunnerConfig(runner_id="runner-a", once=True),
        clock=lambda: datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: False,
    )

    runner.run_once()

    assert repo.consumed == ["quality_snapshot"]


def test_runner_progress_callback_writes_heartbeat_updates() -> None:
    repo = FakeRepository(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 0},
        )
    )

    def handler(params):
        params["progress"](40, "fetching", "读取数据", processed=4, total=10)
        return {"rows": 1}

    runner = DataOpsRunner(
        repository=repo,
        handlers={"quality_snapshot": handler},
        config=DataOpsRunnerConfig(runner_id="runner-a", once=True),
        clock=lambda: datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: True,
    )

    runner.run_once()

    assert any('"percent":40' in heartbeat[3] for heartbeat in repo.heartbeats)
    assert any('"message":"读取数据"' in heartbeat[3] for heartbeat in repo.heartbeats)


def test_realtime_runner_only_executes_realtime_task_group() -> None:
    repo = FakeRepository([
        DataOpsTaskConfig(
            task_key="minute5_intraday_sync",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 0},
        ),
        DataOpsTaskConfig(
            task_key="quote_snapshot_capture",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 0},
        ),
        DataOpsTaskConfig(
            task_key="quote_rollup_refresh",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 0},
        ),
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 0},
        ),
    ])
    runner = DataOpsRunner(
        repository=repo,
        handlers={
            "minute5_intraday_sync": lambda params: {"minute5": True},
            "quote_snapshot_capture": lambda params: {"snapshot": True},
            "quote_rollup_refresh": lambda params: {"rollup": True},
            "quality_snapshot": lambda params: {"quality": True},
        },
        config=DataOpsRunnerConfig(runner_id="runner-realtime", once=True, task_group="realtime"),
        clock=lambda: datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: True,
    )

    result = runner.run_once()

    assert repo.started == ["quote_snapshot_capture", "quote_rollup_refresh"]
    assert result == {"executed": 2, "failed": 0, "skipped": 0}


def test_task_key_filter_still_applies_inside_task_group() -> None:
    repo = FakeRepository([
        DataOpsTaskConfig(
            task_key="quote_snapshot_capture",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 0},
        ),
        DataOpsTaskConfig(
            task_key="quote_rollup_refresh",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={"interval_seconds": 0},
        ),
    ])
    runner = DataOpsRunner(
        repository=repo,
        handlers={
            "quote_snapshot_capture": lambda params: {"snapshot": True},
            "quote_rollup_refresh": lambda params: {"rollup": True},
        },
        config=DataOpsRunnerConfig(
            runner_id="runner-realtime",
            once=True,
            task_key="quote_snapshot_capture",
            task_group="realtime",
        ),
        clock=lambda: datetime(2026, 6, 12, 10, 0),
        is_trading_day=lambda value: True,
    )

    runner.run_once()

    assert repo.started == ["quote_snapshot_capture"]


def test_realtime_runner_default_loop_interval_supports_ten_second_tasks() -> None:
    assert default_runner_loop_interval("realtime") == 1
    assert default_runner_loop_interval("intraday") == 30
    assert default_runner_loop_interval("maintenance") == 30
    assert default_runner_loop_interval(None) == 30
