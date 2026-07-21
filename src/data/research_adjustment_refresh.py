"""Fail-closed orchestration and audit for research adjustment refreshes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Callable

from scripts.build_research_adjustment_data import build_research_adjustment_data
from src.data.research_adjustment_store import ResearchAdjustmentStore

def refresh_research_adjustments(*, client: Any, builder: Callable[..., dict[str, Any]] = build_research_adjustment_data) -> dict[str, Any]:
    store = ResearchAdjustmentStore(client=client)
    store.ensure_tables()
    _ensure_audit_table(client)
    current = store.current_run("v1")
    previous = int((current or {}).get("input_ingest_seq") or 0)
    refresh_id = str(uuid.uuid4())
    rows = client.execute(
        """select ingest_seq, task_key, status, run_id from mootdx_ingestion_runs final
        where ingest_seq > %(previous)s and task_key in ('stock_kline_daily', 'xdxr') order by ingest_seq""",
        {"previous": previous},
    )
    statuses = {str(task): str(status) for _, task, status, _ in rows}
    failed = sorted({str(task) for _, task, status, _ in rows if status != "succeeded"})
    if failed:
        reason = "upstream_not_succeeded:" + ",".join(failed)
        return _audit(client, refresh_id, current, previous, "blocked", reason, statuses)
    if not rows:
        return _audit(client, refresh_id, current, previous, "noop", "no_upstream_changes", statuses)
    try:
        result = builder(client=client, formula_version="v1")
    except Exception as exc:  # preserve the last published version
        return _audit(client, refresh_id, current, previous, "failed", str(exc), statuses)
    decision = "published" if result.get("run_id") else "noop"
    return _audit(client, refresh_id, current, previous, decision, "", statuses, result)


def _ensure_audit_table(client: Any) -> None:
    client.execute("""create table if not exists research_adjustment_refresh_audits (
      refresh_id String, attempted_at DateTime, previous_run_id Nullable(String), previous_input_ingest_seq UInt64,
      decision LowCardinality(String), block_reason String, upstream_status String, published_run_id Nullable(String), details_json String
    ) engine=MergeTree order by (attempted_at, refresh_id)""")


def _audit(client: Any, refresh_id: str, current: dict[str, Any] | None, previous: int, decision: str, reason: str, statuses: dict[str, str], result: dict[str, Any] | None = None) -> dict[str, Any]:
    result = result or {}
    payload = {"refresh_id": refresh_id, "decision": decision, "block_reason": reason, "upstream_status": statuses, "published_run_id": result.get("run_id")}
    client.execute("insert into research_adjustment_refresh_audits values", [(refresh_id, datetime.now(), (current or {}).get("run_id"), previous, decision, reason, json.dumps(statuses, sort_keys=True), result.get("run_id"), json.dumps(result, default=str))])
    return payload
