"""Persist versioned, research-only corporate-action adjustment results."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence

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


class ResearchAdjustmentStore:
    """Store candidate adjustment results and publish complete runs atomically by version.

    Candidate event and factor rows are deliberately keyed by ``run_id``.  Readers
    must resolve a run through :meth:`current_run`, which only returns published
    runs, so partial or failed work is never selected as research input.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

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
            order by (formula_version, run_id, symbol, event_date, category, event_name)
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
                published_at DateTime
            ) engine = ReplacingMergeTree(published_at)
            order by (formula_version, run_id)
            """
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

    def publish_run(self, run_id: str, formula_version: str, completed: bool) -> None:
        """Publish a fully built run; incomplete candidates are never publishable."""
        if not completed:
            raise ValueError("only completed runs may be published")
        self.client.execute(
            """
            insert into research_adjustment_runs
                (run_id, formula_version, status, published_at)
            values
            """,
            [(run_id, formula_version, "published", datetime.now())],
        )

    def current_run(self, formula_version: str) -> dict[str, Any] | None:
        """Return the newest published run for a formula, never a candidate run."""
        rows = self.client.execute(
            """
            select run_id, formula_version, published_at
            from research_adjustment_runs final
            where formula_version = %(formula_version)s and status = 'published'
            order by published_at desc, run_id desc
            limit 1
            """,
            {"formula_version": formula_version},
        )
        if not rows:
            return None
        run_id, version, published_at = rows[0]
        return {"run_id": str(run_id), "formula_version": str(version), "published_at": published_at}

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
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))


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
