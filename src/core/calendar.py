"""Chinese trading calendar.

Handles:
  - Weekday filtering (Mon-Fri only)
  - Chinese public holidays (Spring Festival, National Day, etc.)
  - Special working days (make-up workdays on weekends)

Usage:
    from src.core.calendar import TradingCalendar
    cal = TradingCalendar()
    cal.is_trading_day("2025-01-27")  # False (Spring Festival)
    cal.get_trading_days("2025-01-01", "2025-01-31")
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache


# ── Hardcoded Holiday Dates (2024-2026) ───────────────────────
# Source: State Council official announcements

HOLIDAYS_2024 = [
    "2024-01-01",
    "2024-02-10", "2024-02-11", "2024-02-12", "2024-02-13",
    "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",
    "2024-04-04", "2024-04-05", "2024-04-06",
    "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
    "2024-06-08", "2024-06-09", "2024-06-10",
    "2024-09-15", "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04",
    "2024-10-05", "2024-10-06", "2024-10-07",
]

HOLIDAYS_2025 = [
    "2025-01-01",
    "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31", "2025-06-01", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
]

HOLIDAYS_2026 = [
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
]

# Special working days (weekends that are workdays due to holiday make-up)
WORKING_WEEKENDS_2024 = ["2024-02-04", "2024-02-18", "2024-04-07", "2024-04-28",
                         "2024-05-11", "2024-09-14", "2024-09-29", "2024-10-12"]
WORKING_WEEKENDS_2025 = ["2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11"]
WORKING_WEEKENDS_2026 = []

ALL_HOLIDAYS: set[date] = set()
ALL_WORKING_WEEKENDS: set[date] = set()


def _parse_dates(date_strs: list[str]) -> set[date]:
    return {datetime.strptime(d, "%Y-%m-%d").date() for d in date_strs}


def _init_calendar() -> None:
    global ALL_HOLIDAYS, ALL_WORKING_WEEKENDS
    for year_dates in [HOLIDAYS_2024, HOLIDAYS_2025, HOLIDAYS_2026]:
        ALL_HOLIDAYS |= _parse_dates(year_dates)
    for year_dates in [WORKING_WEEKENDS_2024, WORKING_WEEKENDS_2025, WORKING_WEEKENDS_2026]:
        ALL_WORKING_WEEKENDS |= _parse_dates(year_dates)


_init_calendar()


class TradingCalendar:
    """Chinese A-share trading calendar."""

    def is_trading_day(self, d: date | str) -> bool:
        """Check if a date is a trading day."""
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        if d.weekday() >= 5:
            return d in ALL_WORKING_WEEKENDS
        return d not in ALL_HOLIDAYS

    def get_trading_days(self, start: date | str, end: date | str) -> list[date]:
        """Get all trading days in a date range."""
        if isinstance(start, str):
            start = datetime.strptime(start, "%Y-%m-%d").date()
        if isinstance(end, str):
            end = datetime.strptime(end, "%Y-%m-%d").date()

        days = []
        current = start
        while current <= end:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def get_previous_trading_day(self, d: date | str) -> date:
        """Get the previous trading day."""
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        current = d - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def get_next_trading_day(self, d: date | str) -> date:
        """Get the next trading day."""
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        current = d + timedelta(days=1)
        while not self.is_trading_day(current):
            current += timedelta(days=1)
        return current


# Module-level singleton
_default_calendar = TradingCalendar()


def is_trading_day(d: date | str) -> bool:
    return _default_calendar.is_trading_day(d)


def get_trading_days(start: date | str, end: date | str) -> list[date]:
    return _default_calendar.get_trading_days(start, end)
