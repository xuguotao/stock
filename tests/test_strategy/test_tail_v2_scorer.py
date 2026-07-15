from __future__ import annotations

from datetime import date

from src.strategy.scanner import TailSessionSignal
from src.strategy.tail_session.v2_scorer import score_tail_signals


def _signal(
    symbol: str,
    *,
    strength: float,
    volume_ratio: float,
    tail_return: float,
    tail_high_return: float = 0.0,
    pullback_from_high: float = 0.0,
    close_position: float = 1.0,
) -> TailSessionSignal:
    return TailSessionSignal(
        symbol=symbol,
        trade_date=date(2026, 6, 12),
        strength=strength,
        last_price=10.0,
        volume_ratio=volume_ratio,
        tail_return=tail_return,
        reason="fixture",
        tail_high_return=tail_high_return,
        pullback_from_high=pullback_from_high,
        close_position=close_position,
    )


def test_v2_scorer_assigns_strong_confirmation_for_high_quality_tail_signal() -> None:
    rows = score_tail_signals([
        _signal("000001.SZ", strength=0.82, volume_ratio=2.1, tail_return=0.012)
    ])

    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "000001.SZ"
    assert row.layer == "strong"
    assert row.action == "trade_candidate"
    assert row.total_score >= 70
    assert row.breakdown.tail_money >= 70
    assert row.breakdown.price_action >= 60
    assert "强确认" in row.explanation


def test_v2_scorer_assigns_watchlist_for_moderate_but_tradeable_signal() -> None:
    rows = score_tail_signals([
        _signal("000002.SZ", strength=0.48, volume_ratio=1.28, tail_return=0.002)
    ])

    row = rows[0]
    assert row.layer == "watchlist"
    assert row.action == "observe_next_open"
    assert 45 <= row.total_score < 70
    assert "观察" in row.explanation


def test_v2_scorer_keeps_weak_scoreable_signal_visible() -> None:
    rows = score_tail_signals([
        _signal("000003.SZ", strength=0.22, volume_ratio=0.92, tail_return=-0.003)
    ])

    row = rows[0]
    assert row.layer == "weak"
    assert row.action == "no_trade"
    assert row.total_score < 45
    assert row.risks


def test_v2_scorer_filters_spike_then_pullback_signal_from_trade_candidates() -> None:
    rows = score_tail_signals([
        _signal(
            "600198.SH",
            strength=1.0,
            volume_ratio=6.7,
            tail_return=0.045,
            tail_high_return=0.09,
            pullback_from_high=-0.045,
            close_position=0.22,
        )
    ])

    row = rows[0]
    assert row.symbol == "600198.SH"
    assert row.action != "trade_candidate"
    assert row.layer in {"watchlist", "weak"}
    assert any("冲高回落" in risk for risk in row.risks)


def test_v2_scorer_keeps_overheated_tail_return_out_of_trade_candidates() -> None:
    rows = score_tail_signals([
        _signal("000004.SZ", strength=1.0, volume_ratio=2.2, tail_return=0.028)
    ])

    row = rows[0]
    assert row.action == "observe_next_open"
    assert row.layer == "watchlist"
    assert any("涨幅过热" in risk for risk in row.risks)


def test_v2_scorer_keeps_excessive_volume_spike_out_of_trade_candidates() -> None:
    rows = score_tail_signals([
        _signal("000005.SZ", strength=1.0, volume_ratio=7.5, tail_return=0.018)
    ])

    row = rows[0]
    assert row.action == "observe_next_open"
    assert row.layer == "watchlist"
    assert any("过度放量" in risk for risk in row.risks)


def test_v2_scorer_allows_high_volume_when_price_action_is_orderly() -> None:
    rows = score_tail_signals([
        _signal(
            "000006.SZ",
            strength=1.0,
            volume_ratio=7.5,
            tail_return=0.008,
            tail_high_return=0.01,
            pullback_from_high=-0.001,
            close_position=0.92,
        )
    ])

    row = rows[0]
    assert row.layer == "strong"
    assert row.action == "trade_candidate"
    assert not any("过度放量" in risk for risk in row.risks)
