"""Tests for the research-only adjustment data store."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.data.research_adjustment_store import ResearchAdjustmentStore


class _Client:
    def __init__(self, responses: list[list[tuple[object, ...]]] | None = None) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.responses = responses or []

    def execute(self, sql: str, params: object | None = None) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        if sql.lstrip().lower().startswith("select") and self.responses:
            return self.responses.pop(0)
        return []


def test_ensure_tables_creates_research_derivative_tables() -> None:
    client = _Client()

    ResearchAdjustmentStore(client).ensure_tables()

    ddl = "\n".join(sql for sql, _ in client.calls).lower()
    assert "create table if not exists research_adjustment_events" in ddl
    assert "create table if not exists research_daily_adjustment_factors" in ddl
    assert "create table if not exists research_adjustment_runs" in ddl
    assert ddl.count("replacingmergetree") == 3
    assert "ifnull(category, -1)" in ddl
    assert "datetime64(3)" in ddl


def test_completed_published_run_is_returned_as_current() -> None:
    published_at = datetime(2026, 7, 16, 17, 25)
    client = _Client(responses=[[(1,)], [(1,)], [("run-1", "v1", published_at)]])
    store = ResearchAdjustmentStore(client)

    store.publish_run("run-1", "v1", completed=True, expected_event_count=1, expected_factor_count=1)
    current = store.current_run("v1")

    assert current == {"run_id": "run-1", "formula_version": "v1", "published_at": published_at}
    publish_sql, publish_params = client.calls[2]
    assert "insert into research_adjustment_runs" in publish_sql.lower()
    assert publish_params[0][:3] == ("run-1", "v1", "published")
    assert isinstance(publish_params[0][3], datetime)
    assert "status = 'published'" in client.calls[3][0].lower()
    assert "order by published_at desc, run_id desc" in client.calls[3][0].lower()


def test_incomplete_run_cannot_be_published() -> None:
    client = _Client()
    store = ResearchAdjustmentStore(client)

    with pytest.raises(ValueError, match="completed"):
        store.publish_run("run-1", "v1", completed=False)

    assert client.calls == []


def test_candidate_event_rejects_an_unknown_validation_status() -> None:
    client = _Client()
    store = ResearchAdjustmentStore(client)

    with pytest.raises(ValueError, match="validation status"):
        store.write_candidate_events(
            "run-1",
            "v1",
            [{"symbol": "600000.SH", "event_date": date(2026, 7, 16), "status": "unknown"}],
        )

    assert client.calls == []


@pytest.mark.parametrize("actual_events, actual_factors, expected_events, expected_factors", [(0, 0, 0, 0), (1, 1, 2, 1)])
def test_empty_or_partial_candidate_cannot_be_published(
    actual_events: int, actual_factors: int, expected_events: int, expected_factors: int
) -> None:
    client = _Client(responses=[[(actual_events,)], [(actual_factors,)]])
    store = ResearchAdjustmentStore(client)

    with pytest.raises(ValueError, match="candidate"):
        store.publish_run(
            "run-1",
            "v1",
            completed=True,
            expected_event_count=expected_events,
            expected_factor_count=expected_factors,
        )

    assert all("insert into research_adjustment_runs" not in sql.lower() for sql, _ in client.calls)


def test_candidate_factor_converts_datetime_trade_date_to_date() -> None:
    client = _Client()

    ResearchAdjustmentStore(client).write_candidate_factors(
        "run-1",
        "v1",
        [{"symbol": "600000.SH", "trade_date": datetime(2026, 7, 16, 9, 30)}],
    )

    assert client.calls[0][1][0][3] == date(2026, 7, 16)
