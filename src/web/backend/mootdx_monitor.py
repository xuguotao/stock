"""Read-only monitoring snapshot for mootdx data operations."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data_ops.mootdx_tasks import MOOTDX_TASK_BY_KEY, MOOTDX_TASK_DEFINITIONS


class MootdxMonitorService:
    def __init__(self, *, repository: Any, client: Any | None = None) -> None:
        self._repository = repository
        self._source = None if client is not None else ClickHouseStockDataSource()
        self._client = client
        # Monitoring endpoints are polled concurrently by the page and must not share a query in flight.
        self._lock = threading.RLock()

    def snapshot(self, *, audit_limit: int = 50) -> dict[str, Any]:
        return {
            "tasks": self._tasks(),
            "audits": self._audits(limit=audit_limit),
            "health": self._health(),
        }

    def _tasks(self) -> list[dict[str, Any]]:
        task_store_error = ""
        try:
            statuses = {status.task_key: status for status in self._repository.list_task_statuses()}
        except Exception as exc:  # noqa: BLE001 - definitions remain manageable during task-store outages.
            statuses = {}
            task_store_error = f"{type(exc).__name__}: {exc}"
        items = []
        for definition in MOOTDX_TASK_DEFINITIONS:
            status = statuses.get(definition.task_key)
            items.append({
                "task_key": definition.task_key,
                "label": definition.label,
                "description": definition.description,
                "sync_task": definition.sync_task,
                "daily_reconcile": definition.daily_reconcile,
                "enabled": bool(status.enabled) if status else definition.enabled,
                "status": status.status if status else "unavailable",
                "schedule_kind": status.schedule_kind if status else definition.schedule_kind,
                "schedule_config": status.schedule_config if status else definition.schedule_config,
                "max_runtime_seconds": _config_value(status, "max_runtime_seconds", definition.max_runtime_seconds),
                "stale_after_seconds": _config_value(status, "stale_after_seconds", definition.stale_after_seconds),
                "last_started_at": _iso(status.last_started_at) if status else None,
                "last_finished_at": _iso(status.last_finished_at) if status else None,
                "heartbeat_at": _iso(status.heartbeat_at) if status else None,
                "last_result": status.last_result if status else {},
                "last_error": status.last_error if status else task_store_error,
                "progress": {
                    "percent": status.progress_percent if status else None,
                    "stage": status.progress_stage if status else None,
                    "message": status.progress_message if status else None,
                },
            })
        return items

    def _audits(self, *, limit: int) -> list[dict[str, Any]]:
        rows = self._safe_query(
            "select run_id, task_key, started_at, finished_at, status, params_json, result_json, error "
            "from mootdx_sync_runs where task_key in %(task_keys)s order by started_at desc limit %(limit)s",
            {
                "task_keys": tuple({*(definition.sync_task for definition in MOOTDX_TASK_DEFINITIONS), "mootdx_offline_sync"}),
                "limit": max(1, min(limit, 200)),
            },
        )
        if isinstance(rows, dict):
            return [{"status": "unavailable", "error": rows["error"]}]
        return [_audit_record(row, include_diagnostics=False) for row in rows]

    def audit_detail(self, run_id: str) -> dict[str, Any] | None:
        rows = self._safe_query(
            "select run_id, task_key, started_at, finished_at, status, params_json, result_json, error "
            "from mootdx_sync_runs where run_id = %(run_id)s order by started_at desc limit 1",
            {"run_id": run_id},
        )
        if isinstance(rows, dict) or not rows:
            return None
        return _audit_record(rows[0], include_diagnostics=True)

    def _health(self) -> dict[str, Any]:
        catalog = self._safe_query("select uniqExact(symbol), max(captured_at) from mootdx_stock_catalog final where is_active = 1")
        daily = self._safe_query(
            "select trade_date, uniqExact(symbol) from mootdx_stock_kline "
            "where frequency = 'daily' and trade_date = (select max(trade_date) from mootdx_stock_kline where frequency = 'daily') "
            "group by trade_date"
        )
        symbol_status = self._safe_query(
            "select status, count() from (select symbol, argMax(status, last_checked_at) as status "
            "from mootdx_symbol_data_status where data_kind = 'stock_kline_daily' group by symbol) group by status order by status"
        )
        return {
            "catalog": _health_item(catalog, lambda rows: {"symbols": int(rows[0][0]), "captured_at": _iso(rows[0][1])}),
            "daily": _health_item(daily, lambda rows: {"trade_date": _iso(rows[0][0]), "symbols": int(rows[0][1])}),
            "symbol_status": _health_item(symbol_status, lambda rows: {str(row[0]): int(row[1]) for row in rows}),
        }

    def _safe_query(self, query: str, params: dict[str, Any] | None = None) -> list[tuple] | dict[str, str]:
        try:
            with self._lock:
                return self._clickhouse().execute(query, params)
        except Exception as exc:  # noqa: BLE001 - monitor must expose partial health during outages.
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _clickhouse(self) -> Any:
        if self._client is None:
            self._client = self._source._client_instance()
        return self._client


def _config_value(status: Any | None, name: str, default: int) -> int:
    return int(getattr(status, name, default)) if status is not None and hasattr(status, name) else default


def _audit_record(row: tuple, *, include_diagnostics: bool) -> dict[str, Any]:
    params = _json_object(row[5])
    result = _json_object(row[6])
    diagnostics = _json_object(result.get("diagnostics"))
    task_key = str(row[1])
    sync_task = _source_task_key(task_key, params)
    task_diagnostics = _json_object(diagnostics.get(sync_task))
    audit = _json_object(task_diagnostics.get("audit")) or _legacy_audit(sync_task, task_diagnostics)
    audit = _normalize_daily_reconciliation_audit(
        audit,
        task_key=sync_task,
        params=params,
        diagnostics=task_diagnostics,
    )
    payload = {
        "run_id": str(row[0]),
        "task_key": task_key,
        "task_label": _audit_label(sync_task, params),
        "started_at": _iso(row[2]),
        "finished_at": _iso(row[3]),
        "status": str(row[4]),
        "duration_seconds": result.get("duration_seconds"),
        "inserted": result.get("inserted") or {},
        "audit": audit or {"status": "unknown", "reasons": []},
        "error": str(row[7] or ""),
    }
    if include_diagnostics:
        payload["diagnostics"] = task_diagnostics
    return payload


def _audit_label(task_key: str, params: dict[str, Any]) -> str:
    if task_key == "stock_catalog":
        return MOOTDX_TASK_BY_KEY["mootdx_stock_catalog_sync"].label
    if task_key == "xdxr":
        return MOOTDX_TASK_BY_KEY["mootdx_xdxr_sync"].label
    if task_key == "stock_universe_profile":
        return MOOTDX_TASK_BY_KEY["stock_universe_profile_refresh"].label
    if params.get("daily_reconcile"):
        return MOOTDX_TASK_BY_KEY["mootdx_daily_kline_reconcile"].label
    return MOOTDX_TASK_BY_KEY["mootdx_daily_kline_sync"].label


def _source_task_key(task_key: str, params: dict[str, Any]) -> str:
    if task_key != "mootdx_offline_sync":
        return task_key
    tasks = params.get("tasks")
    if isinstance(tasks, list) and len(tasks) == 1:
        return str(tasks[0])
    return "mootdx_offline_sync"


def _legacy_audit(task_key: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    if task_key != "stock_kline_daily" or not diagnostics:
        return {"status": "unknown", "reasons": []}
    coverage = float(diagnostics.get("coverage_rate") or 0)
    failed_symbols = int(diagnostics.get("failed_symbols_count") or 0)
    dropped_rows = int(diagnostics.get("dropped_rows") or 0)
    reasons = []
    if coverage < 0.995:
        reasons.append("coverage_below_target")
    if failed_symbols:
        reasons.append("symbol_fetch_failed")
    if dropped_rows:
        reasons.append("invalid_rows_dropped")
    if coverage < 0.98:
        return {"status": "failed", "reasons": reasons}
    return {"status": "degraded" if reasons else "healthy", "reasons": reasons}


def _normalize_daily_reconciliation_audit(
    audit: dict[str, Any],
    *,
    task_key: str,
    params: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """Correct historical reconciliation audits that counted known no-data symbols as failures."""
    if task_key != "stock_kline_daily" or not params.get("daily_reconcile"):
        return audit
    reasons = audit.get("reasons") or []
    target = int(diagnostics.get("target_symbols") or 0)
    requested = int(diagnostics.get("requested_symbols") or 0)
    skipped = int(diagnostics.get("skipped_no_data_symbols_count") or 0)
    if (
        audit.get("status") == "failed"
        and reasons == ["coverage_below_target"]
        and target > 0
        and requested == 0
        and skipped == target
        and int(diagnostics.get("failed_symbols_count") or 0) == 0
        and int(diagnostics.get("dropped_rows") or 0) == 0
    ):
        return {"status": "healthy", "reasons": []}
    return audit


def _health_item(value: list[tuple] | dict[str, str], mapper) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"status": "unavailable", "error": value["error"]}
    if not value:
        return {"status": "unavailable", "error": "no rows"}
    return {"status": "healthy", **mapper(value)}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
