"""Tests for the safe XDXR three-layer migration report."""
from __future__ import annotations

import pytest

from scripts import migrate_xdxr_three_layer


class _MigrationClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, object | None]] = []

    def execute(self, sql: str, params: object | None = None):
        self.commands.append((sql, params))
        normalized = " ".join(sql.lower().split())
        if "select count() from mootdx_xdxr final" in normalized:
            return [(10,)]
        if "select count() from mootdx_xdxr_current" in normalized:
            return [(10,)]
        if "having count() = 1" in normalized:
            return [(0,)]
        if "tojsonstring" in normalized:
            return [(0,)]
        if "from mootdx_xdxr_event_versions as version" in normalized:
            return [(10,)]
        raise AssertionError(sql)


def test_migration_dry_run_reports_legacy_and_new_projection_differences() -> None:
    client = _MigrationClient()

    report = migrate_xdxr_three_layer.run_migration(
        client=client,
        dry_run=True,
        baseline_run_id="baseline-run",
    )

    assert report == {
        "renamed": False,
        "legacy_event_count": 10,
        "current_event_count": 10,
        "business_key_difference_count": 0,
        "content_difference_count": 0,
        "baseline_run_id": "baseline-run",
        "baseline_event_count": 10,
        "ready_for_cutover": True,
    }
    assert not any("rename table" in sql.lower() for sql, _ in client.commands)
    assert any(params == {"baseline_run_id": "baseline-run"} for _, params in client.commands)


def test_migration_dry_run_is_not_ready_when_projection_differs() -> None:
    class _DifferingClient(_MigrationClient):
        def execute(self, sql: str, params: object | None = None):
            if "having count() = 1" in " ".join(sql.lower().split()):
                self.commands.append((sql, params))
                return [(1,)]
            return super().execute(sql, params)

    report = migrate_xdxr_three_layer.run_migration(
        client=_DifferingClient(), dry_run=True, baseline_run_id="baseline-run"
    )

    assert report["ready_for_cutover"] is False


def test_migration_execute_refuses_any_projection_difference() -> None:
    class _DifferingClient(_MigrationClient):
        def execute(self, sql: str, params: object | None = None):
            if "having count() = 1" in " ".join(sql.lower().split()):
                self.commands.append((sql, params))
                return [(1,)]
            return super().execute(sql, params)

    client = _DifferingClient()

    with pytest.raises(ValueError, match="cutover refused"):
        migrate_xdxr_three_layer.run_migration(
            client=client, dry_run=False, baseline_run_id="baseline-run"
        )

    assert not any("rename table" in sql.lower() for sql, _ in client.commands)


def test_content_difference_query_avoids_clickhouse_current_keyword_as_alias() -> None:
    assert "mootdx_xdxr_current as projection" in migrate_xdxr_three_layer._CONTENT_DIFFERENCE_SQL
    assert "from (select * from mootdx_xdxr final) as legacy" in migrate_xdxr_three_layer._CONTENT_DIFFERENCE_SQL


def test_baseline_query_aliases_final_audit_through_subquery() -> None:
    assert "inner join (select * from mootdx_ingestion_runs final) as ingestion" in migrate_xdxr_three_layer._BASELINE_EVENT_COUNT_SQL
