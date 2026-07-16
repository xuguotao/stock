"""Tests for research-only corporate-action event helpers."""
from __future__ import annotations

from datetime import date

import pytest

from src.data.research_adjustment_events import daily_ratio
from src.data.research_adjustment_validation import validate_event


def _cash_dividend_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_date": date(2024, 1, 10),
        "category": 1,
        "fenhong": 1.0,
        "songzhuangu": 0.0,
        "peigu": 0.0,
        "peigujia": 0.0,
        "suogu": 1.0,
    }
    event.update(overrides)
    return event


def test_validate_event_approves_cash_dividend_with_matching_ex_close() -> None:
    result = validate_event(
        _cash_dividend_event(),
        pre_close=10.0,
        ex_close=9.0,
    )

    assert result.status == "approved"
    assert result.ratio == 0.9
    assert result.theoretical_price == 9.0
    assert result.error == 0.0


def test_validate_event_requires_an_ex_date_bar() -> None:
    result = validate_event(
        _cash_dividend_event(),
        pre_close=10.0,
        ex_close=None,
    )

    assert result.status == "missing_ex_date_bar"
    assert result.ratio is None


def test_validate_event_treats_missing_suogu_as_no_consolidation() -> None:
    result = validate_event(
        _cash_dividend_event(suogu=None),
        pre_close=10.0,
        ex_close=9.0,
    )

    assert result.status == "approved"
    assert result.ratio == 0.9


@pytest.mark.parametrize("field", ["fenhong", "songzhuangu", "peigu", "peigujia"])
def test_validate_event_rejects_missing_corporate_action_value(field: str) -> None:
    result = validate_event(
        _cash_dividend_event(**{field: None}),
        pre_close=10.0,
        ex_close=9.0,
    )

    assert result.status == "formula_invalid"
    assert result.ratio is None


def test_validate_event_marks_non_price_category_unverified() -> None:
    result = validate_event(
        _cash_dividend_event(category=2),
        pre_close=10.0,
        ex_close=9.0,
    )

    assert result.status == "unverified"
    assert result.ratio is None


def test_validate_event_marks_price_discontinuity_unverified() -> None:
    result = validate_event(
        _cash_dividend_event(),
        pre_close=10.0,
        ex_close=8.0,
    )

    assert result.status == "unverified"
    assert result.ratio is None


def test_daily_ratio_uses_only_approved_events_in_stable_order() -> None:
    events = [
        {"event_date": date(2024, 1, 10), "category": 1, "name": "later", "status": "approved", "ratio": 0.8},
        {"event_date": date(2024, 1, 10), "category": 1, "name": "first", "status": "approved", "ratio": 0.9},
        {"event_date": date(2024, 1, 10), "category": 2, "name": "excluded", "status": "approved", "ratio": 0.5},
    ]

    assert daily_ratio(events) == pytest.approx(0.72)
