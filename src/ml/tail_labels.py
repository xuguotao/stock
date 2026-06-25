"""Label construction for tail-session ML samples."""

from __future__ import annotations

import pandas as pd


def build_tail_label_frame(*, daily_bars: pd.DataFrame, feature_frame: pd.DataFrame) -> pd.DataFrame:
    """Build next-session return labels for feature rows."""
    if daily_bars.empty or feature_frame.empty:
        return pd.DataFrame()
    daily = daily_bars.copy()
    daily["symbol"] = daily["symbol"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    for column in ["open", "high", "low", "close"]:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
        daily.loc[daily[column] <= 0, column] = pd.NA
    next_rows = []
    for symbol, symbol_daily in daily.sort_values("date").groupby("symbol", sort=True):
        shifted = symbol_daily[["date", "open", "high", "low", "close"]].shift(-1)
        current = symbol_daily[["date"]].copy()
        current["symbol"] = symbol
        current["outcome_date"] = shifted["date"]
        current["next_open"] = shifted["open"]
        current["next_high"] = shifted["high"]
        current["next_low"] = shifted["low"]
        current["next_close"] = shifted["close"]
        next_rows.append(current)
    next_daily = pd.concat(next_rows, ignore_index=True) if next_rows else pd.DataFrame()
    features = feature_frame[["trade_date", "symbol", "decision_time", "entry_price"]].copy()
    labels = features.merge(
        next_daily,
        left_on=["trade_date", "symbol"],
        right_on=["date", "symbol"],
        how="left",
    ).drop(columns=["date"])
    labels["next_open_return"] = _return_series(labels["next_open"], labels["entry_price"])
    labels["next_high_return"] = _return_series(labels["next_high"], labels["entry_price"])
    labels["next_close_return"] = _return_series(labels["next_close"], labels["entry_price"])
    labels["next_low_return"] = _return_series(labels["next_low"], labels["entry_price"])
    labels["hit_next_high_1pct"] = labels["next_high_return"].map(lambda value: pd.NA if pd.isna(value) else bool(value >= 0.01)).astype(object)
    labels["drawdown_breach_2pct"] = labels["next_low_return"].map(lambda value: pd.NA if pd.isna(value) else bool(value <= -0.02)).astype(object)
    return labels[
        [
            "trade_date",
            "symbol",
            "decision_time",
            "outcome_date",
            "next_open",
            "next_high",
            "next_low",
            "next_close",
            "next_open_return",
            "next_high_return",
            "next_close_return",
            "next_low_return",
            "hit_next_high_1pct",
            "drawdown_breach_2pct",
        ]
    ]


def _return_series(value: pd.Series, base: pd.Series) -> pd.Series:
    numeric_value = pd.to_numeric(value, errors="coerce")
    numeric_base = pd.to_numeric(base, errors="coerce")
    result = numeric_value / numeric_base - 1.0
    invalid = numeric_base.isna() | numeric_value.isna() | (numeric_base <= 0) | (numeric_value <= 0)
    return result.mask(invalid, pd.NA)
