"""Pure helpers for combining validated research adjustment events."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def daily_ratio(events: Iterable[Mapping[str, Any] | Any]) -> float:
    """Return the combined ratio for approved events in a deterministic order.

    Events that were not explicitly approved are intentionally excluded.  This
    keeps a bad or incomplete corporate-action record from entering a research
    adjustment factor.
    """
    approved = [event for event in events if _value(event, "status") == "approved"]
    ordered = sorted(
        approved,
        key=lambda event: (
            _value(event, "event_date"),
            _value(event, "category") if _value(event, "category") is not None else 0,
            _value(event, "name") or "",
        ),
    )
    ratio = 1.0
    for event in ordered:
        value = _value(event, "ratio")
        if value is not None:
            ratio *= float(value)
    return ratio


def _value(event: Mapping[str, Any] | Any, field: str) -> Any:
    if isinstance(event, Mapping):
        return event.get(field)
    return getattr(event, field, None)
