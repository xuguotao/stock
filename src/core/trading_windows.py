"""Shared trading window definitions used by strategy and ML code."""

from __future__ import annotations

from datetime import time

TAIL_SESSION_START = time(14, 30)
TAIL_SESSION_END = time(15, 0)
TAIL_DECISION_TIMES = (
    time(14, 30),
    time(14, 35),
    time(14, 40),
    time(14, 45),
    time(14, 50),
    time(14, 55),
)
TAIL_SESSION_LABEL = f"{TAIL_SESSION_START.strftime('%H:%M')}-{TAIL_SESSION_END.strftime('%H:%M')}"


def tail_bar_time_label(value: time = TAIL_SESSION_START) -> str:
    return value.strftime("%H:%M")
