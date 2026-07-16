"""Tests for pure research adjustment-factor calculation."""
from __future__ import annotations

from datetime import date

from src.data.research_adjustment_validation import build_daily_factors


def test_build_daily_factors_applies_event_before_the_event_to_forward_factor() -> None:
    factors = build_daily_factors(
        [date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 11)],
        {date(2024, 1, 10): 0.9},
    )

    assert factors[date(2024, 1, 9)].forward_factor == 0.9
    assert factors[date(2024, 1, 10)].forward_factor == 1.0
    assert factors[date(2024, 1, 11)].forward_factor == 1.0
    assert factors[date(2024, 1, 9)].backward_factor == 1.0
    assert factors[date(2024, 1, 10)].backward_factor == 1 / 0.9
    assert factors[date(2024, 1, 11)].backward_factor == 1 / 0.9
