"""Load promoted tail-session model artifacts and score feature rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


class TailModelInference:
    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        self.payload: dict[str, Any] = joblib.load(self.model_path)
        self.feature_columns = list(self.payload["feature_columns"])
        self.models = dict(self.payload["models"])
        self.version = str(self.payload.get("version") or self.model_path.parent.name)

    def score(self, rows: pd.DataFrame) -> list[dict[str, Any]]:
        if rows.empty:
            return []
        frame = rows.copy()
        for column in self.feature_columns:
            if column not in frame:
                frame[column] = 0.0
        x_frame = frame[self.feature_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        hit_probability = np.asarray(self.models["hit"].predict_proba(x_frame))[:, 1]
        risk_probability = np.asarray(self.models["risk"].predict_proba(x_frame))[:, 1]
        expected_high_return = np.asarray(self.models["high"].predict(x_frame))
        high_rank = pd.Series(expected_high_return).rank(pct=True).to_numpy()
        model_score = hit_probability * 0.45 + high_rank * 0.35 - risk_probability * 0.20
        scored = []
        for index, (_row_index, row) in enumerate(frame.iterrows()):
            feature_values = x_frame.iloc[index]
            scored.append(
                {
                    "symbol": str(row.get("symbol") or ""),
                    "model_version": self.version,
                    "model_score": round(float(model_score[index]), 6),
                    "hit_probability": round(float(hit_probability[index]), 6),
                    "expected_high_return": round(float(expected_high_return[index]), 6),
                    "risk_probability": round(float(risk_probability[index]), 6),
                    "feature_snapshot": [
                        {"feature": column, "value": round(float(feature_values[column]), 6)}
                        for column in self.feature_columns
                    ],
                }
            )
        return scored
