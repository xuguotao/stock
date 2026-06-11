"""TimesFM-backed return forecast factor.

The real TimesFM model is optional and loaded lazily. Tests and offline research
can inject any object exposing the same forecast method.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import pandas as pd

from src.strategy.base import Factor


class ReturnForecaster(Protocol):
    def forecast(
        self,
        *,
        horizon: int,
        inputs: list[np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Forecast future log returns for each input context."""


class LazyTimesFMForecaster:
    """Small adapter around the optional ``timesfm`` package."""

    def __init__(
        self,
        model_id: str = "google/timesfm-2.5-200m-pytorch",
        max_context: int = 1024,
        max_horizon: int = 5,
        per_core_batch_size: int = 32,
    ) -> None:
        self.model_id = model_id
        self.max_context = max_context
        self.max_horizon = max_horizon
        self.per_core_batch_size = per_core_batch_size
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        import torch
        import timesfm

        torch.set_float32_matmul_precision("high")
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(self.model_id)
        model.compile(
            timesfm.ForecastConfig(
                max_context=self.max_context,
                max_horizon=self.max_horizon,
                normalize_inputs=True,
                per_core_batch_size=self.per_core_batch_size,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=False,
                fix_quantile_crossing=True,
            )
        )
        self._model = model
        return model

    def forecast(
        self,
        *,
        horizon: int,
        inputs: list[np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        return self._load_model().forecast(horizon=horizon, inputs=inputs)


class TimesFMReturnForecastFactor(Factor):
    """Forecast future cumulative log return with TimesFM.

    Higher values mean the model expects a higher forward return. The factor
    feeds log returns, not raw prices, so the signal is closer to a stationary
    cross-sectional ranking input.
    """

    name = "timesfm_return_forecast"
    description = "TimesFM forecast of future cumulative return"

    def __init__(
        self,
        forecaster: ReturnForecaster | None = None,
        context_window: int = 512,
        min_history: int = 32,
        horizon: int = 1,
        price_col: str = "close",
    ) -> None:
        if context_window < 2:
            raise ValueError("context_window must be at least 2 prices")
        if min_history < 1:
            raise ValueError("min_history must be positive")
        if horizon < 1:
            raise ValueError("horizon must be positive")

        self.forecaster = forecaster
        self.context_window = context_window
        self.min_history = min_history
        self.horizon = horizon
        self.price_col = price_col

    def compute(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute the single-column factor expected by strategy code."""
        return self.compute_features(bars, **kwargs)[[self.name]]

    def compute_features(self, bars: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Compute forecast, uncertainty, and confidence feature columns."""
        if bars.empty:
            return pd.DataFrame(
                columns=[self.name, "timesfm_uncertainty", "timesfm_confidence"]
            )

        price_col = kwargs.get("price_col", self.price_col)
        if price_col not in bars.columns:
            raise KeyError(f"bars must contain '{price_col}' column")

        horizon = int(kwargs.get("horizon", self.horizon))
        context_window = int(kwargs.get("context_window", self.context_window))
        min_history = int(kwargs.get("min_history", self.min_history))

        result = pd.DataFrame(
            np.nan,
            index=bars.index,
            columns=[self.name, "timesfm_uncertainty", "timesfm_confidence"],
            dtype=float,
        )
        contexts: list[np.ndarray] = []
        targets: list[tuple[pd.Timestamp, str]] = []

        for symbol, symbol_bars in bars.sort_index().groupby(level="symbol"):
            prices = symbol_bars[price_col].astype(float).to_numpy()
            dates = symbol_bars.index.get_level_values("date")
            if len(prices) < min_history + 1:
                continue

            log_prices = np.log(prices)
            log_returns = np.diff(log_prices)
            for price_pos in range(1, len(prices)):
                end_return_pos = price_pos
                start_price_pos = max(0, price_pos - context_window + 1)
                context = log_returns[start_price_pos:end_return_pos]
                if len(context) < min_history:
                    continue
                contexts.append(context.astype(np.float32))
                targets.append((pd.Timestamp(dates[price_pos]), str(symbol)))

        if not contexts:
            return result

        point, quantiles = self._forecaster().forecast(
            horizon=horizon,
            inputs=contexts,
        )
        point = np.asarray(point, dtype=float)
        quantiles = np.asarray(quantiles, dtype=float)

        cumulative_log_return = point[:, :horizon].sum(axis=1)
        expected_return = np.expm1(cumulative_log_return)
        uncertainty = self._interval_width(quantiles, horizon)
        confidence = np.divide(
            expected_return,
            uncertainty,
            out=np.full_like(expected_return, np.nan, dtype=float),
            where=uncertainty > 0,
        )

        for idx, key in enumerate(targets):
            result.loc[key, self.name] = expected_return[idx]
            result.loc[key, "timesfm_uncertainty"] = uncertainty[idx]
            result.loc[key, "timesfm_confidence"] = confidence[idx]

        return result

    def _forecaster(self) -> ReturnForecaster:
        if self.forecaster is None:
            self.forecaster = LazyTimesFMForecaster(
                max_context=self.context_window,
                max_horizon=self.horizon,
            )
        return self.forecaster

    @staticmethod
    def _interval_width(quantiles: np.ndarray, horizon: int) -> np.ndarray:
        if quantiles.ndim != 3 or quantiles.shape[2] < 10:
            return np.full(quantiles.shape[0], np.nan, dtype=float)

        q10 = quantiles[:, :horizon, 1].sum(axis=1)
        q90 = quantiles[:, :horizon, 9].sum(axis=1)
        return np.round(q90 - q10, 12)
