"""Standalone data operations runner."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Callable

from src.data_ops.config import load_data_ops_config
from src.data_ops.handlers import TaskHandler, build_default_handlers
from src.data_ops.models import encode_progress_message
from src.data_ops.repository import ClickHouseDataOpsRepository
from src.data_ops.scheduler import should_run_task
from src.trading.scheduler import TradingScheduler

TASK_GROUPS: dict[str, set[str]] = {
    "realtime": {"quote_snapshot_capture", "quote_rollup_refresh"},
    "intraday": {"minute5_intraday_sync"},
    "maintenance": {"stock_master_sync", "quality_snapshot", "post_close_maintenance"},
}


def default_runner_loop_interval(task_group: str | None) -> int:
    return 1 if task_group == "realtime" else 30


@dataclass(frozen=True)
class DataOpsRunnerConfig:
    runner_id: str
    once: bool = False
    interval_seconds: int = 30
    task_key: str | None = None
    task_group: str | None = None
    log_dir: str = "logs"


class DataOpsRunner:
    def __init__(
        self,
        *,
        repository: Any,
        handlers: dict[str, TaskHandler],
        config: DataOpsRunnerConfig,
        clock: Callable[[], datetime] | None = None,
        is_trading_day: Callable[[Any], bool] | None = None,
    ) -> None:
        self.repository = repository
        self.handlers = handlers
        self.config = config
        self.clock = clock or datetime.now
        self.is_trading_day = is_trading_day or TradingScheduler().is_trading_day

    def run_once(self) -> dict[str, int]:
        self.repository.ensure_tables()
        self.repository.seed_default_configs()
        now = self.clock()
        statuses = {status.task_key: status for status in self.repository.list_task_statuses(now=now)}
        executed = 0
        failed = 0
        skipped = 0
        for task_config in self.repository.list_task_configs():
            if not self._matches_task_group(task_config.task_key):
                continue
            if self.config.task_key and task_config.task_key != self.config.task_key:
                continue
            decision = should_run_task(
                task_config,
                statuses.get(task_config.task_key),
                now,
                is_trading_day=self.is_trading_day,
            )
            if not decision.run:
                skipped += 1
                continue
            handler = self.handlers.get(task_config.task_key)
            if handler is None:
                skipped += 1
                continue
            run_id = self.repository.start_run(task_config.task_key, self.config.runner_id, now=now)
            self.repository.write_heartbeat(
                self.config.runner_id,
                task_config.task_key,
                "running",
                encode_progress_message(percent=1, stage="started", message="任务已开始"),
                now=now,
            )
            try:
                params = dict(task_config.schedule_config)
                params["progress"] = self._progress_callback(task_config.task_key)
                result = handler(params)
            except Exception as exc:  # noqa: BLE001 - failures must be recorded and runner continues.
                failed += 1
                self.repository.finish_run(run_id, "failed", {}, str(exc), now=self.clock())
                self.repository.write_heartbeat(
                    self.config.runner_id,
                    task_config.task_key,
                    "failed",
                    encode_progress_message(percent=100, stage="failed", message=str(exc)),
                    now=self.clock(),
                )
            else:
                executed += 1
                self.repository.finish_run(run_id, "success", result, "", now=self.clock())
                self.repository.write_heartbeat(
                    self.config.runner_id,
                    task_config.task_key,
                    "success",
                    encode_progress_message(percent=100, stage="completed", message="任务完成"),
                    now=self.clock(),
                )
            if task_config.manual_trigger:
                self.repository.consume_manual_trigger(task_config.task_key, now=self.clock())
        return {"executed": executed, "failed": failed, "skipped": skipped}

    def _matches_task_group(self, task_key: str) -> bool:
        if not self.config.task_group:
            return True
        return task_key in TASK_GROUPS[self.config.task_group]

    def _progress_callback(self, task_key: str) -> Callable[..., None]:
        def report(percent: int, stage: str, message: str, *, processed: int | None = None, total: int | None = None) -> None:
            self.repository.write_heartbeat(
                self.config.runner_id,
                task_key,
                "running",
                encode_progress_message(
                    percent=percent,
                    stage=stage,
                    message=message,
                    processed=processed,
                    total=total,
                ),
                now=self.clock(),
            )

        return report

    def run_forever(self) -> None:
        while True:
            result = self.run_once()
            logging.info("data ops cycle completed: %s", result)
            sleep(self.config.interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run standalone data operations tasks.")
    parser.add_argument("--once", action="store_true", help="Run one scheduler cycle and exit")
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--runner-id", default=None)
    parser.add_argument("--task-key", default=None)
    parser.add_argument("--task-group", choices=sorted(TASK_GROUPS), default=None)
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args(argv)

    runtime = load_data_ops_config(config_path=args.config_path)
    log_dir = args.log_dir or runtime.log_dir
    _configure_logging(log_dir)
    repository = ClickHouseDataOpsRepository(
        host=runtime.clickhouse_host,
        user=runtime.clickhouse_user,
        password=runtime.clickhouse_password,
        database=runtime.clickhouse_database,
    )
    runner = DataOpsRunner(
        repository=repository,
        handlers=build_default_handlers(),
        config=DataOpsRunnerConfig(
            runner_id=args.runner_id or runtime.runner_id,
            once=args.once,
            interval_seconds=args.interval_seconds
            if args.interval_seconds is not None
            else default_runner_loop_interval(args.task_group),
            task_key=args.task_key,
            task_group=args.task_group,
            log_dir=log_dir,
        ),
    )
    try:
        if args.once:
            logging.info("data ops one-shot result: %s", runner.run_once())
        else:
            runner.run_forever()
    except Exception:
        logging.exception("data ops runner failed")
        return 1
    return 0


def _configure_logging(log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(log_dir) / "data_ops_runner.log", encoding="utf-8"),
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
