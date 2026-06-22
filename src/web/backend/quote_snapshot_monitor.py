"""Background monitor for realtime quote snapshot updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable

from src.trading.scheduler import TradingScheduler


ProgressCallback = Callable[[int, str, str], None]
SessionChecker = Callable[[], tuple[bool, str]]


@dataclass(frozen=True)
class QuoteSnapshotMonitorConfig:
    interval_seconds: int
    limit: int
    include_st: bool
    chunk_size: int = 400
    timeout_seconds: int = 8
    min_chunk_size: int = 200
    max_chunk_size: int = 1000


class QuoteSnapshotMonitor:
    """Run quote snapshot sync on a lightweight background loop."""

    def __init__(
        self,
        *,
        runner: Callable[..., dict[str, Any]],
        session_checker: SessionChecker | None = None,
    ) -> None:
        self._runner = runner
        self._session_checker = session_checker or _default_session_checker
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._config: QuoteSnapshotMonitorConfig | None = None
        self._mode = "manual"
        self._running = False
        self._cycle_count = 0
        self._skip_count = 0
        self._failure_count = 0
        self._timeout_count = 0
        self._effective_chunk_size: int | None = None
        self._last_cycle_duration_seconds: float | None = None
        self._next_run_at: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_progress: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(
        self,
        config: QuoteSnapshotMonitorConfig,
        *,
        run_first_cycle_inline: bool = False,
        mode: str = "manual",
    ) -> dict[str, Any]:
        with self._lock:
            self._config = config
            self._effective_chunk_size = config.chunk_size
            self._mode = mode
            self._running = True
            self._stop_event.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = Thread(target=self._loop, name="quote-snapshot-monitor", daemon=True)
                self._thread.start()
        if run_first_cycle_inline:
            self.run_once()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            self._running = False
            self._next_run_at = None
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            config = self._config
            running = self._running
            mode = self._mode
            cycle_count = self._cycle_count
            skip_count = self._skip_count
            failure_count = self._failure_count
            timeout_count = self._timeout_count
            effective_chunk_size = self._effective_chunk_size
            last_cycle_duration_seconds = self._last_cycle_duration_seconds
            next_run_at = self._next_run_at
            last_started_at = self._last_started_at
            last_finished_at = self._last_finished_at
            last_progress = self._last_progress
            last_result = self._last_result
            last_error = self._last_error
        session_open, session_reason = self._session_checker()
        return {
            "running": running,
            "mode": mode,
            "config": {
                "interval_seconds": config.interval_seconds if config else None,
                "limit": config.limit if config else None,
                "include_st": config.include_st if config else None,
                "chunk_size": config.chunk_size if config else None,
                "timeout_seconds": config.timeout_seconds if config else None,
                "min_chunk_size": config.min_chunk_size if config else None,
                "max_chunk_size": config.max_chunk_size if config else None,
            },
            "session": {
                "open": session_open,
                "reason": session_reason,
                "message": _session_message(session_reason) if not session_open else "交易时段内，可执行行情快照采集",
            },
            "cycle_count": cycle_count,
            "skip_count": skip_count,
            "failure_count": failure_count,
            "timeout_count": timeout_count,
            "effective_chunk_size": effective_chunk_size if effective_chunk_size is not None else (config.chunk_size if config else None),
            "last_cycle_duration_seconds": last_cycle_duration_seconds,
            "next_run_at": next_run_at,
            "last_started_at": last_started_at,
            "last_finished_at": last_finished_at,
            "last_progress": last_progress,
            "last_result": last_result,
            "last_error": last_error,
        }

    def run_once(self) -> None:
        with self._lock:
            config = self._config
            effective_chunk_size = self._effective_chunk_size or (config.chunk_size if config else None)
        if config is None:
            return
        self._set_started()
        is_open, reason = self._session_checker()
        if not is_open:
            self._record_skip(reason)
            return
        try:
            result = self._runner(
                limit=config.limit,
                include_st=config.include_st,
                chunk_size=effective_chunk_size,
                timeout_seconds=config.timeout_seconds,
                progress=self._progress,
            )
        except Exception as exc:  # noqa: BLE001 - monitor must survive failed cycles.
            with self._lock:
                self._failure_count += 1
                self._last_error = str(exc)
                self._last_finished_at = _now()
            return
        duration = _result_duration(result)
        timed_out = duration > config.timeout_seconds
        overrun_seconds = max(0.0, duration - config.interval_seconds)
        result = {
            **result,
            "timeout": timed_out,
            "deadline_seconds": config.timeout_seconds,
            "overrun_seconds": round(overrun_seconds, 3),
            "effective_chunk_size": effective_chunk_size,
        }
        with self._lock:
            self._cycle_count += 1
            self._last_cycle_duration_seconds = round(duration, 3)
            if timed_out:
                self._timeout_count += 1
                self._effective_chunk_size = _reduced_chunk_size(
                    effective_chunk_size,
                    min_chunk_size=config.min_chunk_size,
                )
            else:
                self._effective_chunk_size = _increased_chunk_size(
                    effective_chunk_size,
                    max_chunk_size=min(config.chunk_size, config.max_chunk_size),
                )
            self._last_result = result
            self._last_error = None
            self._last_finished_at = _now()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                running = self._running
                config = self._config
            if not running or config is None:
                sleep(0.2)
                continue
            cycle_started = monotonic()
            self.run_once()
            wait_seconds = max(0.0, config.interval_seconds - (monotonic() - cycle_started))
            self._set_next_run(wait_seconds)
            if wait_seconds > 0:
                self._stop_event.wait(wait_seconds)

    def _set_started(self) -> None:
        with self._lock:
            if self._effective_chunk_size is None and self._config is not None:
                self._effective_chunk_size = self._config.chunk_size
            self._last_started_at = _now()
            self._last_progress = {"percent": 0, "stage": "starting", "message": "行情快照采集启动"}

    def _record_skip(self, reason: str) -> None:
        message = _session_message(reason)
        with self._lock:
            self._skip_count += 1
            self._last_result = {"skipped": True, "skip_reason": reason, "message": message}
            self._last_progress = {"percent": 100, "stage": "skipped", "message": message}
            self._last_error = None
            self._last_finished_at = _now()

    def _progress(self, percent: int, stage: str, message: str) -> None:
        with self._lock:
            self._last_progress = {"percent": percent, "stage": stage, "message": message}

    def _set_next_run(self, wait_seconds: float) -> None:
        with self._lock:
            if self._running:
                self._next_run_at = (datetime.now() + timedelta(seconds=max(0, wait_seconds))).isoformat(
                    timespec="seconds"
                )


def _default_session_checker() -> tuple[bool, str]:
    scheduler = TradingScheduler()
    today = datetime.now().date()
    if not scheduler.is_trading_day(today):
        return False, "not_trading_day"
    if not scheduler.is_market_hours():
        return False, "outside_market_hours"
    return True, "market_open"


def _session_message(reason: str) -> str:
    if reason == "not_trading_day":
        return "非交易日，跳过行情快照采集"
    if reason == "outside_market_hours":
        return "非交易时段，跳过行情快照采集"
    return "当前不满足行情快照采集条件，已跳过"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _result_duration(result: dict[str, Any]) -> float:
    timings = result.get("timings")
    if isinstance(timings, dict) and timings.get("total_seconds") is not None:
        return float(timings["total_seconds"])
    return float(result.get("duration_seconds") or 0.0)


def _reduced_chunk_size(value: int, *, min_chunk_size: int) -> int:
    return max(min_chunk_size, int(value * 0.8))


def _increased_chunk_size(value: int, *, max_chunk_size: int) -> int:
    if value >= max_chunk_size:
        return value
    return min(max_chunk_size, max(value + 50, int(value * 1.1)))
