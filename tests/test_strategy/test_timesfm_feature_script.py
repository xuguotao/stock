from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.compute_timesfm_features import compute_timesfm_features


class ConstantForecaster:
    def forecast(
        self,
        *,
        horizon: int,
        inputs: list[np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        point = np.full((len(inputs), horizon), 0.02, dtype=np.float32)
        quantiles = np.zeros((len(inputs), horizon, 10), dtype=np.float32)
        quantiles[:, :, 1] = -0.01
        quantiles[:, :, 9] = 0.03
        return point, quantiles


def test_compute_timesfm_features_returns_non_empty_forecasts() -> None:
    dates = pd.bdate_range("2025-01-01", periods=5)
    bars = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "symbol": ["000001.SZ"] * 5 + ["600519.SH"] * 5,
            "open": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
            "high": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
            "low": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
            "close": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
            "volume": [1_000_000] * 10,
            "amount": [10_000_000] * 10,
            "adjusted_close": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
        }
    ).set_index(["date", "symbol"])

    result = compute_timesfm_features(
        bars,
        forecaster=ConstantForecaster(),
        context_window=3,
        min_history=2,
        horizon=1,
    )

    assert result.index.names == ["date", "symbol"]
    assert result.columns.tolist() == [
        "timesfm_return_forecast",
        "timesfm_uncertainty",
        "timesfm_confidence",
    ]
    assert len(result.dropna()) == 6
