from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.ml.tail_rule_baseline import evaluate_tail_rule_baseline


def test_evaluate_tail_rule_baseline_scores_top_n_by_rule_quality() -> None:
    samples = pd.DataFrame(
        [
            _sample("2026-06-10", "000001.SZ", 2.4, 0.020, 0.010, 0.030, -0.005, True, False),
            _sample("2026-06-10", "000002.SZ", 1.1, 0.004, -0.010, 0.004, -0.025, False, True),
            _sample("2026-06-11", "000003.SZ", 2.0, 0.018, 0.012, 0.025, -0.006, True, False),
            _sample("2026-06-11", "000004.SZ", 1.5, 0.008, -0.004, 0.012, -0.012, True, False),
            _sample("2026-06-12", "000005.SZ", 0.8, -0.002, -0.006, 0.002, -0.020, False, True),
        ]
    )

    report = evaluate_tail_rule_baseline(samples, top_ns=(1, 2), min_score=0.0)

    assert report["sample_rows"] == 5
    assert report["trade_days"] == 3
    assert report["score_formula"] == "0.45*tail_return + 0.30*volume_ratio + 0.15*last3_slope + 0.10*pullback_control"
    top1 = report["by_top_n"][0]
    top2 = report["by_top_n"][1]
    assert top1["top_n"] == 1
    assert top1["selected_days"] == 3
    assert top1["selected_rows"] == 3
    assert top1["empty_days"] == 0
    assert top1["next_open_win_rate"] == pytest.approx(2 / 3)
    assert top1["next_high_hit_1pct_rate"] == pytest.approx(2 / 3)
    assert top1["avg_next_open_return"] == pytest.approx((0.010 + 0.012 - 0.006) / 3)
    assert top1["avg_next_high_return"] == pytest.approx((0.030 + 0.025 + 0.002) / 3)
    assert top1["avg_next_low_drawdown"] == pytest.approx((-0.005 - 0.006 - 0.020) / 3)
    assert top1["max_consecutive_losing_selections"] == 1
    assert top2["top_n"] == 2
    assert top2["selected_rows"] == 5
    assert top2["next_open_win_rate"] == pytest.approx(2 / 5)


def test_evaluate_tail_rule_baseline_handles_empty_or_filtered_samples() -> None:
    empty = evaluate_tail_rule_baseline(pd.DataFrame(), top_ns=(1,))
    assert empty == {"sample_rows": 0, "trade_days": 0, "score_formula": empty["score_formula"], "by_top_n": []}

    samples = pd.DataFrame([
        _sample("2026-06-10", "000001.SZ", 0.5, -0.01, -0.01, 0.0, -0.03, False, True),
    ])
    report = evaluate_tail_rule_baseline(samples, top_ns=(1,), min_score=10.0)

    assert report["sample_rows"] == 1
    assert report["trade_days"] == 1
    assert report["by_top_n"][0]["selected_rows"] == 0
    assert report["by_top_n"][0]["empty_days"] == 1


def _sample(
    trade_date: str,
    symbol: str,
    volume_ratio: float,
    tail_return: float,
    open_return: float,
    high_return: float,
    low_return: float,
    hit_high: bool,
    drawdown: bool,
) -> dict[str, object]:
    return {
        "trade_date": date.fromisoformat(trade_date),
        "symbol": symbol,
        "decision_time": "14:55",
        "tail_volume_ratio": volume_ratio,
        "tail_return_from_1430": tail_return,
        "last3_close_slope": tail_return / 2,
        "tail_pullback_from_high": -0.002,
        "next_open_return": open_return,
        "next_high_return": high_return,
        "next_low_return": low_return,
        "hit_next_high_1pct": hit_high,
        "drawdown_breach_2pct": drawdown,
    }
