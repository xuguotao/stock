"""Persist versioned, research-only corporate-action adjustment results."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import fcntl

from src.data.clickhouse_source import ClickHouseStockDataSource


VALIDATION_STATUSES = frozenset(
    {
        "approved",
        "unverified",
        "source_mismatch",
        "missing_pre_close",
        "missing_ex_date_bar",
        "formula_invalid",
    }
)
_UNSET = object()


class ResearchAdjustmentStore:
    """Store candidate adjustment results and publish complete runs atomically by version.

    Candidate event and factor rows are deliberately keyed by ``run_id``.  Readers
    must resolve a run through :meth:`current_run`, which only returns published
    runs, so partial or failed work is never selected as research input.
    """

    def __init__(self, client: Any | None = None, lock_directory: Path | None = None) -> None:
        self._client = client
        self._lock_directory = lock_directory or Path(tempfile.gettempdir())

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = ClickHouseStockDataSource()._client_instance()
        return self._client

    def ensure_tables(self) -> None:
        self.client.execute(
            """
            create table if not exists research_adjustment_events (
                run_id String,
                formula_version String,
                symbol String,
                event_date Date,
                category Nullable(Int32),
                event_name String,
                validation_status String,
                ratio Nullable(Float64),
                theoretical_price Nullable(Float64),
                pre_close Nullable(Float64),
                ex_close Nullable(Float64),
                validation_error Nullable(Float64),
                event_payload String,
                computed_at DateTime
            ) engine = ReplacingMergeTree(computed_at)
            partition by toYYYYMM(event_date)
            order by (formula_version, run_id, symbol, event_date, ifNull(category, -1), event_name)
            """
        )
        self.client.execute(
            """
            create table if not exists research_daily_adjustment_factors (
                run_id String,
                formula_version String,
                symbol String,
                trade_date Date,
                forward_factor Nullable(Float64),
                backward_factor Nullable(Float64),
                eligible_event_count UInt32,
                excluded_event_count UInt32,
                quality_status String,
                input_snapshot_at Nullable(DateTime),
                computed_at DateTime
            ) engine = ReplacingMergeTree(computed_at)
            partition by toYYYYMM(trade_date)
            order by (formula_version, run_id, symbol, trade_date)
            """
        )
        self.client.execute(
            """
            create table if not exists research_adjustment_runs (
                run_id String,
                formula_version String,
                status String,
                published_at DateTime64(3),
                input_watermark Nullable(DateTime)
            ) engine = ReplacingMergeTree(published_at)
            order by (formula_version, run_id)
            """
        )
        self.client.execute(
            "alter table research_adjustment_runs add column if not exists input_watermark Nullable(DateTime)"
        )

    def write_candidate_events(
        self, run_id: str, formula_version: str, rows: Sequence[Mapping[str, Any]]
    ) -> int:
        """Write event-validation candidates; this does not make them readable."""
        values = [self._event_row(run_id, formula_version, row) for row in rows]
        if not values:
            return 0
        self.client.execute(
            """
            insert into research_adjustment_events
                (run_id, formula_version, symbol, event_date, category, event_name,
                 validation_status, ratio, theoretical_price, pre_close, ex_close,
                 validation_error, event_payload, computed_at)
            values
            """,
            values,
        )
        return len(values)

    def write_candidate_factors(
        self, run_id: str, formula_version: str, rows: Sequence[Mapping[str, Any]]
    ) -> int:
        """Write daily-factor candidates; publication remains a separate operation."""
        values = [self._factor_row(run_id, formula_version, row) for row in rows]
        if not values:
            return 0
        self.client.execute(
            """
            insert into research_daily_adjustment_factors
                (run_id, formula_version, symbol, trade_date, forward_factor,
                 backward_factor, eligible_event_count, excluded_event_count,
                 quality_status, input_snapshot_at, computed_at)
            values
            """,
            values,
        )
        return len(values)

    def publish_run(
        self,
        run_id: str,
        formula_version: str,
        completed: bool,
        expected_event_count: int | None = None,
        expected_factor_count: int | None = None,
        input_watermark: datetime | None = None,
        base_run_id: str | None | object = _UNSET,
    ) -> None:
        """Publish a fully built run; incomplete candidates are never publishable."""
        if not completed:
            raise ValueError("only completed runs may be published")
        if expected_event_count is None or expected_factor_count is None:
            raise ValueError("candidate counts are required before publication")
        if expected_event_count < 0 or expected_factor_count <= 0:
            raise ValueError(
                "candidate event count must be non-negative and candidate factor count must be greater than zero"
            )
        # ClickHouse has no compare-and-swap insert.  The deployment currently
        # has one scheduler host, so an advisory file lock serializes the final
        # current-run check and insert across its processes.  Multi-host
        # scheduling must replace this with a shared coordinator before use.
        with self._publication_lock(formula_version):
            if base_run_id is not _UNSET:
                current = self.current_run(formula_version)
                if (current or {}).get("run_id") != base_run_id:
                    raise ValueError("published run changed during candidate build; refusing stale publication")

            actual_event_count = self._candidate_count(
                "research_adjustment_events", run_id, formula_version
            )
            actual_factor_count = self._candidate_count(
                "research_daily_adjustment_factors", run_id, formula_version
            )
            if (actual_event_count, actual_factor_count) != (expected_event_count, expected_factor_count):
                raise ValueError(
                    "candidate counts do not match expected publication counts: "
                    f"events={actual_event_count}/{expected_event_count}, "
                    f"factors={actual_factor_count}/{expected_factor_count}"
                )
            self.client.execute(
                """
                insert into research_adjustment_runs
                    (run_id, formula_version, status, published_at, input_watermark)
                values
                """,
                [(run_id, formula_version, "published", datetime.now(), input_watermark)],
            )

    @contextmanager
    def _publication_lock(self, formula_version: str):
        safe_version = "".join(character if character.isalnum() else "_" for character in formula_version)
        lock_path = self._lock_directory / f"research-adjustment-publish-{safe_version}.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _candidate_count(self, table: str, run_id: str, formula_version: str) -> int:
        rows = self.client.execute(
            f"""
            select count()
            from {table}
            where run_id = %(run_id)s and formula_version = %(formula_version)s
            """,
            {"run_id": run_id, "formula_version": formula_version},
        )
        return int(rows[0][0]) if rows else 0

    def current_run(self, formula_version: str) -> dict[str, Any] | None:
        """Return the newest published run for a formula, never a candidate run."""
        rows = self.client.execute(
            """
            select run_id, formula_version, published_at, input_watermark
            from research_adjustment_runs final
            where formula_version = %(formula_version)s and status = 'published'
            order by published_at desc, run_id desc
            limit 1
            """,
            {"formula_version": formula_version},
        )
        if not rows:
            return None
        run_id, version, published_at, input_watermark = rows[0]
        return {
            "run_id": str(run_id), "formula_version": str(version), "published_at": published_at,
            "input_watermark": input_watermark,
        }

    @staticmethod
    def _event_row(run_id: str, formula_version: str, row: Mapping[str, Any]) -> tuple[Any, ...]:
        event_date = _as_date(row["event_date"])
        now = datetime.now()
        validation_status = _validation_status(row)
        return (
            run_id, formula_version, str(row["symbol"]), event_date,
            _optional_int(row.get("category")), str(row.get("name") or row.get("event_name") or ""),
            validation_status,
            _optional_float(row.get("ratio")), _optional_float(row.get("theoretical_price")),
            _optional_float(row.get("pre_close")), _optional_float(row.get("ex_close")),
            _optional_float(row.get("error") if "error" in row else row.get("validation_error")),
            json.dumps(dict(row), ensure_ascii=False, default=_json_default, sort_keys=True), now,
        )

    @staticmethod
    def _factor_row(run_id: str, formula_version: str, row: Mapping[str, Any]) -> tuple[Any, ...]:
        snapshot = row.get("input_snapshot_at")
        return (
            run_id, formula_version, str(row["symbol"]), _as_date(row["trade_date"]),
            _optional_float(row.get("forward_factor")), _optional_float(row.get("backward_factor")),
            int(row.get("eligible_event_count") or 0), int(row.get("excluded_event_count") or 0),
            str(row.get("quality_status") or "unverified"), _as_datetime(snapshot) if snapshot else None,
            datetime.now(),
        )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _as_datetime(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _validation_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("status") or row.get("validation_status") or "unverified")
    if status not in VALIDATION_STATUSES:
        raise ValueError(f"invalid validation status: {status}")
    return status


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
