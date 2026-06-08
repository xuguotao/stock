"""交易调度器.

管理交易时段、节假日、定时任务。

Usage:
    scheduler = TradingScheduler()
    if scheduler.is_market_open():
        # execute trades
    if scheduler.is_rebalance_day():
        # rebalance portfolio
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Callable

from src.core.calendar import TradingCalendar, is_trading_day


class TradingScheduler:
    """Trading day and time scheduler."""

    def __init__(self):
        self.calendar = TradingCalendar()
        self._callbacks: list[Callable] = []

    def is_trading_day(self, d: date | None = None) -> bool:
        """Check if a date is a trading day."""
        return self.calendar.is_trading_day(d or date.today())

    def is_market_hours(self, current_time: time | None = None) -> bool:
        """Check if within market hours."""
        now = current_time or datetime.now().time()
        # Morning: 9:30-11:30, Afternoon: 13:00-15:00
        morning_start = time(9, 30)
        morning_end = time(11, 30)
        afternoon_start = time(13, 0)
        afternoon_end = time(15, 0)

        return (morning_start <= now <= morning_end or
                afternoon_start <= now <= afternoon_end)

    def is_call_auction(self, current_time: time | None = None) -> bool:
        """Check if within call auction period."""
        now = current_time or datetime.now().time()
        # Morning call auction: 9:15-9:25
        # Afternoon call auction: 14:57-15:00
        return (time(9, 15) <= now <= time(9, 25) or
                time(14, 57) <= now <= time(15, 0))

    def next_trading_day(self, d: date | None = None) -> date:
        """Get next trading day."""
        return self.calendar.get_next_trading_day(d or date.today())

    def prev_trading_day(self, d: date | None = None) -> date:
        """Get previous trading day."""
        return self.calendar.get_previous_trading_day(d or date.today())

    def is_rebalance_day(
        self,
        d: date | None = None,
        frequency: str = "weekly",
    ) -> bool:
        """Check if today is a scheduled rebalance day.

        Args:
            d: Date to check (default: today).
            frequency: "daily", "weekly", or "monthly".
        """
        check_date = d or date.today()
        if not self.is_trading_day(check_date):
            return False

        if frequency == "daily":
            return True
        elif frequency == "weekly":
            # Rebalance on Monday
            return check_date.weekday() == 0
        elif frequency == "monthly":
            # Rebalance on first trading day of month
            prev = self.prev_trading_day(check_date)
            return check_date.month != prev.month
        return False

    def get_trading_days(self, start: date, end: date) -> list[date]:
        """Get all trading days in range."""
        return self.calendar.get_trading_days(start, end)

    def on_trading_day_start(self, callback: Callable) -> None:
        """Register callback for market open."""
        self._callbacks.append(callback)

    def run_callbacks(self) -> None:
        """Run all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Scheduler callback error: {e}")
