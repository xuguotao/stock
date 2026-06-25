"""Feature construction for tail-session ML samples."""

from __future__ import annotations

from datetime import time
from typing import Iterable

import pandas as pd

from src.core.trading_windows import TAIL_DECISION_TIMES, TAIL_SESSION_START, tail_bar_time_label

DEFAULT_DECISION_TIMES = TAIL_DECISION_TIMES


def build_tail_feature_frame(
    *,
    daily_bars: pd.DataFrame,
    minute5_bars: pd.DataFrame,
    decision_times: Iterable[time] = DEFAULT_DECISION_TIMES,
) -> pd.DataFrame:
    """Build one feature row per symbol/date/decision time without future daily leakage."""
    if daily_bars.empty or minute5_bars.empty:
        return pd.DataFrame()
    daily = _prepare_daily(daily_bars)
    minute5 = _prepare_minute5(minute5_bars)
    decision_values = sorted(_time_label(value) for value in decision_times)
    daily_by_symbol = {
        symbol: symbol_daily.reset_index(drop=True)
        for symbol, symbol_daily in daily.groupby("symbol", sort=True)
    }
    market_by_date = _market_context_by_date(daily_by_symbol)
    rows = []
    for (symbol, trade_date), day_bars in minute5.groupby(["symbol", "trade_date"], sort=True):
        symbol_daily = daily_by_symbol.get(symbol)
        if symbol_daily is None:
            continue
        cutoff = int(symbol_daily["date"].searchsorted(trade_date, side="left"))
        prior_daily = symbol_daily.iloc[:cutoff]
        if len(prior_daily) < 6:
            continue
        day_bars = day_bars.sort_values("datetime")
        tail_bars = day_bars[day_bars["bar_time"] >= tail_bar_time_label(TAIL_SESSION_START)]
        if tail_bars.empty:
            continue
        first_tail_close = float(tail_bars.iloc[0]["close"])
        prior = _daily_features(prior_daily)
        market = market_by_date.get(trade_date, _empty_market_context())
        prior = {
            **prior,
            **market,
            "relative_ret_5": prior["daily_ret_5"] - market["market_ret_5"],
            "relative_ret_20": prior["daily_ret_20"] - market["market_ret_20"],
        }
        for decision_time in decision_values:
            observed = tail_bars[tail_bars["bar_time"] <= decision_time]
            if observed.empty:
                continue
            latest = observed.iloc[-1]
            entry_price = float(latest["close"])
            high_so_far = float(observed["high"].max())
            volume_sum = float(observed["volume"].sum())
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "decision_time": decision_time,
                    "entry_price": entry_price,
                    "tail_return_from_1430": _return(entry_price, first_tail_close),
                    "tail_high_return_from_1430": _return(high_so_far, first_tail_close),
                    "tail_pullback_from_high": _return(entry_price, high_so_far),
                    "tail_volume": volume_sum,
                    "tail_amount": float(observed["amount"].sum()),
                    "tail_volume_ratio": volume_sum / max(float(prior.get("avg_5m_volume_20", 0.0)), 1.0),
                    "last3_close_slope": _last_n_slope(observed["close"], 3),
                    "last6_close_slope": _last_n_slope(observed["close"], 6),
                    **prior,
                }
            )
    return pd.DataFrame(rows).sort_values(["trade_date", "symbol", "decision_time"]).reset_index(drop=True)


def _prepare_daily(daily_bars: pd.DataFrame) -> pd.DataFrame:
    daily = daily_bars.copy()
    daily["symbol"] = daily["symbol"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        daily[column] = pd.to_numeric(daily[column], errors="coerce").fillna(0.0)
    return daily.sort_values(["symbol", "date"])


def _prepare_minute5(minute5_bars: pd.DataFrame) -> pd.DataFrame:
    minute5 = minute5_bars.copy()
    minute5["symbol"] = minute5["symbol"].astype(str)
    minute5["datetime"] = pd.to_datetime(minute5["datetime"])
    minute5["trade_date"] = minute5["datetime"].dt.date
    minute5["bar_time"] = minute5["datetime"].dt.strftime("%H:%M")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        minute5[column] = pd.to_numeric(minute5[column], errors="coerce").fillna(0.0)
    return minute5.sort_values(["symbol", "datetime"])


def _daily_features(prior_daily: pd.DataFrame) -> dict[str, float]:
    close = prior_daily["close"].astype(float)
    volume = prior_daily["volume"].astype(float)
    amount = prior_daily["amount"].astype(float)
    prior_close = float(close.iloc[-1])
    return {
        "prior_close": prior_close,
        "daily_ret_5": _return(prior_close, float(close.iloc[-6])),
        "daily_ret_10": _window_return(close, 11),
        "daily_ret_20": _window_return(close, 21),
        "daily_volatility_20": float(close.pct_change().tail(20).std() or 0.0),
        "ma5_distance": _return(prior_close, float(close.tail(5).mean())),
        "ma20_distance": _return(prior_close, float(close.tail(20).mean())) if len(close) >= 20 else 0.0,
        "avg_volume_20": float(volume.tail(20).mean()),
        "avg_amount_20": float(amount.tail(20).mean()),
        "avg_5m_volume_20": float(volume.tail(20).mean() / 48.0),
    }


def _market_context_by_date(daily_by_symbol: dict[str, pd.DataFrame]) -> dict[object, dict[str, float]]:
    rows = []
    for symbol_daily in daily_by_symbol.values():
        for index in range(6, len(symbol_daily)):
            prior_daily = symbol_daily.iloc[:index]
            trade_date = symbol_daily.iloc[index]["date"]
            features = _daily_features(prior_daily)
            rows.append(
                {
                    "trade_date": trade_date,
                    "daily_ret_5": features["daily_ret_5"],
                    "daily_ret_20": features["daily_ret_20"],
                    "above_ma20": 1.0 if features["ma20_distance"] > 0 else 0.0,
                }
            )
    if not rows:
        return {}
    frame = pd.DataFrame(rows)
    grouped = frame.groupby("trade_date", sort=True)
    result: dict[object, dict[str, float]] = {}
    for trade_date, group in grouped:
        result[trade_date] = {
            "market_ret_5": float(group["daily_ret_5"].mean()),
            "market_ret_20": float(group["daily_ret_20"].mean()),
            "market_breadth_20": float(group["above_ma20"].mean()),
        }
    return result


def _empty_market_context() -> dict[str, float]:
    return {"market_ret_5": 0.0, "market_ret_20": 0.0, "market_breadth_20": 0.0}


def _window_return(close: pd.Series, rows: int) -> float:
    if len(close) < rows:
        return 0.0
    return _return(float(close.iloc[-1]), float(close.iloc[-rows]))


def _last_n_slope(values: pd.Series, n: int) -> float:
    if len(values) < 2:
        return 0.0
    window = values.tail(n).astype(float)
    return _return(float(window.iloc[-1]), float(window.iloc[0]))


def _return(value: float, base: float) -> float:
    return value / base - 1.0 if base else 0.0


def _time_label(value: time | str) -> str:
    if isinstance(value, str):
        return value[:5]
    return value.strftime("%H:%M")
