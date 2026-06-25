"""First-pass walk-forward model training for tail-session samples."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

DEFAULT_FEATURE_COLUMNS = [
    "daily_ret_5",
    "daily_ret_10",
    "daily_ret_20",
    "daily_volatility_20",
    "ma5_distance",
    "ma20_distance",
    "avg_amount_20",
    "tail_return_from_1430",
    "tail_high_return_from_1430",
    "tail_pullback_from_high",
    "tail_volume_ratio",
    "last3_close_slope",
    "last6_close_slope",
]


def train_tail_model_walk_forward(
    samples: pd.DataFrame,
    *,
    feature_columns: list[str] | None = None,
    train_days: int = 60,
    validation_days: int = 10,
    top_n: int = 2,
) -> dict[str, Any]:
    features = feature_columns or DEFAULT_FEATURE_COLUMNS
    frame = _prepared_samples(samples, features)
    trade_dates = sorted(frame["trade_date"].unique()) if not frame.empty else []
    if len(trade_dates) < train_days + validation_days:
        return {
            "status": "blocked",
            "reason": "not_enough_history",
            "sample_count": int(len(samples)),
            "feature_columns": features,
            "fold_count": 0,
            "predictions": [],
            "metrics": {},
        }

    predictions: list[dict[str, Any]] = []
    fold_count = 0
    for validation_start in range(train_days, len(trade_dates), validation_days):
        train_window = trade_dates[validation_start - train_days:validation_start]
        validation_window = trade_dates[validation_start:validation_start + validation_days]
        if len(validation_window) < validation_days:
            break
        train_frame = frame[frame["trade_date"].isin(train_window)]
        validation_frame = frame[frame["trade_date"].isin(validation_window)]
        if train_frame.empty or validation_frame.empty or train_frame["hit_next_high_1pct"].nunique() < 2:
            continue
        models = _fit_models(train_frame, features)
        fold_predictions = _predict_frame(validation_frame, models=models, features=features)
        predictions.extend(fold_predictions)
        fold_count += 1

    return {
        "status": "ready" if predictions else "blocked",
        "reason": None if predictions else "no_valid_folds",
        "sample_count": int(len(frame)),
        "feature_columns": features,
        "fold_count": fold_count,
        "predictions": predictions,
        "metrics": _top_n_metrics(pd.DataFrame(predictions), top_n=top_n),
    }


def _prepared_samples(samples: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    if samples.empty:
        return pd.DataFrame()
    required = [
        "trade_date",
        "symbol",
        "next_high_return",
        "next_low_return",
        "hit_next_high_1pct",
        "drawdown_breach_2pct",
        *features,
    ]
    frame = samples.copy()
    for column in required:
        if column not in frame:
            frame[column] = 0
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    for column in [*features, "next_high_return", "next_low_return"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["hit_next_high_1pct"] = frame["hit_next_high_1pct"].astype(bool)
    frame["drawdown_breach_2pct"] = frame["drawdown_breach_2pct"].astype(bool)
    return frame.dropna(subset=[*features, "next_high_return", "next_low_return"])


def _fit_models(train_frame: pd.DataFrame, features: list[str]) -> dict[str, Any]:
    x_train = train_frame[features]
    hit_model = HistGradientBoostingClassifier(random_state=7, max_iter=80).fit(x_train, train_frame["hit_next_high_1pct"])
    risk_model = HistGradientBoostingClassifier(random_state=11, max_iter=80).fit(x_train, train_frame["drawdown_breach_2pct"])
    high_model = HistGradientBoostingRegressor(random_state=13, max_iter=80).fit(x_train, train_frame["next_high_return"])
    return {"hit": hit_model, "risk": risk_model, "high": high_model}


def _predict_frame(validation_frame: pd.DataFrame, *, models: dict[str, Any], features: list[str]) -> list[dict[str, Any]]:
    x_validation = validation_frame[features]
    hit_probability = models["hit"].predict_proba(x_validation)[:, 1]
    risk_probability = models["risk"].predict_proba(x_validation)[:, 1]
    expected_high = models["high"].predict(x_validation)
    high_rank = pd.Series(expected_high).rank(pct=True).to_numpy()
    scores = hit_probability * 0.45 + high_rank * 0.35 - risk_probability * 0.20
    rows = []
    for index, (_row_index, row) in enumerate(validation_frame.iterrows()):
        rows.append(
            {
                "trade_date": row["trade_date"].isoformat(),
                "symbol": str(row["symbol"]),
                "model_score": float(scores[index]),
                "hit_probability": float(hit_probability[index]),
                "expected_high_return": float(expected_high[index]),
                "risk_probability": float(risk_probability[index]),
                "next_high_return": float(row["next_high_return"]),
                "next_low_return": float(row["next_low_return"]),
                "hit_next_high_1pct": bool(row["hit_next_high_1pct"]),
                "drawdown_breach_2pct": bool(row["drawdown_breach_2pct"]),
            }
        )
    return rows


def _top_n_metrics(predictions: pd.DataFrame, *, top_n: int) -> dict[str, Any]:
    if predictions.empty:
        return {
            "selected_days": 0,
            "selected_rows": 0,
            "hit_next_high_1pct_rate": 0.0,
            "avg_expected_high_return": 0.0,
            "avg_next_high_return": 0.0,
            "avg_next_low_drawdown": 0.0,
            "drawdown_breach_2pct_rate": 0.0,
        }
    selected = predictions.sort_values(["trade_date", "model_score", "symbol"], ascending=[True, False, True]).groupby("trade_date", group_keys=False).head(top_n)
    return {
        "selected_days": int(selected["trade_date"].nunique()),
        "selected_rows": int(len(selected)),
        "hit_next_high_1pct_rate": float(selected["hit_next_high_1pct"].astype(bool).mean()),
        "avg_expected_high_return": float(selected["expected_high_return"].mean()),
        "avg_next_high_return": float(selected["next_high_return"].mean()),
        "avg_next_low_drawdown": float(selected["next_low_return"].mean()),
        "drawdown_breach_2pct_rate": float(selected["drawdown_breach_2pct"].astype(bool).mean()),
    }
