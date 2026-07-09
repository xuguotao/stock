"""In-process 5-minute kline monitor for dashboard-controlled updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable

from src.trading.scheduler import TradingScheduler


ProgressCallback = Callable[[int, str, str], None]
SessionChecker = Callable[[date], tuple[bool, str]]


@dataclass(frozen=True)
class Minute5MonitorConfig:
    trade_date: date | None
    interval_seconds: int
    limit: int
    include_st: bool
    max_fetch_symbols: int = 0


class Minute5UpdateMonitor:
    """Run incremental minute5 updates on a lightweight background loop."""

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
        self._config: Minute5MonitorConfig | None = None
        self._mode = "manual"
        self._running = False
        self._started_count = 0
        self._cycle_count = 0
        self._skip_count = 0
        self._next_run_at: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_progress: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(
        self,
        config: Minute5MonitorConfig,
        *,
        run_first_cycle_inline: bool = False,
        mode: str = "manual",
    ) -> dict[str, Any]:
        with self._lock:
            self._config = config
            self._mode = mode
            self._running = True
            self._stop_event.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = Thread(target=self._loop, name="minute5-update-monitor", daemon=True)
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
            next_run_at = self._next_run_at
            started_count = self._started_count
            cycle_count = self._cycle_count
            skip_count = self._skip_count
            last_started_at = self._last_started_at
            last_finished_at = self._last_finished_at
            last_progress = self._last_progress
            last_result = self._last_result
            last_error = self._last_error
        trade_date = config.trade_date if config and config.trade_date else date.today()
        session_open, session_reason = self._session_checker(trade_date)
        return {
            "running": running,
            "mode": mode,
            "config": {
                "trade_date": config.trade_date.isoformat() if config and config.trade_date else None,
                "interval_seconds": config.interval_seconds if config else None,
                "limit": config.limit if config else None,
                "include_st": config.include_st if config else None,
                "max_fetch_symbols": config.max_fetch_symbols if config else None,
            },
            "session": {
                "open": session_open,
                "reason": session_reason,
                "message": _skip_message(session_reason) if not session_open else "交易时段内，可执行分钟线持续更新",
            },
            "started_count": started_count,
            "cycle_count": cycle_count,
            "skip_count": skip_count,
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
        if config is None:
            return
        trade_date = config.trade_date or date.today()
        self._set_started()
        is_open, reason = self._session_checker(trade_date)
        if not is_open:
            self._record_skip(trade_date, reason)
            return
        try:
            result = self._runner(
                trade_date=trade_date,
                limit=config.limit,
                symbols=None,
                include_st=config.include_st,
                max_fetch_symbols=config.max_fetch_symbols,
                progress=self._progress,
            )
        except Exception as exc:  # noqa: BLE001 - monitor must survive failed cycles.
            with self._lock:
                self._last_error = str(exc)
                self._last_finished_at = _now()
            return
        with self._lock:
            self._cycle_count += 1
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
            wait_seconds = _monitor_wait_seconds(
                interval_seconds=config.interval_seconds,
                duration_seconds=monotonic() - cycle_started,
            )
            self._set_next_run(wait_seconds)
            self._stop_event.wait(wait_seconds)

    def _set_started(self) -> None:
        with self._lock:
            self._started_count += 1
            self._last_started_at = _now()
            self._last_progress = {"percent": 0, "stage": "starting", "message": "分钟线持续更新启动"}

    def _record_skip(self, trade_date: date, reason: str) -> None:
        message = _skip_message(reason)
        with self._lock:
            self._skip_count += 1
            self._last_result = {
                "skipped": True,
                "skip_reason": reason,
                "trade_date": trade_date.isoformat(),
                "message": message,
            }
            self._last_progress = {"percent": 100, "stage": "skipped", "message": message}
            self._last_error = None
            self._last_finished_at = _now()

    def _progress(
        self,
        percent: int,
        stage: str,
        message: str,
        *,
        processed: int | None = None,
        total: int | None = None,
    ) -> None:
        with self._lock:
            progress_data: dict[str, Any] = {
                "percent": percent,
                "stage": stage,
                "message": message,
            }
            if processed is not None:
                progress_data["processed"] = processed
            if total is not None:
                progress_data["total"] = total
            self._last_progress = progress_data

    def _set_next_run(self, interval_seconds: int) -> None:
        with self._lock:
            if self._running:
                self._next_run_at = (datetime.now() + timedelta(seconds=max(1, interval_seconds))).isoformat(
                    timespec="seconds"
                )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _monitor_wait_seconds(*, interval_seconds: int, duration_seconds: float) -> float:
    return max(1.0, float(interval_seconds) - max(0.0, duration_seconds))


def _default_session_checker(trade_date: date) -> tuple[bool, str]:
    today = date.today()
    if trade_date != today:
        return False, "not_today"
    scheduler = TradingScheduler()
    if not scheduler.is_trading_day(today):
        return False, "not_trading_day"
    if not scheduler.is_market_hours():
        return False, "outside_market_hours"
    return True, "market_open"


def _skip_message(reason: str) -> str:
    if reason == "not_today":
        return "持续更新只在今日交易日运行，历史日期请使用手动更新"
    if reason == "not_trading_day":
        return "非交易日，跳过分钟线持续更新"
    if reason == "outside_market_hours":
        return "非交易时段，跳过分钟线持续更新"
    return "当前不满足持续更新条件，已跳过"
