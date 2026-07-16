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
    assert "create table if not exists research_adjustment_raw_bars" in ddl
    assert "create table if not exists research_daily_adjustment_factors" in ddl
    assert "create table if not exists research_adjustment_runs" in ddl
    assert ddl.count("replacingmergetree") == 4
    assert "ifnull(category, -1)" in ddl
    assert "datetime64(3)" in ddl
    assert "alter table research_adjustment_runs add column if not exists input_watermark" in ddl
    assert "alter table research_adjustment_runs add column if not exists input_ingest_seq" in ddl


def test_completed_published_run_is_returned_as_current() -> None:
    published_at = datetime(2026, 7, 16, 17, 25)
    watermark = datetime(2026, 7, 16, 17, 24)
    client = _Client(responses=[[(1,)], [(1,)], [(1,)], [(0,)], [("run-1", "v1", published_at, watermark, 21)]])
    store = ResearchAdjustmentStore(client)

    store.publish_run(
        "run-1", "v1", completed=True, expected_event_count=1, expected_factor_count=1,
        input_watermark=watermark, input_ingest_seq=21, expected_raw_bar_count=1,
    )
    current = store.current_run("v1")

    assert current == {
        "run_id": "run-1", "formula_version": "v1", "published_at": published_at,
        "input_watermark": watermark, "input_ingest_seq": 21,
    }
    publish_sql, publish_params = client.calls[4]
    assert "insert into research_adjustment_runs" in publish_sql.lower()
    assert publish_params[0][:3] == ("run-1", "v1", "published")
    assert isinstance(publish_params[0][3], datetime)
    assert "status = 'published'" in client.calls[5][0].lower()
    assert "order by published_at desc, run_id desc" in client.calls[5][0].lower()


def test_published_run_persists_and_returns_input_ingest_sequence() -> None:
    published_at = datetime(2026, 7, 16, 17, 25)
    client = _Client(
        responses=[[(0,)], [(1,)], [(1,)], [(0,)], [("run-1", "v1", published_at, None, 21)]]
    )
    store = ResearchAdjustmentStore(client)

    store.publish_run(
        "run-1", "v1", completed=True, expected_event_count=0, expected_factor_count=1,
        expected_raw_bar_count=1, input_ingest_seq=21,
    )

    assert store.current_run("v1")["input_ingest_seq"] == 21
    assert "input_ingest_seq" in client.calls[4][0].lower()
    assert client.calls[4][1][0][-1] == 21


def test_stale_base_run_cannot_publish_over_newer_snapshot() -> None:
    client = _Client(responses=[[("newer-run", "v1", datetime(2026, 7, 16, 18), datetime(2026, 7, 16, 17, 30), 21)]])
    store = ResearchAdjustmentStore(client)

    with pytest.raises(ValueError, match="published run changed"):
        store.publish_run(
            "stale-run", "v1", completed=True, expected_event_count=0, expected_factor_count=1,
            base_run_id="prior-run", expected_raw_bar_count=1, input_ingest_seq=21,
        )

    assert all("insert into research_adjustment_runs" not in sql.lower() for sql, _ in client.calls)


def test_second_candidate_based_on_same_snapshot_is_rejected_after_first_publish(tmp_path) -> None:
    class _PublishingClient:
        def __init__(self) -> None:
            self.current_run_id = "prior-run"

        def execute(self, sql: str, params: object | None = None):
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("select run_id, formula_version"):
                return [(self.current_run_id, "v1", datetime(2026, 7, 16, 17, 25), datetime(2026, 7, 16, 17, 20), 21)]
            if "select count()" in normalized:
                if "left anti join" in normalized:
                    return [(0,)]
                return [(0,)] if "events" in normalized else [(1,)]
            if "insert into research_adjustment_runs" in normalized:
                self.current_run_id = params[0][0]
            return []

    store = ResearchAdjustmentStore(_PublishingClient(), lock_directory=tmp_path)
    store.publish_run("run-a", "v1", True, 0, 1, 1, input_ingest_seq=21, base_run_id="prior-run")

    with pytest.raises(ValueError, match="published run changed"):
        store.publish_run("run-b", "v1", True, 0, 1, 1, input_ingest_seq=21, base_run_id="prior-run")


def test_completed_run_with_no_events_and_daily_factors_can_be_published() -> None:
    client = _Client(responses=[[(0,)], [(2,)], [(2,)], [(0,)]])
    store = ResearchAdjustmentStore(client)

    store.publish_run(
        "run-1",
        "v1",
        completed=True,
        expected_event_count=0,
        expected_factor_count=2, expected_raw_bar_count=2, input_ingest_seq=21,
    )

    assert "insert into research_adjustment_runs" in client.calls[4][0].lower()


def test_publish_requires_a_nonzero_raw_bar_count_for_positive_factors() -> None:
    store = ResearchAdjustmentStore(_Client())

    with pytest.raises(ValueError, match="raw-bar"):
        store.publish_run("run-1", "v1", completed=True, expected_event_count=0, expected_factor_count=1)
    with pytest.raises(ValueError, match="raw-bar"):
        store.publish_run(
            "run-1", "v1", completed=True, expected_event_count=0,
                expected_factor_count=1, expected_raw_bar_count=0, input_ingest_seq=21,
        )


def test_publish_rejects_raw_bar_and_factor_count_mismatch() -> None:
    client = _Client(responses=[[(0,)], [(2,)], [(1,)]])

    with pytest.raises(ValueError, match="raw-bar"):
        ResearchAdjustmentStore(client).publish_run(
            "run-1", "v1", completed=True, expected_event_count=0,
                expected_factor_count=2, expected_raw_bar_count=2, input_ingest_seq=21,
        )

    assert all("insert into research_adjustment_runs" not in sql.lower() for sql, _ in client.calls)


def test_publish_rejects_raw_bar_and_factor_symbol_date_mismatch() -> None:
    client = _Client(responses=[[(0,)], [(2,)], [(2,)], [(1,)]])

    with pytest.raises(ValueError, match="symbol/date coverage"):
        ResearchAdjustmentStore(client).publish_run(
            "run-1", "v1", completed=True, expected_event_count=0,
                expected_factor_count=2, expected_raw_bar_count=2, input_ingest_seq=21,
        )


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

    with pytest.raises(ValueError):
        store.publish_run(
            "run-1",
            "v1",
            completed=True,
                expected_event_count=expected_events,
                expected_factor_count=expected_factors,
                expected_raw_bar_count=expected_factors, input_ingest_seq=21,
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
