"""Multi-factor scoring for tail-session signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.strategy.scanner import TailSessionSignal


SignalLayer = Literal["strong", "watchlist", "weak"]
SignalAction = Literal["trade_candidate", "observe_next_open", "no_trade"]


@dataclass(frozen=True)
class SignalScoreBreakdown:
    """Component scores for a scored tail-session signal."""

    tail_money: float
    price_action: float
    liquidity: float
    risk_control: float


@dataclass(frozen=True)
class LayeredSignal:
    """A tail-session signal with V2 multi-factor classification."""

    signal: TailSessionSignal
    total_score: float
    layer: SignalLayer
    action: SignalAction
    breakdown: SignalScoreBreakdown
    explanation: str
    risks: list[str]

    @property
    def symbol(self) -> str:
        return self.signal.symbol


def score_tail_signals(signals: list[TailSessionSignal]) -> list[LayeredSignal]:
    """Score and classify tail-session signals into trade, watch, and weak layers."""
    rows = [_score_signal(signal) for signal in signals]
    return sorted(
        rows,
        key=lambda row: (
            row.total_score,
            row.signal.strength,
            row.signal.volume_ratio,
            row.signal.tail_return,
            row.signal.symbol,
        ),
        reverse=True,
    )


def _score_signal(signal: TailSessionSignal) -> LayeredSignal:
    tail_money = _bounded((float(signal.volume_ratio) / 2.0) * 80.0)
    price_action = _bounded(50.0 + float(signal.tail_return) * 2500.0)
    liquidity = _bounded(float(signal.strength) * 100.0)
    risk_control = _risk_control_score(signal)
    total_score = round(
        tail_money * 0.35
        + price_action * 0.30
        + liquidity * 0.20
        + risk_control * 0.15,
        2,
    )
    layer, action, explanation = _classify(total_score, signal)
    return LayeredSignal(
        signal=signal,
        total_score=total_score,
        layer=layer,
        action=action,
        breakdown=SignalScoreBreakdown(
            tail_money=round(tail_money, 2),
            price_action=round(price_action, 2),
            liquidity=round(liquidity, 2),
            risk_control=round(risk_control, 2),
        ),
        explanation=explanation,
        risks=_risks(signal),
    )


def _classify(
    total_score: float,
    signal: TailSessionSignal,
) -> tuple[SignalLayer, SignalAction, str]:
    if (
        total_score >= 60
        and signal.volume_ratio >= 1.5
        and signal.tail_return >= 0
        and not _has_tail_chase_risk(signal)
        and not _has_tail_pullback_risk(signal)
    ):
        return "strong", "trade_candidate", "强确认：尾盘量价配合较好，可进入最终交易候选。"
    if total_score >= 45:
        return "watchlist", "observe_next_open", "观察：已有异动迹象，适合纳入次日开盘/早盘观察。"
    return "weak", "no_trade", "弱信号：保留在排序池用于解释，但不建议交易。"


def _risk_control_score(signal: TailSessionSignal) -> float:
    score = 70.0
    if signal.tail_return < 0:
        score -= 20.0
    if signal.tail_return > 0.035:
        score -= 18.0
    if _has_tail_chase_risk(signal):
        score -= 20.0
    if _has_tail_pullback_risk(signal):
        score -= 35.0
    if signal.volume_ratio < 1.0:
        score -= 12.0
    if signal.strength < 0.35:
        score -= 10.0
    return _bounded(score)


def _risks(signal: TailSessionSignal) -> list[str]:
    risks = []
    if signal.volume_ratio < 1.2:
        risks.append("尾盘量能不足，资金确认偏弱")
    elif signal.volume_ratio < 1.5:
        risks.append("量比未达到强确认阈值")
    if signal.tail_return < 0:
        risks.append("尾盘价格回落，次日延续性不确定")
    if signal.tail_return > 0.02:
        risks.append("尾盘涨幅过热，存在次日兑现压力")
    if _has_excessive_volume_chase_risk(signal):
        risks.append("尾盘过度放量，可能是短线资金抢跑")
    if _has_tail_pullback_risk(signal):
        risks.append("尾盘冲高回落，收盘未能守住拉升区间")
    if signal.strength < 0.45:
        risks.append("综合强度偏弱")
    return risks


def _has_tail_pullback_risk(signal: TailSessionSignal) -> bool:
    pullback = float(getattr(signal, "pullback_from_high", 0.0) or 0.0)
    high_return = float(getattr(signal, "tail_high_return", 0.0) or 0.0)
    close_position = float(getattr(signal, "close_position", 1.0) or 1.0)
    return high_return >= 0.015 and (pullback <= -0.015 or close_position < 0.45)


def _has_tail_chase_risk(signal: TailSessionSignal) -> bool:
    tail_return = float(signal.tail_return)
    return tail_return > 0.02 or _has_excessive_volume_chase_risk(signal)


def _has_excessive_volume_chase_risk(signal: TailSessionSignal) -> bool:
    volume_ratio = float(signal.volume_ratio)
    tail_return = float(signal.tail_return)
    return volume_ratio >= 6.0 and tail_return >= 0.015


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))
