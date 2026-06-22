"""Automatic data operations scheduler for dashboard health and repair jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from threading import Event, Lock, Thread
from time import sleep
from typing import Any, Callable

from src.trading.scheduler import TradingScheduler


@dataclass(frozen=True)
class DataOpsSchedulerConfig:
    interval_seconds: int = 60
    post_close_time: time = time(15, 5)


class DataOpsScheduler:
    """Run once-per-day post-close data maintenance and expose runtime status."""

    def __init__(
        self,
        *,
        maintenance_runner: Callable[[], dict[str, Any]] | None,
        config: DataOpsSchedulerConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        trading_day_checker: Callable[[date], bool] | None = None,
    ) -> None:
        self._maintenance_runner = maintenance_runner
        self._config = config or DataOpsSchedulerConfig()
        self._clock = clock or datetime.now
        self._trading_day_checker = trading_day_checker or TradingScheduler().is_trading_day
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._running = False
        self._cycle_count = 0
        self._skip_count = 0
        self._maintenance_count = 0
        self._last_run_date: str | None = None
        self._next_run_at: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._running = True
            self._stop_event.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = Thread(target=self._loop, name="data-ops-scheduler", daemon=True)
                self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            self._running = False
            self._next_run_at = None
        return self.status()

    def status(self) -> dict[str, Any]:
        now = self._clock()
        phase = self._phase(now)
        with self._lock:
            return {
                "running": self._running,
                "phase": phase,
                "config": {
                    "interval_seconds": self._config.interval_seconds,
                    "post_close_time": self._config.post_close_time.strftime("%H:%M"),
                },
                "tasks": {
                    "post_close_maintenance": {
                        "enabled": self._maintenance_runner is not None,
                        "phase": "post_close",
                        "last_run_date": self._last_run_date,
                    }
                },
                "cycle_count": self._cycle_count,
                "skip_count": self._skip_count,
                "maintenance_count": self._maintenance_count,
                "next_run_at": self._next_run_at,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        now = self._clock()
        phase = self._phase(now)
        with self._lock:
            self._cycle_count += 1
        if self._maintenance_runner is None:
            self._record_skip("no_maintenance_runner")
            return self.status()
        if not force and phase != "post_close":
            self._record_skip(f"phase_{phase}")
            return self.status()
        today = now.date().isoformat()
        if not force and self._last_run_date == today:
            self._record_skip("already_ran_today")
            return self.status()
        with self._lock:
            self._last_started_at = _fmt(now)
            self._last_error = None
        try:
            result = self._maintenance_runner()
        except Exception as exc:  # noqa: BLE001 - scheduler must survive failed jobs.
            with self._lock:
                self._last_error = str(exc)
                self._last_finished_at = _fmt(self._clock())
            return self.status()
        with self._lock:
            self._maintenance_count += 1
            self._last_run_date = today
            self._last_result = result
            self._last_finished_at = _fmt(self._clock())
            self._last_error = None
        return self.status()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                running = self._running
            if running:
                self.run_once()
                self._set_next_run(self._config.interval_seconds)
            self._stop_event.wait(self._config.interval_seconds if running else 0.2)

    def _phase(self, value: datetime) -> str:
        current_date = value.date()
        if not self._trading_day_checker(current_date):
            return "non_trading_day"
        current_time = value.time()
        if current_time < time(9, 15):
            return "pre_open"
        if current_time < time(11, 30):
            return "morning_session"
        if current_time < time(13, 0):
            return "lunch_break"
        if current_time < time(14, 30):
            return "afternoon_session"
        if current_time < time(15, 0):
            return "tail_session"
        if current_time >= self._config.post_close_time:
            return "post_close"
        return "market_closed_waiting"

    def _record_skip(self, reason: str) -> None:
        with self._lock:
            self._skip_count += 1
            self._last_result = {"skipped": True, "skip_reason": reason}
            self._last_finished_at = _fmt(self._clock())
            self._last_error = None

    def _set_next_run(self, interval_seconds: int) -> None:
        with self._lock:
            if self._running:
                self._next_run_at = _fmt(self._clock() + timedelta(seconds=interval_seconds))


def _fmt(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
