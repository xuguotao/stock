"""Promotion gate and registry for tail-session ML models."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal

ModelStatus = Literal["candidate", "promoted", "rejected"]


def evaluate_promotion_gate(
    *,
    model_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
    audit_status: dict[str, Any],
    min_selected_days: int = 30,
    max_drawdown_deterioration: float = 0.005,
) -> dict[str, Any]:
    """Return promotion eligibility relative to the current rule baseline."""
    reasons: list[str] = []
    if int(model_metrics.get("selected_days") or 0) < min_selected_days:
        reasons.append(f"selected_days_below_{min_selected_days}")
    if _number(model_metrics.get("hit_next_high_1pct_rate")) <= _number(baseline_metrics.get("next_high_hit_1pct_rate")):
        reasons.append("hit_rate_not_above_baseline")
    if _number(model_metrics.get("avg_next_high_return")) <= _number(baseline_metrics.get("avg_next_high_return")):
        reasons.append("avg_high_return_not_above_baseline")
    model_drawdown = _number(model_metrics.get("avg_next_low_drawdown"))
    baseline_drawdown = _number(baseline_metrics.get("avg_next_low_drawdown"))
    if model_drawdown < baseline_drawdown - max_drawdown_deterioration:
        reasons.append("drawdown_worse_than_baseline")
    if audit_status.get("status") == "blocked":
        reasons.append("data_audit_blocked")
    eligible = not reasons
    return {"eligible": eligible, "status": "promoted" if eligible else "rejected", "reasons": reasons}


class ModelRegistry:
    """Small in-memory registry; persistence can wrap this contract later."""

    def __init__(self) -> None:
        self._models: dict[str, dict[str, Any]] = {}

    def register(
        self,
        *,
        version: str,
        metrics: dict[str, Any],
        feature_columns: list[str],
        status: ModelStatus = "candidate",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "version": version,
            "status": status,
            "metrics": deepcopy(metrics),
            "feature_columns": list(feature_columns),
            "metadata": deepcopy(metadata or {}),
            "registered_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._models[version] = record
        if status == "promoted":
            self.promote(version)
        return deepcopy(self._models[version])

    def promote(self, version: str) -> dict[str, Any]:
        if version not in self._models:
            raise KeyError(f"unknown model version: {version}")
        for record in self._models.values():
            if record["status"] == "promoted":
                record["status"] = "candidate"
        self._models[version]["status"] = "promoted"
        return deepcopy(self._models[version])

    def reject(self, version: str, *, reasons: list[str] | None = None) -> dict[str, Any]:
        if version not in self._models:
            raise KeyError(f"unknown model version: {version}")
        self._models[version]["status"] = "rejected"
        self._models[version]["rejection_reasons"] = list(reasons or [])
        return deepcopy(self._models[version])

    def get(self, version: str) -> dict[str, Any]:
        return deepcopy(self._models[version])

    def list(self) -> list[dict[str, Any]]:
        return [deepcopy(record) for record in self._models.values()]

    def promoted(self) -> dict[str, Any] | None:
        for record in self._models.values():
            if record["status"] == "promoted":
                return deepcopy(record)
        return None


def register_evaluated_model(
    registry: ModelRegistry,
    *,
    version: str,
    model_result: dict[str, Any],
    baseline_report: dict[str, Any],
    audit_status: dict[str, Any],
    top_n: int = 2,
) -> dict[str, Any]:
    baseline_metrics = _baseline_metrics_for_top_n(baseline_report, top_n=top_n)
    decision = evaluate_promotion_gate(
        model_metrics=dict(model_result.get("metrics") or {}),
        baseline_metrics=baseline_metrics,
        audit_status=audit_status,
    )
    record = registry.register(
        version=version,
        metrics=dict(model_result.get("metrics") or {}),
        feature_columns=list(model_result.get("feature_columns") or []),
        status="candidate",
        metadata={
            "top_n": top_n,
            "promotion_decision": decision,
            "baseline_metrics": baseline_metrics,
            "audit_status": deepcopy(audit_status),
        },
    )
    if decision["eligible"]:
        record = registry.promote(version)
    else:
        record = registry.reject(version, reasons=list(decision["reasons"]))
    record["promotion_decision"] = decision
    record["baseline_metrics"] = baseline_metrics
    return record


def _baseline_metrics_for_top_n(baseline_report: dict[str, Any], *, top_n: int) -> dict[str, Any]:
    rows = list(baseline_report.get("by_top_n") or [])
    for row in rows:
        if int(row.get("top_n") or 0) == top_n:
            return deepcopy(row)
    return deepcopy(rows[0]) if rows else {}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
