"""Backtest helpers for fund tail-session advice rules."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SignalConfig:
    """Thresholds for classifying tail-session add/watch/avoid signals."""

    pullback_floor: float = -0.03
    chase_limit: float = 0.025
    weak_day_limit: float = -0.01
    relative_strength_margin: float = 0.0


def _prepare_series(df: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["close"])
    return out.reset_index(drop=True)


def normalize_akshare_nav(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize AKShare open-fund NAV output to date/close columns."""
    renamed = df.rename(columns={"净值日期": "date", "单位净值": "close"})
    return _prepare_series(renamed)[["date", "close"]]


def normalize_akshare_index(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize AKShare A-share index output to date/close/volume columns."""
    renamed = df.rename(columns={"日期": "date", "收盘": "close", "成交量": "volume"})
    prepared = _prepare_series(renamed)
    if "volume" in renamed.columns:
        prepared["volume"] = pd.to_numeric(renamed.loc[prepared.index, "volume"], errors="coerce")
        return prepared[["date", "close", "volume"]]
    return prepared[["date", "close"]]


def normalize_akshare_cni_index(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize AKShare CNI index output to date/close/volume columns."""
    renamed = df.rename(columns={"日期": "date", "收盘价": "close", "成交量": "volume"})
    prepared = _prepare_series(renamed)
    if "volume" in renamed.columns:
        prepared["volume"] = pd.to_numeric(renamed.loc[prepared.index, "volume"], errors="coerce")
        return prepared[["date", "close", "volume"]]
    return prepared[["date", "close"]]


def normalize_akshare_us_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize AKShare Sina US daily output to date/close/volume columns."""
    prepared = _prepare_series(df)
    if "volume" in df.columns:
        prepared["volume"] = pd.to_numeric(df.loc[prepared.index, "volume"], errors="coerce")
        return prepared[["date", "close", "volume"]]
    return prepared[["date", "close"]]


def select_proxy_series(*, nav: pd.DataFrame, proxy: pd.DataFrame | None) -> pd.DataFrame:
    """Use proxy data when available; otherwise fall back to NAV data."""
    if proxy is None or proxy.empty:
        return nav
    return proxy


def append_latest_row(history: pd.DataFrame, latest: pd.DataFrame | None) -> pd.DataFrame:
    """Append or replace latest rows by date, preserving chronological order."""
    prepared = _prepare_series(history)
    if latest is None or latest.empty:
        return prepared
    latest_prepared = _prepare_series(latest)
    combined = pd.concat([prepared, latest_prepared], ignore_index=True)
    combined = combined.sort_values("date").drop_duplicates("date", keep="last")
    columns = [col for col in history.columns if col in combined.columns]
    extra = [col for col in combined.columns if col not in columns]
    return combined[columns + extra].reset_index(drop=True)


def _signed_streak(returns: pd.Series) -> pd.Series:
    streaks = []
    current = 0
    for value in returns:
        if pd.isna(value) or value == 0:
            current = 0
        elif value > 0:
            current = current + 1 if current > 0 else 1
        else:
            current = current - 1 if current < 0 else -1
        streaks.append(current)
    return pd.Series(streaks, index=returns.index, dtype="int64")


def _rolling_percentile_rank(values: pd.Series, window: int) -> pd.Series:
    def rank_latest(window_values) -> float:
        series = pd.Series(window_values).dropna()
        if series.empty:
            return float("nan")
        latest = series.iloc[-1]
        return float((series <= latest).mean())

    return values.rolling(window, min_periods=5).apply(rank_latest, raw=False)


def classify_tail_signals(
    proxy: pd.DataFrame,
    *,
    benchmark: pd.DataFrame | None = None,
    lookback: int = 5,
    config: SignalConfig | None = None,
) -> pd.DataFrame:
    """Classify each proxy date as add, watch, or avoid.

    The rules are intentionally simple and auditable: avoid sharp selloffs,
    avoid chasing overextended days, prefer positive trend with relative
    strength versus a benchmark.
    """
    cfg = config or SignalConfig()
    px = _prepare_series(proxy)
    px["daily_return"] = px["close"].pct_change(fill_method=None)
    px["ma"] = px["close"].rolling(lookback, min_periods=lookback).mean()
    px["lookback_return"] = px["close"].pct_change(lookback - 1, fill_method=None)
    px["return_3d"] = px["close"].pct_change(3, fill_method=None)
    px["return_5d"] = px["close"].pct_change(5, fill_method=None)
    px["return_10d"] = px["close"].pct_change(10, fill_method=None)
    px["return_20d"] = px["close"].pct_change(20, fill_method=None)
    px["ma5"] = px["close"].rolling(5, min_periods=5).mean()
    px["ma20"] = px["close"].rolling(20, min_periods=5).mean()
    px["ma60"] = px["close"].rolling(60, min_periods=10).mean()
    px["ma5_deviation"] = px["close"] / px["ma5"] - 1
    px["ma20_deviation"] = px["close"] / px["ma20"] - 1
    px["ma60_deviation"] = px["close"] / px["ma60"] - 1
    px["volatility_20d"] = px["daily_return"].rolling(20, min_periods=5).std()
    px["drawdown_20d"] = px["close"] / px["close"].rolling(20, min_periods=5).max() - 1
    px["daily_return_rank_252d"] = _rolling_percentile_rank(px["daily_return"], 252)
    px["streak"] = _signed_streak(px["daily_return"])
    if "volume" in px.columns:
        px["volume"] = pd.to_numeric(px["volume"], errors="coerce")
        px["volume_ratio_20d"] = px["volume"] / px["volume"].rolling(20, min_periods=5).mean()

    if benchmark is not None:
        bm = _prepare_series(benchmark)[["date", "close"]].rename(
            columns={"close": "benchmark_close"}
        )
        px = px.merge(bm, on="date", how="left")
        px["benchmark_return"] = px["benchmark_close"].pct_change(
            lookback - 1,
            fill_method=None,
        )
    else:
        px["benchmark_return"] = 0.0

    signals = []
    reasons = []
    for row in px.itertuples(index=False):
        if pd.isna(row.daily_return) or pd.isna(row.ma) or pd.isna(row.lookback_return):
            signals.append("watch")
            reasons.append("insufficient_history")
        elif row.daily_return > cfg.chase_limit:
            signals.append("watch")
            reasons.append("overextended_do_not_chase")
        elif row.daily_return < cfg.pullback_floor:
            signals.append("avoid")
            reasons.append("sharp_selloff")
        elif row.daily_return < cfg.weak_day_limit and row.close < row.ma:
            signals.append("avoid")
            reasons.append("weak_below_trend")
        elif row.close >= row.ma and row.lookback_return >= row.benchmark_return + cfg.relative_strength_margin:
            signals.append("add")
            reasons.append("trend_positive_relative_strength")
        else:
            signals.append("watch")
            reasons.append("mixed_signal")

    px["signal"] = signals
    px["reason"] = reasons
    columns = [
        "date",
        "close",
        "daily_return",
        "lookback_return",
        "benchmark_return",
        "return_3d",
        "return_5d",
        "return_10d",
        "return_20d",
        "ma5_deviation",
        "ma20_deviation",
        "ma60_deviation",
        "volatility_20d",
        "drawdown_20d",
        "daily_return_rank_252d",
        "streak",
        "signal",
        "reason",
    ]
    if "volume_ratio_20d" in px.columns:
        columns.insert(-2, "volume_ratio_20d")
    return px[columns]


def evaluate_forward_returns(
    signals: pd.DataFrame,
    nav: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    signal_name: str = "add",
) -> pd.DataFrame:
    """Evaluate future NAV returns after selected signal dates."""
    if "date" not in signals or "signal" not in signals:
        raise ValueError("signals must contain date and signal columns")

    nav_px = _prepare_series(nav)[["date", "close"]].rename(columns={"close": "nav_close"})
    events = signals.copy()
    events["date"] = pd.to_datetime(events["date"])
    events = events.merge(nav_px, on="date", how="inner")
    events = events[events["signal"] == signal_name].copy()

    rows = []
    nav_px = nav_px.reset_index(drop=True)
    date_to_pos = {d: i for i, d in enumerate(nav_px["date"])}
    for horizon in horizons:
        forward = []
        for event in events.itertuples(index=False):
            pos = date_to_pos.get(event.date)
            if pos is None:
                continue
            target = pos + horizon
            if target >= len(nav_px):
                continue
            start = float(event.nav_close)
            end = float(nav_px.iloc[target]["nav_close"])
            if start > 0:
                forward.append(end / start - 1)

        series = pd.Series(forward, dtype="float64")
        rows.append(
            {
                "horizon": horizon,
                "count": int(series.count()),
                "avg_return": float(series.mean()) if not series.empty else 0.0,
                "median_return": float(series.median()) if not series.empty else 0.0,
                "win_rate": float((series > 0).mean()) if not series.empty else 0.0,
                "worst_return": float(series.min()) if not series.empty else 0.0,
                "drawdown_risk": float((series < -0.02).mean()) if not series.empty else 0.0,
            }
        )

    return pd.DataFrame(rows).set_index("horizon")


def evaluate_proxy_fit(nav: pd.DataFrame, proxy: pd.DataFrame, *, min_samples: int = 20) -> dict[str, object]:
    """Measure how well proxy daily returns track fund NAV daily returns."""
    nav_px = _prepare_series(nav)[["date", "close"]].rename(columns={"close": "nav_close"})
    proxy_px = _prepare_series(proxy)[["date", "close"]].rename(columns={"close": "proxy_close"})
    merged = nav_px.merge(proxy_px, on="date", how="inner").sort_values("date")
    merged["nav_return"] = merged["nav_close"].pct_change(fill_method=None)
    merged["proxy_return"] = merged["proxy_close"].pct_change(fill_method=None)
    returns = merged[["nav_return", "proxy_return"]].dropna()
    sample_count = int(len(returns))
    if sample_count < min_samples:
        corr = float("nan")
        level = "low_sample"
    else:
        corr = float(returns["nav_return"].corr(returns["proxy_return"]))
        if pd.isna(corr):
            level = "low_sample"
        elif corr >= 0.8:
            level = "high"
        elif corr >= 0.6:
            level = "medium"
        elif corr >= 0.4:
            level = "low"
        else:
            level = "very_low"
    return {
        "proxy_fit_sample_count": sample_count,
        "proxy_fit_correlation": corr,
        "proxy_fit_level": level,
    }


def evaluate_latest_condition(
    signals: pd.DataFrame,
    nav: pd.DataFrame,
    *,
    min_samples: int = 10,
) -> dict[str, object]:
    """Evaluate next-day NAV outcomes for dates similar to the latest signal."""
    if signals.empty:
        raise ValueError("signals cannot be empty")
    required = {"date", "signal", "reason", "daily_return"}
    missing = required - set(signals.columns)
    if missing:
        raise ValueError(f"signals missing columns: {sorted(missing)}")

    prepared_signals = signals.copy()
    prepared_signals["date"] = pd.to_datetime(prepared_signals["date"])
    latest = prepared_signals.sort_values("date").iloc[-1]

    nav_px = _prepare_series(nav)[["date", "close"]].rename(columns={"close": "nav_close"})
    events = prepared_signals.merge(nav_px, on="date", how="inner")

    reason = str(latest["reason"])
    latest_return = float(latest["daily_return"])
    same_reason = events["reason"].eq(reason)

    if reason in {"weak_below_trend", "mixed_signal"}:
        low = max(-0.05, latest_return - 0.01)
        high = min(0.05, latest_return + 0.01)
        band = same_reason & events["daily_return"].between(low, high)
        if int(band.sum()) >= min_samples:
            mask = band
            label = f"{reason}_daily_{low:.1%}_{high:.1%}"
        else:
            mask = same_reason
            label = f"reason_{reason}"
    else:
        mask = same_reason
        label = f"reason_{reason}"

    nav_px = nav_px.reset_index(drop=True)
    date_to_pos = {d: i for i, d in enumerate(nav_px["date"])}
    forward = []
    for event in events[mask].itertuples(index=False):
        pos = date_to_pos.get(event.date)
        if pos is None or pos + 1 >= len(nav_px):
            continue
        start = float(event.nav_close)
        end = float(nav_px.iloc[pos + 1]["nav_close"])
        if start > 0:
            forward.append(end / start - 1)

    series = pd.Series(forward, dtype="float64")
    return {
        "condition_label": label,
        "condition_count": int(series.count()),
        "condition_next_up_prob": float((series > 0).mean()) if not series.empty else 0.0,
        "condition_next_down_prob": float((series < 0).mean()) if not series.empty else 0.0,
        "condition_next_avg_return": float(series.mean()) if not series.empty else 0.0,
        "condition_next_median_return": float(series.median()) if not series.empty else 0.0,
        "condition_next_worst_return": float(series.min()) if not series.empty else 0.0,
        "condition_next_down_gt_1pct": float((series < -0.01).mean()) if not series.empty else 0.0,
        "condition_next_down_gt_2pct": float((series < -0.02).mean()) if not series.empty else 0.0,
    }


def evaluate_prediction_profile(
    signals: pd.DataFrame,
    nav: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    min_samples: int = 10,
) -> dict[str, object]:
    """Estimate future N-day outcomes for dates similar to the latest setup."""
    if signals.empty:
        raise ValueError("signals cannot be empty")
    required = {"date", "reason", "daily_return"}
    missing = required - set(signals.columns)
    if missing:
        raise ValueError(f"signals missing columns: {sorted(missing)}")

    prepared_signals = signals.copy()
    prepared_signals["date"] = pd.to_datetime(prepared_signals["date"])
    latest = prepared_signals.sort_values("date").iloc[-1]
    reason = str(latest["reason"])
    latest_return = float(latest["daily_return"])

    nav_px = _prepare_series(nav)[["date", "close"]].rename(columns={"close": "nav_close"})
    events = prepared_signals.merge(nav_px, on="date", how="inner")
    same_reason = events["reason"].eq(reason)
    low = max(-0.08, latest_return - 0.01)
    high = min(0.08, latest_return + 0.01)
    band = same_reason & events["daily_return"].between(low, high)
    if int(band.sum()) >= min_samples:
        mask = band
        label = f"{reason}_daily_{low:.1%}_{high:.1%}"
    else:
        mask = same_reason
        label = f"reason_{reason}"
    mask, label = _refine_prediction_mask_by_feature_regime(
        events,
        latest,
        mask,
        label,
        min_samples=min_samples,
    )

    nav_px = nav_px.reset_index(drop=True)
    date_to_pos = {d: i for i, d in enumerate(nav_px["date"])}
    result: dict[str, object] = {
        "prediction_condition_label": label,
        "prediction_latest_daily_return": latest_return,
    }
    for horizon in horizons:
        forward = []
        for event in events[mask].itertuples(index=False):
            pos = date_to_pos.get(event.date)
            if pos is None:
                continue
            target = pos + horizon
            if target >= len(nav_px):
                continue
            start = float(event.nav_close)
            end = float(nav_px.iloc[target]["nav_close"])
            if start > 0:
                forward.append(end / start - 1)
        series = pd.Series(forward, dtype="float64")
        prefix = f"prediction_h{horizon}"
        result[f"{prefix}_count"] = int(series.count())
        result[f"{prefix}_up_prob"] = float((series > 0).mean()) if not series.empty else 0.0
        result[f"{prefix}_down_prob"] = float((series < 0).mean()) if not series.empty else 0.0
        result[f"{prefix}_avg_return"] = float(series.mean()) if not series.empty else 0.0
        result[f"{prefix}_median_return"] = float(series.median()) if not series.empty else 0.0
        result[f"{prefix}_down_gt_1pct"] = float((series < -0.01).mean()) if not series.empty else 0.0
        result[f"{prefix}_down_gt_2pct"] = float((series < -0.02).mean()) if not series.empty else 0.0

    result["prediction_score"] = score_prediction_profile(result)
    return result


def _refine_prediction_mask_by_feature_regime(
    events: pd.DataFrame,
    latest: pd.Series,
    mask: pd.Series,
    label: str,
    *,
    min_samples: int,
) -> tuple[pd.Series, str]:
    refinements = [
        ("return_5d", "return_5d_positive", "return_5d_negative"),
        ("ma20_deviation", "ma20_positive", "ma20_negative"),
    ]
    refined = mask.copy()
    labels = [label]
    for column, positive_label, negative_label in refinements:
        if column not in events.columns or column not in latest:
            continue
        latest_value = latest[column]
        if pd.isna(latest_value):
            continue
        candidate = refined & events[column].notna()
        if latest_value >= 0:
            candidate = candidate & (events[column] >= 0)
            suffix = positive_label
        else:
            candidate = candidate & (events[column] < 0)
            suffix = negative_label
        if int(candidate.sum()) >= min_samples:
            refined = candidate
            labels.append(suffix)
    return refined, "|".join(labels)


def score_prediction_profile(profile: dict[str, object]) -> float:
    """Convert multi-horizon probabilities and risks into a 0-100 add score."""
    h3_up = float(profile.get("prediction_h3_up_prob", profile.get("prediction_h1_up_prob", 0.5)))
    h5_up = float(profile.get("prediction_h5_up_prob", h3_up))
    h5_median = float(profile.get("prediction_h5_median_return", 0.0))
    h5_down_2 = float(profile.get("prediction_h5_down_gt_2pct", 0.0))
    latest_return = float(profile.get("prediction_latest_daily_return", 0.0))

    expected_return_score = max(-15.0, min(20.0, h5_median * 1000.0))
    chase_penalty = max(0.0, latest_return - 0.01) * 600.0
    risk_penalty = h5_down_2 * 35.0
    score = 50.0 + (h3_up - 0.5) * 35.0 + (h5_up - 0.5) * 25.0
    score += expected_return_score - risk_penalty - chase_penalty
    return round(max(0.0, min(100.0, score)), 2)


def _latest_numeric(latest: pd.Series, key: str, default: float = 0.0) -> float:
    value = latest.get(key, default)
    if pd.isna(value):
        return default
    return float(value)


def assign_sell_decision(
    signals: pd.DataFrame,
    prediction: dict[str, object] | None = None,
    condition: dict[str, object] | None = None,
) -> dict[str, object]:
    """Convert latest setup into a sell/reduce decision.

    This is intentionally separate from add decisions: sell logic focuses on
    protecting capital after sharp rises and reducing weak trends with poor
    forward odds.
    """
    if signals.empty:
        raise ValueError("signals cannot be empty")

    latest = signals.sort_values("date").iloc[-1]
    latest_return = _latest_numeric(latest, "daily_return")
    return_5d = _latest_numeric(latest, "return_5d")
    ma20_deviation = _latest_numeric(latest, "ma20_deviation")
    return_rank = _latest_numeric(latest, "daily_return_rank_252d", 0.5)
    reason = str(latest.get("reason", ""))

    profile = prediction or {}
    h3_up = float(profile.get("prediction_h3_up_prob", 0.5))
    h5_up = float(profile.get("prediction_h5_up_prob", h3_up))
    h5_median = float(profile.get("prediction_h5_median_return", 0.0))
    h5_down_2 = float(profile.get("prediction_h5_down_gt_2pct", 0.0))
    sample_count = int(profile.get("prediction_h5_count", profile.get("prediction_h3_count", 0)))

    downside_pressure = max(0.0, 0.5 - h5_up) * 45.0
    expected_loss_pressure = max(0.0, -h5_median) * 1200.0
    drawdown_pressure = h5_down_2 * 35.0
    overheat_pressure = max(0.0, latest_return - 0.015) * 650.0 + max(0.0, return_rank - 0.9) * 30.0
    weak_trend_pressure = max(0.0, -return_5d) * 350.0 + max(0.0, -ma20_deviation) * 250.0
    sell_score = round(
        max(
            0.0,
            min(
                100.0,
                25.0
                + downside_pressure
                + expected_loss_pressure
                + drawdown_pressure
                + overheat_pressure
                + weak_trend_pressure,
            ),
        ),
        2,
    )

    if (
        reason == "overextended_do_not_chase"
        and latest_return >= 0.02
        and return_rank >= 0.9
        and (h5_median <= 0 or h5_up < 0.5 or h5_down_2 >= 0.18)
    ):
        return {
            "sell_grade": "A",
            "sell_action": "take_profit_reduce",
            "sell_reason": "overextended_forward_edge_negative",
            "sell_score": max(sell_score, 70.0),
        }
    if reason == "overextended_do_not_chase" and latest_return >= 0.02 and return_rank >= 0.95:
        return {
            "sell_grade": "C",
            "sell_action": "small_take_profit",
            "sell_reason": "overextended_lock_profit",
            "sell_score": max(sell_score, 50.0),
        }
    if (
        reason in {"weak_below_trend", "sharp_selloff"}
        and return_5d < 0
        and ma20_deviation < 0
        and (h5_median < 0 or h5_down_2 >= 0.25 or h5_up < 0.45)
    ):
        return {
            "sell_grade": "A",
            "sell_action": "stop_loss_reduce",
            "sell_reason": "weak_trend_downside_risk",
            "sell_score": max(sell_score, 72.0),
        }
    if h3_up >= 0.58 and h5_median > 0 and h5_down_2 <= 0.12:
        return {
            "sell_grade": "D",
            "sell_action": "do_not_sell",
            "sell_reason": "pullback_rebound_probability_ok",
            "sell_score": min(sell_score, 35.0),
        }
    if sample_count >= 10 and h5_median < 0 and h5_down_2 >= 0.2:
        return {
            "sell_grade": "B",
            "sell_action": "reduce_observe",
            "sell_reason": "forward_risk_reward_poor",
            "sell_score": max(sell_score, 58.0),
        }
    if latest_return >= 0.02 and return_rank >= 0.9:
        return {
            "sell_grade": "C",
            "sell_action": "hold_watch_sell",
            "sell_reason": "overheated_but_edge_not_negative",
            "sell_score": max(sell_score, 45.0),
        }
    return {
        "sell_grade": "D",
        "sell_action": "do_not_sell",
        "sell_reason": "sell_signal_not_triggered",
        "sell_score": sell_score,
    }


def assign_decision(
    signals: pd.DataFrame,
    metrics: pd.DataFrame,
    condition: dict[str, object] | None = None,
    prediction: dict[str, object] | None = None,
) -> dict[str, str]:
    """Convert latest signal and historical edge into an executable grade."""
    if signals.empty:
        raise ValueError("signals cannot be empty")
    if metrics.empty:
        return {
            "decision_grade": "C",
            "decision_action": "hold_watch",
            "decision_reason": "insufficient_backtest_metrics",
        }

    latest = signals.sort_values("date").iloc[-1]
    sorted_signals = signals.sort_values("date")
    prev_reason = sorted_signals.iloc[-2]["reason"] if len(sorted_signals) >= 2 else None
    eval_horizon = 5 if 5 in metrics.index else metrics.index[-1]
    edge = metrics.loc[eval_horizon]
    avg_return = float(edge["avg_return"])
    median_return = float(edge.get("median_return", avg_return))
    win_rate = float(edge["win_rate"])
    drawdown_risk = float(edge.get("drawdown_risk", 0.0))

    if latest["reason"] == "overextended_do_not_chase":
        return {
            "decision_grade": "C",
            "decision_action": "wait_for_pullback",
            "decision_reason": "latest_proxy_overextended",
        }
    if condition is not None and int(condition.get("condition_count", 0)) >= 10:
        up_prob = float(condition.get("condition_next_up_prob", 0.0))
        down_prob = float(condition.get("condition_next_down_prob", 0.0))
        avg_next = float(condition.get("condition_next_avg_return", 0.0))
        median_next = float(condition.get("condition_next_median_return", 0.0))
        down_gt_1 = float(condition.get("condition_next_down_gt_1pct", 0.0))
        if down_prob >= 0.52 and median_next <= 0:
            return {
                "decision_grade": "D",
                "decision_action": "do_not_add",
                "decision_reason": "similar_history_downside_higher",
            }
        if latest["reason"] == "weak_below_trend":
            if prev_reason == "weak_below_trend":
                return {
                    "decision_grade": "C",
                    "decision_action": "wait_for_stabilization",
                    "decision_reason": "consecutive_weak_needs_confirmation",
                }
            if up_prob >= 0.54 and median_next > 0 and down_gt_1 <= 0.25:
                return {
                    "decision_grade": "B",
                    "decision_action": "small_probe",
                    "decision_reason": "similar_history_rebound_slightly_higher",
                }
            return {
                "decision_grade": "C",
                "decision_action": "wait_for_stabilization",
                "decision_reason": "similar_history_edge_thin",
            }
        if latest["reason"] == "mixed_signal" and (avg_next <= 0 or up_prob < 0.52):
            return {
                "decision_grade": "D",
                "decision_action": "do_not_add",
                "decision_reason": "similar_history_no_edge",
            }
    if avg_return <= 0 or median_return <= 0 or win_rate < 0.5 or drawdown_risk > 0.5:
        return {
            "decision_grade": "D",
            "decision_action": "do_not_add",
            "decision_reason": "historical_edge_weak",
        }
    if latest["reason"] == "weak_below_trend":
        if avg_return >= 0.005 and median_return > 0 and win_rate >= 0.6 and drawdown_risk <= 0.2:
            return {
                "decision_grade": "B",
                "decision_action": "small_probe",
                "decision_reason": "pullback_with_positive_history",
            }
        return {
            "decision_grade": "C",
            "decision_action": "wait_for_stabilization",
            "decision_reason": "weak_pullback_needs_confirmation",
        }
    if latest["signal"] == "avoid":
        return {
            "decision_grade": "D",
            "decision_action": "do_not_add",
            "decision_reason": str(latest["reason"]),
        }
    if prediction is not None and int(prediction.get("prediction_h3_count", 0)) >= 10:
        prediction_score = float(prediction.get("prediction_score", 0.0))
        h3_up = float(prediction.get("prediction_h3_up_prob", 0.0))
        h5_median = float(prediction.get("prediction_h5_median_return", 0.0))
        latest_return = float(latest.get("daily_return", 0.0))
        if latest["signal"] == "add" and latest_return >= 0.02 and h3_up < 0.58:
            return {
                "decision_grade": "C",
                "decision_action": "wait_for_pullback",
                "decision_reason": "prediction_chase_risk",
            }
        if latest["signal"] == "add" and (prediction_score < 55 or h3_up < 0.52 or h5_median <= 0):
            return {
                "decision_grade": "D",
                "decision_action": "do_not_add",
                "decision_reason": "prediction_edge_weak",
            }
        if latest["signal"] == "add" and prediction_score >= 72:
            return {
                "decision_grade": "A",
                "decision_action": "tail_add",
                "decision_reason": "prediction_edge_strong",
            }
        if latest["signal"] == "add" and prediction_score >= 55:
            return {
                "decision_grade": "B",
                "decision_action": "small_probe",
                "decision_reason": "prediction_edge_moderate",
            }
    if latest["signal"] == "add" and avg_return >= 0.005 and win_rate >= 0.58 and drawdown_risk <= 0.35:
        return {
            "decision_grade": "A",
            "decision_action": "tail_add",
            "decision_reason": "signal_and_history_aligned",
        }
    if latest["signal"] == "add":
        return {
            "decision_grade": "B",
            "decision_action": "small_probe",
            "decision_reason": "signal_positive_but_edge_moderate",
        }
    return {
        "decision_grade": "C",
        "decision_action": "hold_watch",
        "decision_reason": "latest_signal_mixed",
    }


def summarize_latest_signal(
    fund_name: str,
    fund_code: str,
    signals: pd.DataFrame,
    metrics: pd.DataFrame,
    condition: dict[str, object] | None = None,
    prediction: dict[str, object] | None = None,
    proxy_info: dict[str, object] | None = None,
    proxy_fit: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a flat report row for the latest signal plus horizon metrics."""
    if signals.empty:
        raise ValueError("signals cannot be empty")

    latest = signals.sort_values("date").iloc[-1]
    row: dict[str, object] = {
        "fund_name": fund_name,
        "fund_code": fund_code,
        "latest_date": latest["date"],
        "latest_daily_return": float(latest.get("daily_return", 0.0)),
        "latest_signal": latest["signal"],
        "latest_reason": latest["reason"],
    }
    if proxy_info:
        row.update(proxy_info)
    if proxy_fit:
        row.update(proxy_fit)
    for column in (
        "return_3d",
        "return_5d",
        "return_10d",
        "return_20d",
        "ma20_deviation",
        "volatility_20d",
        "drawdown_20d",
        "daily_return_rank_252d",
        "streak",
    ):
        if column in latest and pd.notna(latest[column]):
            row[f"latest_{column}"] = float(latest[column])
    condition_stats = condition or {}
    prediction_stats = prediction or {}
    row.update(assign_decision(signals, metrics, condition_stats, prediction_stats))
    row.update(assign_sell_decision(signals, prediction_stats, condition_stats))
    row.update(condition_stats)
    row.update(prediction_stats)
    for horizon, metric in metrics.iterrows():
        prefix = f"h{horizon}"
        row[f"{prefix}_count"] = int(metric["count"])
        row[f"{prefix}_avg_return"] = float(metric["avg_return"])
        row[f"{prefix}_median_return"] = float(metric.get("median_return", metric["avg_return"]))
        row[f"{prefix}_win_rate"] = float(metric["win_rate"])
        row[f"{prefix}_worst_return"] = float(metric["worst_return"])
        row[f"{prefix}_drawdown_risk"] = float(metric.get("drawdown_risk", 0.0))
    return row


CHINESE_COLUMN_NAMES = {
    "fund_name": "基金名称",
    "fund_code": "基金代码",
    "proxy_name": "代理标的",
    "proxy_code": "代理代码",
    "proxy_provider": "代理来源",
    "proxy_fit_sample_count": "代理匹配样本数",
    "proxy_fit_correlation": "代理匹配度",
    "proxy_fit_level": "代理匹配等级",
    "latest_date": "最新日期",
    "latest_daily_return": "今日代理涨跌率",
    "latest_return_3d": "近3日涨跌率",
    "latest_return_5d": "近5日涨跌率",
    "latest_return_10d": "近10日涨跌率",
    "latest_return_20d": "近20日涨跌率",
    "latest_ma20_deviation": "偏离20日均线",
    "latest_volatility_20d": "20日波动率",
    "latest_drawdown_20d": "20日回撤",
    "latest_daily_return_rank_252d": "今日涨跌分位",
    "latest_streak": "连续涨跌天数",
    "latest_signal": "技术信号",
    "latest_reason": "信号原因",
    "decision_grade": "操作等级",
    "decision_action": "最终操作建议",
    "decision_reason": "建议原因",
    "sell_grade": "卖出等级",
    "sell_action": "卖出建议",
    "sell_reason": "卖出原因",
    "sell_score": "卖出评分",
    "condition_label": "同类条件",
    "condition_count": "同类样本数",
    "condition_next_up_prob": "同类次日上涨概率",
    "condition_next_down_prob": "同类次日下跌概率",
    "condition_next_avg_return": "同类次日平均收益",
    "condition_next_median_return": "同类次日中位数收益",
    "condition_next_worst_return": "同类次日最差收益",
    "condition_next_down_gt_1pct": "同类次日跌超1%概率",
    "condition_next_down_gt_2pct": "同类次日跌超2%概率",
    "prediction_condition_label": "预测同类条件",
    "prediction_latest_daily_return": "预测用今日涨跌率",
    "prediction_score": "预测加仓评分",
}

CHINESE_VALUE_MAP = {
    "add": "加仓",
    "watch": "观察",
    "avoid": "回避",
    "trend_positive_relative_strength": "趋势向上且相对强势",
    "overextended_do_not_chase": "涨幅过大不追高",
    "sharp_selloff": "急跌",
    "weak_below_trend": "弱于趋势",
    "mixed_signal": "信号不明确",
    "insufficient_history": "历史不足",
    "tail_add": "尾盘加仓",
    "small_probe": "小额试探",
    "wait_for_pullback": "等待回踩",
    "wait_for_stabilization": "等待企稳",
    "hold_watch": "持有观察",
    "do_not_add": "不加仓",
    "latest_proxy_overextended": "最新代理指数涨幅过大",
    "historical_edge_weak": "历史优势不足",
    "pullback_with_positive_history": "回踩但历史赔率较好",
    "weak_pullback_needs_confirmation": "弱势回踩需要确认",
    "signal_and_history_aligned": "信号与历史优势一致",
    "signal_positive_but_edge_moderate": "信号偏正但优势一般",
    "latest_signal_mixed": "最新信号不明确",
    "similar_history_downside_higher": "同类历史下跌概率更高",
    "similar_history_rebound_slightly_higher": "同类历史反弹概率略高",
    "similar_history_edge_thin": "同类历史优势较薄",
    "similar_history_no_edge": "同类历史无明显优势",
    "consecutive_weak_needs_confirmation": "连续弱势需要确认",
    "prediction_chase_risk": "预测显示追高风险",
    "prediction_edge_weak": "预测优势不足",
    "prediction_edge_moderate": "预测优势一般",
    "prediction_edge_strong": "预测优势较强",
    "take_profit_reduce": "止盈减仓",
    "small_take_profit": "小比例止盈",
    "stop_loss_reduce": "止损减仓",
    "reduce_observe": "分批减仓",
    "hold_watch_sell": "持有观察",
    "do_not_sell": "不卖出",
    "overextended_forward_edge_negative": "涨幅过大且未来收益转弱",
    "overextended_lock_profit": "涨幅过大，盈利仓落袋为安",
    "weak_trend_downside_risk": "弱势趋势且下行风险高",
    "pullback_rebound_probability_ok": "回调但反弹概率仍可",
    "forward_risk_reward_poor": "未来风险收益比差",
    "overheated_but_edge_not_negative": "过热但未来优势未转负",
    "sell_signal_not_triggered": "卖出信号未触发",
    "high": "高",
    "medium": "中",
    "low": "低",
    "very_low": "很低",
    "low_sample": "样本不足",
}


def _chinese_metric_column(column: str) -> str:
    if column in CHINESE_COLUMN_NAMES:
        return CHINESE_COLUMN_NAMES[column]
    for horizon in (1, 3, 5, 10):
        prefix = f"h{horizon}_"
        if column.startswith(prefix):
            suffix = column.removeprefix(prefix)
            names = {
                "count": "样本数",
                "avg_return": "平均收益",
                "median_return": "中位数收益",
                "win_rate": "胜率",
                "worst_return": "最差收益",
                "drawdown_risk": "跌超2%概率",
            }
            if suffix in names:
                return f"{horizon}日{names[suffix]}"
        prediction_prefix = f"prediction_h{horizon}_"
        if column.startswith(prediction_prefix):
            suffix = column.removeprefix(prediction_prefix)
            names = {
                "count": "预测样本数",
                "up_prob": "预测上涨概率",
                "down_prob": "预测下跌概率",
                "avg_return": "预测平均收益",
                "median_return": "预测中位数收益",
                "down_gt_1pct": "预测跌超1%概率",
                "down_gt_2pct": "预测跌超2%概率",
            }
            if suffix in names:
                return f"{horizon}日{names[suffix]}"
    return column


def to_chinese_report(report: pd.DataFrame) -> pd.DataFrame:
    """Translate report columns and enum values for human-facing CSV output."""
    out = report.copy()
    if "latest_daily_return" in out.columns:
        out = out.sort_values("latest_daily_return", ascending=False, na_position="last").reset_index(drop=True)
    for column in out.columns:
        if out[column].dtype == "object":
            out[column] = out[column].map(lambda value: CHINESE_VALUE_MAP.get(value, value))
    out = out.rename(columns={column: _chinese_metric_column(column) for column in out.columns})
    if "今日代理涨跌率" in out.columns:
        out["今日代理涨跌率"] = out["今日代理涨跌率"].map(lambda value: f"{float(value) * 100:.2f}%")
    for column in (
        "预测用今日涨跌率",
        "近3日涨跌率",
        "近5日涨跌率",
        "近10日涨跌率",
        "近20日涨跌率",
        "偏离20日均线",
        "20日波动率",
        "20日回撤",
        "今日涨跌分位",
        "代理匹配度",
    ):
        if column in out.columns:
            out[column] = out[column].map(lambda value: f"{float(value) * 100:.2f}%")
    return out
