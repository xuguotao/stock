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
        daily[column] = pd.to_numeric(daily[column], errors="coerce").fillna(0.0)
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
    labels["next_open_return"] = labels.apply(lambda row: _return(row["next_open"], row["entry_price"]), axis=1)
    labels["next_high_return"] = labels.apply(lambda row: _return(row["next_high"], row["entry_price"]), axis=1)
    labels["next_close_return"] = labels.apply(lambda row: _return(row["next_close"], row["entry_price"]), axis=1)
    labels["next_low_return"] = labels.apply(lambda row: _return(row["next_low"], row["entry_price"]), axis=1)
    labels["hit_next_high_1pct"] = (labels["next_high_return"] >= 0.01).map(bool).astype(object)
    labels["drawdown_breach_2pct"] = (labels["next_low_return"] <= -0.02).map(bool).astype(object)
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


def _return(value: float, base: float) -> float:
    return float(value) / float(base) - 1.0 if base and value else 0.0
