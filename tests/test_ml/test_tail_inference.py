from __future__ import annotations

import joblib
import pandas as pd

from src.ml.tail_inference import TailModelInference
from src.ml.tail_model import DEFAULT_FEATURE_COLUMNS


def test_tail_model_inference_scores_feature_rows(tmp_path) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump(
        {
            "version": "tail-test-001",
            "feature_columns": DEFAULT_FEATURE_COLUMNS,
            "models": {
                "hit": ConstantProbabilityModel(0.7),
                "risk": ConstantProbabilityModel(0.2),
                "high": ConstantReturnModel(0.025),
            },
        },
        model_path,
    )
    rows = pd.DataFrame([{column: 0.01 for column in DEFAULT_FEATURE_COLUMNS}])
    rows["symbol"] = ["000001.SZ"]

    scored = TailModelInference(model_path).score(rows)

    assert scored[0]["symbol"] == "000001.SZ"
    assert scored[0]["model_version"] == "tail-test-001"
    assert scored[0]["hit_probability"] == 0.7
    assert scored[0]["risk_probability"] == 0.2
    assert scored[0]["expected_high_return"] == 0.025
    assert scored[0]["model_score"] == 0.625


class ConstantProbabilityModel:
    def __init__(self, probability: float) -> None:
        self.probability = probability

    def predict_proba(self, frame):
        return [[1 - self.probability, self.probability] for _ in range(len(frame))]


class ConstantReturnModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, frame):
        return [self.value for _ in range(len(frame))]
