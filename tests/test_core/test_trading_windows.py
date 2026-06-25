from __future__ import annotations

from datetime import time

from src.core.trading_windows import (
    TAIL_DECISION_TIMES,
    TAIL_SESSION_END,
    TAIL_SESSION_LABEL,
    TAIL_SESSION_START,
    tail_bar_time_label,
)
from src.ml.tail_features import DEFAULT_DECISION_TIMES
from src.strategy.scanner import IntradayScanner


def test_tail_session_window_is_shared_by_ml_and_scanner_defaults() -> None:
    scanner = IntradayScanner(aggregator=object())

    assert TAIL_SESSION_START == time(14, 30)
    assert TAIL_SESSION_END == time(15, 0)
    assert TAIL_SESSION_LABEL == "14:30-15:00"
    assert DEFAULT_DECISION_TIMES == TAIL_DECISION_TIMES
    assert scanner.tail_start == TAIL_SESSION_START
    assert scanner.tail_end == TAIL_SESSION_END
    assert tail_bar_time_label(TAIL_SESSION_START) == "14:30"
