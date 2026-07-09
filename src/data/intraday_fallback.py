"""Fallback helpers for intraday market data sources."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.core.constants import format_symbol


class FallbackIntradaySource:
    """Try multiple intraday sources and return the first non-empty result."""

    def __init__(self, sources: list[Any]) -> None:
        self.sources = sources

    def fetch_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        for source in self.sources:
            bars = source.fetch_intraday_bars(symbol, trade_date, frequency)
            if bars is not None and not bars.empty:
                return bars
        return pd.DataFrame()

    def fetch_intraday_bars_batch(self, symbols: list[str], trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        remaining = list(symbols)
        frames = []
        for source in self.sources:
            if not remaining:
                break
            batch_fetcher = getattr(source, "fetch_intraday_bars_batch", None)
            if batch_fetcher is not None:
                bars = batch_fetcher(remaining, trade_date, frequency)
            else:
                single_frames = [
                    source.fetch_intraday_bars(symbol, trade_date, frequency)
                    for symbol in remaining
                ]
                usable_frames = [frame for frame in single_frames if frame is not None and not frame.empty]
                bars = pd.concat(usable_frames, ignore_index=True) if usable_frames else pd.DataFrame()
            if bars is None or bars.empty or "symbol" not in bars.columns:
                continue
            frames.append(bars)
            found = {format_symbol(symbol) for symbol in bars["symbol"].dropna().unique()}
            remaining = [symbol for symbol in remaining if format_symbol(symbol) not in found]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
