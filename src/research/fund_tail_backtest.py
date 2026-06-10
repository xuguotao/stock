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
    return px[
        [
            "date",
            "close",
            "daily_return",
            "lookback_return",
            "benchmark_return",
            "signal",
            "reason",
        ]
    ]


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


def assign_decision(
    signals: pd.DataFrame,
    metrics: pd.DataFrame,
    condition: dict[str, object] | None = None,
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
    condition_stats = condition or {}
    row.update(assign_decision(signals, metrics, condition_stats))
    row.update(condition_stats)
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
    "latest_date": "最新日期",
    "latest_daily_return": "今日代理涨跌率",
    "latest_signal": "技术信号",
    "latest_reason": "信号原因",
    "decision_grade": "操作等级",
    "decision_action": "最终操作建议",
    "decision_reason": "建议原因",
    "condition_label": "同类条件",
    "condition_count": "同类样本数",
    "condition_next_up_prob": "同类次日上涨概率",
    "condition_next_down_prob": "同类次日下跌概率",
    "condition_next_avg_return": "同类次日平均收益",
    "condition_next_median_return": "同类次日中位数收益",
    "condition_next_worst_return": "同类次日最差收益",
    "condition_next_down_gt_1pct": "同类次日跌超1%概率",
    "condition_next_down_gt_2pct": "同类次日跌超2%概率",
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
    return column


def to_chinese_report(report: pd.DataFrame) -> pd.DataFrame:
    """Translate report columns and enum values for human-facing CSV output."""
    out = report.copy()
    for column in out.columns:
        if out[column].dtype == "object":
            out[column] = out[column].map(lambda value: CHINESE_VALUE_MAP.get(value, value))
    out = out.rename(columns={column: _chinese_metric_column(column) for column in out.columns})
    return out
