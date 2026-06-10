"""Intraday scanner for tail-session price-volume signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

import pandas as pd


@dataclass(frozen=True)
class TailSessionSignal:
    """Confirmed or candidate tail-session signal."""

    symbol: str
    trade_date: date
    strength: float
    last_price: float
    volume_ratio: float
    tail_return: float
    reason: str


class IntradayScanner:
    """Scan 5-minute bars for tail-session price and volume confirmation."""

    def __init__(
        self,
        aggregator,
        frequency: str = "5m",
        tail_start: time = time(14, 30),
        tail_end: time = time(15, 0),
        volume_ratio_threshold: float = 1.5,
        min_tail_return: float = 0.0,
        confirmation_count: int = 3,
    ):
        self.aggregator = aggregator
        self.frequency = frequency
        self.tail_start = tail_start
        self.tail_end = tail_end
        self.volume_ratio_threshold = volume_ratio_threshold
        self.min_tail_return = min_tail_return
        self.confirmation_count = confirmation_count
        self._confirmations: dict[str, int] = {}

    def scan(self, symbols: list[str], trade_date: date) -> list[TailSessionSignal]:
        """Return candidate signals for symbols passing current tail-session checks."""
        candidates = []
        for symbol in symbols:
            bars = self.aggregator.get_intraday_bars(symbol, trade_date, self.frequency)
            signal = self._scan_symbol(symbol, trade_date, bars)
            if signal is not None:
                candidates.append(signal)
        return candidates

    def confirm(self, candidates: list[TailSessionSignal]) -> list[TailSessionSignal]:
        """Require a symbol to pass several consecutive scans before trading."""
        candidate_by_symbol = {candidate.symbol: candidate for candidate in candidates}

        for symbol in list(self._confirmations):
            if symbol not in candidate_by_symbol:
                self._confirmations.pop(symbol, None)

        confirmed = []
        for symbol, signal in candidate_by_symbol.items():
            count = self._confirmations.get(symbol, 0) + 1
            self._confirmations[symbol] = count
            if count >= self.confirmation_count:
                confirmed.append(signal)

        return confirmed

    def _scan_symbol(
        self,
        symbol: str,
        trade_date: date,
        bars: pd.DataFrame,
    ) -> TailSessionSignal | None:
        if bars is None or bars.empty:
            return None
        if "time" not in bars.columns or "volume" not in bars.columns:
            return None

        ordered = bars.sort_values("datetime" if "datetime" in bars.columns else "time")
        times = ordered["time"]
        tail_mask = times.between(self.tail_start, self.tail_end, inclusive="both")
        tail = ordered[tail_mask]
        baseline = ordered[~tail_mask]

        if tail.empty or baseline.empty:
            return None

        base_volume = float(baseline["volume"].mean())
        tail_volume = float(tail["volume"].mean())
        if base_volume <= 0:
            return None

        volume_ratio = tail_volume / base_volume
        first_open = float(tail["open"].iloc[0])
        last_close = float(tail["close"].iloc[-1])
        if first_open <= 0:
            return None

        tail_return = (last_close - first_open) / first_open
        if volume_ratio < self.volume_ratio_threshold:
            return None
        if tail_return < self.min_tail_return:
            return None

        strength = min(1.0, 0.5 * (volume_ratio / self.volume_ratio_threshold) + 10 * max(tail_return, 0))
        return TailSessionSignal(
            symbol=symbol,
            trade_date=trade_date,
            strength=float(strength),
            last_price=last_close,
            volume_ratio=volume_ratio,
            tail_return=tail_return,
            reason=f"tail price-volume confirmation: volume_ratio={volume_ratio:.2f}, return={tail_return:.2%}",
        )
