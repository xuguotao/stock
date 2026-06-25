"""Rule-strategy baseline evaluation for tail-session ML samples."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

SCORE_FORMULA = "0.45*tail_return + 0.30*volume_ratio + 0.15*last3_slope + 0.10*pullback_control"


def evaluate_tail_rule_baseline(
    samples: pd.DataFrame,
    *,
    top_ns: Iterable[int] = (1, 2, 3),
    min_score: float | None = None,
) -> dict[str, object]:
    if samples.empty:
        return {"sample_rows": 0, "trade_days": 0, "score_formula": SCORE_FORMULA, "by_top_n": []}
    frame = samples.copy()
    frame["rule_score"] = _rule_score(frame)
    if min_score is not None:
        frame = frame[frame["rule_score"] >= min_score].copy()
    trade_days = sorted(pd.to_datetime(samples["trade_date"]).dt.date.unique())
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    ranked = frame.sort_values(["trade_date", "rule_score", "symbol"], ascending=[True, False, True])
    return {
        "sample_rows": int(len(samples)),
        "trade_days": int(len(trade_days)),
        "score_formula": SCORE_FORMULA,
        "by_top_n": [_top_n_metrics(ranked, trade_days=trade_days, top_n=top_n) for top_n in sorted(set(top_ns))],
    }


def _rule_score(frame: pd.DataFrame) -> pd.Series:
    tail_return = _numeric(frame, "tail_return_from_1430").clip(lower=-0.03, upper=0.05) / 0.05
    volume_ratio = _numeric(frame, "tail_volume_ratio").clip(lower=0, upper=3) / 3
    last3_slope = _numeric(frame, "last3_close_slope").clip(lower=-0.02, upper=0.03) / 0.03
    pullback_control = (1 + _numeric(frame, "tail_pullback_from_high").clip(lower=-0.05, upper=0)) / 1
    return tail_return * 0.45 + volume_ratio * 0.30 + last3_slope * 0.15 + pullback_control * 0.10


def _top_n_metrics(ranked: pd.DataFrame, *, trade_days: list[object], top_n: int) -> dict[str, object]:
    selected = ranked.groupby("trade_date", group_keys=False).head(top_n)
    selected_days = int(selected["trade_date"].nunique()) if not selected.empty else 0
    empty_days = max(0, len(trade_days) - selected_days)
    return {
        "top_n": int(top_n),
        "selected_days": selected_days,
        "empty_days": empty_days,
        "selected_rows": int(len(selected)),
        "next_open_win_rate": _mean_bool(selected, "next_open_return", threshold=0),
        "next_high_hit_1pct_rate": _mean_bool_column(selected, "hit_next_high_1pct"),
        "avg_next_open_return": _mean_number(selected, "next_open_return"),
        "avg_next_high_return": _mean_number(selected, "next_high_return"),
        "avg_next_low_drawdown": _mean_number(selected, "next_low_return"),
        "drawdown_breach_2pct_rate": _mean_bool_column(selected, "drawdown_breach_2pct"),
        "max_consecutive_losing_selections": _max_consecutive_losses(selected),
    }


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame.get(column, 0), errors="coerce").fillna(0.0)


def _mean_number(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").mean() or 0.0)


def _mean_bool(frame: pd.DataFrame, column: str, *, threshold: float) -> float:
    if frame.empty or column not in frame:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float((values > threshold).mean()) if not values.empty else 0.0


def _mean_bool_column(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    values = frame[column].dropna().astype(bool)
    return float(values.mean()) if not values.empty else 0.0


def _max_consecutive_losses(selected: pd.DataFrame) -> int:
    if selected.empty or "next_open_return" not in selected:
        return 0
    max_run = 0
    current = 0
    ordered = selected.sort_values(["trade_date", "rule_score", "symbol"], ascending=[True, False, True])
    for value in pd.to_numeric(ordered["next_open_return"], errors="coerce").fillna(0.0):
        if value <= 0:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run
