from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategy.factors.timesfm import TimesFMReturnForecastFactor


class RecordingForecaster:
    def __init__(self) -> None:
        self.inputs: list[np.ndarray] = []

    def forecast(
        self,
        *,
        horizon: int,
        inputs: list[np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        self.inputs = [arr.copy() for arr in inputs]
        point = np.full((len(inputs), horizon), 0.01, dtype=np.float32)
        quantiles = np.zeros((len(inputs), horizon, 10), dtype=np.float32)
        quantiles[:, :, 1] = -0.02
        quantiles[:, :, 9] = 0.04
        return point, quantiles


def _bars(closes: list[float], symbol: str = "000001.SZ") -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=len(closes))
    rows = [
        {
            "date": d,
            "symbol": symbol,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
            "adjusted_close": close,
        }
        for d, close in zip(dates, closes)
    ]
    return pd.DataFrame(rows).set_index(["date", "symbol"])


def test_timesfm_factor_forecasts_forward_returns_from_past_context() -> None:
    forecaster = RecordingForecaster()
    bars = _bars([100.0, 101.0, 103.0, 106.0, 110.0])

    factor = TimesFMReturnForecastFactor(
        forecaster=forecaster,
        context_window=3,
        min_history=2,
        horizon=2,
    )
    result = factor.compute(bars)

    valid = result["timesfm_return_forecast"].dropna()
    assert valid.index.tolist() == [
        (pd.Timestamp("2025-01-03"), "000001.SZ"),
        (pd.Timestamp("2025-01-06"), "000001.SZ"),
        (pd.Timestamp("2025-01-07"), "000001.SZ"),
    ]
    expected_cumulative_return = np.expm1(0.02)
    assert np.allclose(valid.to_numpy(), expected_cumulative_return)
    assert np.allclose(
        forecaster.inputs[0],
        np.diff(np.log(np.array([100.0, 101.0, 103.0], dtype=np.float32))),
        atol=1e-6,
    )
    assert np.allclose(
        forecaster.inputs[-1],
        np.diff(np.log(np.array([103.0, 106.0, 110.0], dtype=np.float32))),
        atol=1e-6,
    )


def test_timesfm_factor_exposes_uncertainty_and_confidence_features() -> None:
    forecaster = RecordingForecaster()
    bars = _bars([100.0, 101.0, 103.0, 106.0])
    factor = TimesFMReturnForecastFactor(
        forecaster=forecaster,
        context_window=4,
        min_history=2,
        horizon=1,
    )

    features = factor.compute_features(bars)

    last = features.dropna().iloc[-1]
    assert np.isclose(last["timesfm_return_forecast"], np.expm1(0.01))
    assert np.isclose(last["timesfm_uncertainty"], 0.06)
    assert np.isclose(
        last["timesfm_confidence"],
        last["timesfm_return_forecast"] / last["timesfm_uncertainty"],
    )
