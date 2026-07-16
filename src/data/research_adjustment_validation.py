"""Validation and factor calculation for research-only adjusted prices."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
import math
from typing import Any


PRICE_ERROR_TOLERANCE = 0.03


@dataclass(frozen=True)
class ValidatedEvent:
    """The auditable outcome of validating one corporate-action event."""

    status: str
    ratio: float | None
    theoretical_price: float | None
    error: float | None


@dataclass(frozen=True)
class DailyAdjustmentFactors:
    """Forward and backward price factors for one trading date."""

    forward_factor: float
    backward_factor: float


def validate_event(
    event: Mapping[str, Any],
    pre_close: float | None,
    ex_close: float | None,
    *,
    price_error_tolerance: float = PRICE_ERROR_TOLERANCE,
) -> ValidatedEvent:
    """Validate one event against the adjacent raw daily bars.

    The event's theoretical ex-rights price uses the existing adjustment
    formula.  A record is usable only when that calculation is finite and its
    ex-date close is close enough to the theoretical price.
    """
    if not _positive_finite(pre_close):
        return ValidatedEvent("missing_pre_close", None, None, None)
    if not _positive_finite(ex_close):
        return ValidatedEvent("missing_ex_date_bar", None, None, None)
    if event.get("category") != 1:
        return ValidatedEvent("unverified", None, None, None)

    fenhong = _required_nonnegative(event.get("fenhong"))
    songzhuangu = _required_nonnegative(event.get("songzhuangu"))
    peigu = _required_nonnegative(event.get("peigu"))
    suogu = _nonnegative(event.get("suogu"), default=1.0)
    if None in (fenhong, songzhuangu, peigu, suogu):
        return ValidatedEvent("formula_invalid", None, None, None)
    if suogu == 0.0:
        suogu = 1.0

    peigujia = _required_nonnegative(event.get("peigujia"))
    if peigujia is None:
        return ValidatedEvent("formula_invalid", None, None, None)

    denominator = float(pre_close) + songzhuangu + peigu
    numerator = float(pre_close) - fenhong + peigu * peigujia
    if denominator <= 0 or numerator <= 0:
        return ValidatedEvent("formula_invalid", None, None, None)

    ratio = numerator / denominator * suogu
    theoretical_price = float(pre_close) * ratio
    if not _positive_finite(ratio) or not _positive_finite(theoretical_price):
        return ValidatedEvent("formula_invalid", None, None, None)

    error = (float(ex_close) - theoretical_price) / theoretical_price
    if abs(error) > price_error_tolerance:
        return ValidatedEvent("unverified", None, theoretical_price, error)
    return ValidatedEvent("approved", ratio, theoretical_price, error)


def build_daily_factors(
    trade_dates: Iterable[date], daily_ratios: Mapping[date, float],
) -> dict[date, DailyAdjustmentFactors]:
    """Build date-indexed factors from already approved daily event ratios.

    Forward factors include only events strictly after a date, leaving the
    event date and all newer bars at the current-price anchor.  Backward
    factors are the inverse product of events through that date.
    """
    dates = sorted(set(trade_dates))
    validated_ratios = {
        event_date: float(ratio)
        for event_date, ratio in daily_ratios.items()
        if _positive_finite(ratio)
    }

    forward_by_date: dict[date, float] = {}
    future_product = 1.0
    for trade_date in reversed(dates):
        forward_by_date[trade_date] = future_product
        if trade_date in validated_ratios:
            future_product *= validated_ratios[trade_date]

    result: dict[date, DailyAdjustmentFactors] = {}
    past_product = 1.0
    for trade_date in dates:
        if trade_date in validated_ratios:
            past_product *= validated_ratios[trade_date]
        result[trade_date] = DailyAdjustmentFactors(
            forward_factor=forward_by_date[trade_date],
            backward_factor=1.0 / past_product,
        )
    return result


def _nonnegative(value: object, *, default: float) -> float | None:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def _required_nonnegative(value: object) -> float | None:
    if value is None:
        return None
    return _nonnegative(value, default=0.0)


def _positive_finite(value: object) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False
