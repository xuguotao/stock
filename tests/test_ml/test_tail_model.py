from __future__ import annotations

from datetime import date, timedelta

import json

import pandas as pd

from src.ml.tail_model import DEFAULT_FEATURE_COLUMNS, train_tail_model_artifact, train_tail_model_walk_forward


def test_train_tail_model_walk_forward_scores_validation_rows_chronologically() -> None:
    samples = _model_samples()

    result = train_tail_model_walk_forward(
        samples,
        train_days=4,
        validation_days=2,
        top_n=1,
    )

    assert result["status"] == "ready"
    assert result["feature_columns"] == DEFAULT_FEATURE_COLUMNS
    assert result["fold_count"] >= 1
    assert result["sample_count"] == len(samples)
    assert result["metrics"]["selected_days"] > 0
    assert result["metrics"]["selected_rows"] == result["metrics"]["selected_days"]
    assert 0 <= result["metrics"]["hit_next_high_1pct_rate"] <= 1
    assert "avg_expected_high_return" in result["metrics"]
    first_prediction = result["predictions"][0]
    assert {
        "trade_date",
        "symbol",
        "model_score",
        "hit_probability",
        "expected_high_return",
        "risk_probability",
    }.issubset(first_prediction)


def test_train_tail_model_walk_forward_blocks_when_not_enough_history() -> None:
    result = train_tail_model_walk_forward(_model_samples().head(3), train_days=4, validation_days=2)

    assert result["status"] == "blocked"
    assert result["reason"] == "not_enough_history"


def test_train_tail_model_artifact_persists_manifest_and_model(tmp_path) -> None:
    artifact = train_tail_model_artifact(
        _model_samples(),
        version="tail-test-001",
        output_root=tmp_path,
        train_days=4,
        validation_days=2,
        top_n=1,
    )

    assert artifact["version"] == "tail-test-001"
    assert artifact["status"] == "ready"
    assert artifact["artifact_dir"] == str(tmp_path / "tail-test-001")
    assert (tmp_path / "tail-test-001" / "manifest.json").exists()
    assert (tmp_path / "tail-test-001" / "model.joblib").exists()
    manifest = json.loads((tmp_path / "tail-test-001" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "tail-test-001"
    assert manifest["feature_columns"] == DEFAULT_FEATURE_COLUMNS
    assert {"market_ret_5", "market_breadth_20", "relative_ret_5"}.issubset(DEFAULT_FEATURE_COLUMNS)
    assert manifest["metrics"]["selected_days"] > 0


def _model_samples() -> pd.DataFrame:
    rows = []
    start = date(2026, 1, 1)
    for day_index in range(10):
        trade_date = start + timedelta(days=day_index)
        for symbol_index in range(4):
            strong = symbol_index == 0
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": f"00000{symbol_index}.SZ",
                    "decision_time": "14:55",
                    "daily_ret_5": 0.01 * symbol_index,
                    "daily_ret_10": 0.01 * symbol_index,
                    "daily_ret_20": 0.01 * symbol_index,
                    "daily_volatility_20": 0.02,
                    "ma5_distance": 0.01,
                    "ma20_distance": 0.02,
                    "avg_amount_20": 20_000_000 + symbol_index,
                    "tail_return_from_1430": 0.025 if strong else -0.002 * symbol_index,
                    "tail_high_return_from_1430": 0.030 if strong else 0.001,
                    "tail_pullback_from_high": -0.001 if strong else -0.02,
                    "tail_volume_ratio": 2.5 if strong else 0.8,
                    "last3_close_slope": 0.012 if strong else -0.004,
                    "last6_close_slope": 0.018 if strong else -0.003,
                    "market_ret_5": 0.004,
                    "market_ret_20": 0.012,
                    "market_breadth_20": 0.55,
                    "relative_ret_5": 0.01 * symbol_index - 0.004,
                    "relative_ret_20": 0.01 * symbol_index - 0.012,
                    "next_open_return": 0.01 if strong else -0.005,
                    "next_high_return": 0.03 if strong else 0.002,
                    "next_low_return": -0.004 if strong else -0.03,
                    "hit_next_high_1pct": strong,
                    "drawdown_breach_2pct": not strong,
                }
            )
    return pd.DataFrame(rows)
