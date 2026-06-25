from __future__ import annotations

from src.ml.tail_model_registry import ModelRegistry, evaluate_promotion_gate, register_evaluated_model


def test_evaluate_promotion_gate_promotes_model_that_beats_rule_baseline() -> None:
    decision = evaluate_promotion_gate(
        model_metrics={
            "selected_days": 35,
            "hit_next_high_1pct_rate": 0.62,
            "avg_next_high_return": 0.026,
            "avg_next_low_drawdown": -0.014,
        },
        baseline_metrics={
            "selected_days": 35,
            "next_high_hit_1pct_rate": 0.55,
            "avg_next_high_return": 0.019,
            "avg_next_low_drawdown": -0.012,
        },
        audit_status={"status": "ready", "issues": []},
    )

    assert decision == {
        "eligible": True,
        "status": "promoted",
        "reasons": [],
    }


def test_evaluate_promotion_gate_rejects_weak_or_blocked_model() -> None:
    decision = evaluate_promotion_gate(
        model_metrics={
            "selected_days": 12,
            "hit_next_high_1pct_rate": 0.50,
            "avg_next_high_return": 0.010,
            "avg_next_low_drawdown": -0.030,
        },
        baseline_metrics={
            "selected_days": 35,
            "next_high_hit_1pct_rate": 0.55,
            "avg_next_high_return": 0.019,
            "avg_next_low_drawdown": -0.012,
        },
        audit_status={"status": "blocked", "issues": ["daily_kline_missing"]},
    )

    assert decision["eligible"] is False
    assert decision["status"] == "rejected"
    assert "selected_days_below_30" in decision["reasons"]
    assert "hit_rate_not_above_baseline" in decision["reasons"]
    assert "avg_high_return_not_above_baseline" in decision["reasons"]
    assert "drawdown_worse_than_baseline" in decision["reasons"]
    assert "data_audit_blocked" in decision["reasons"]


def test_model_registry_promotes_only_one_model_at_a_time() -> None:
    registry = ModelRegistry()

    first = registry.register(
        version="model-a",
        metrics={"selected_days": 40},
        feature_columns=["tail_return_from_1430"],
        status="candidate",
    )
    second = registry.register(
        version="model-b",
        metrics={"selected_days": 42},
        feature_columns=["tail_volume_ratio"],
        status="candidate",
    )

    registry.promote(first["version"])
    registry.promote(second["version"])

    assert registry.get("model-a")["status"] == "candidate"
    assert registry.get("model-b")["status"] == "promoted"
    assert registry.promoted()["version"] == "model-b"


def test_register_evaluated_model_applies_gate_and_records_comparison() -> None:
    registry = ModelRegistry()

    record = register_evaluated_model(
        registry,
        version="walk-forward-001",
        model_result={
            "metrics": {
                "selected_days": 40,
                "hit_next_high_1pct_rate": 0.66,
                "avg_next_high_return": 0.031,
                "avg_next_low_drawdown": -0.010,
            },
            "feature_columns": ["tail_return_from_1430", "tail_volume_ratio"],
        },
        baseline_report={
            "by_top_n": [
                {
                    "top_n": 2,
                    "selected_days": 40,
                    "next_high_hit_1pct_rate": 0.58,
                    "avg_next_high_return": 0.022,
                    "avg_next_low_drawdown": -0.012,
                }
            ]
        },
        audit_status={"status": "ready", "issues": []},
        top_n=2,
    )

    assert record["status"] == "promoted"
    assert record["promotion_decision"]["eligible"] is True
    assert record["baseline_metrics"]["top_n"] == 2
    assert registry.promoted()["version"] == "walk-forward-001"
