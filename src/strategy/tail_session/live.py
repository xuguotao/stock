"""Live tail-session scan helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.constants import format_symbol
from src.data.bar_repository import CacheBarRepository


@dataclass(frozen=True)
class MarketBreadthResult:
    """Market breadth over a scan universe."""

    breadth: float
    above_count: int
    symbol_count: int


def prices_from_quotes(quotes: pd.DataFrame | None, fallback_signals: list[Any]) -> dict[str, float]:
    """Build execution prices from realtime quotes with signal prices as fallback."""
    prices: dict[str, float] = {}
    if quotes is not None and not quotes.empty and "symbol" in quotes.columns:
        price_col = "price" if "price" in quotes.columns else "close"
        if price_col in quotes.columns:
            prices.update({
                str(row["symbol"]): float(row[price_col])
                for _, row in quotes.iterrows()
                if float(row[price_col]) > 0
            })

    for signal in fallback_signals:
        prices.setdefault(signal.symbol, signal.last_price)
    return prices


def resolve_scan_symbols(
    aggregator,
    raw_symbols: list[str] | None,
    limit: int,
    universe: str,
    bars_cache_dir: str | Path,
    liquidity_start: date,
    liquidity_end: date,
    liquidity_min_bars: int,
    liquidity_min_end_date: date | None,
) -> list[str]:
    """Resolve the live scan universe from explicit symbols, cache, or default pool."""
    if raw_symbols:
        return [format_symbol(symbol) for symbol in raw_symbols]

    if universe == "liquid-cache":
        ranking = CacheBarRepository(bars_cache_dir).rank_liquid_symbols(
            start=liquidity_start,
            end=liquidity_end,
            limit=limit,
            min_bars=liquidity_min_bars,
            min_end_date=liquidity_min_end_date,
        )
        symbols = [row["symbol"] for row in ranking]
        if symbols:
            return symbols

    return aggregator.get_csi300_symbols()[:limit]


def calculate_market_breadth_above_ma20(
    symbols: list[str],
    bars_cache_dir: str | Path,
    trade_date: date,
    quotes: pd.DataFrame | None = None,
    ma_window: int = 20,
) -> MarketBreadthResult:
    """Calculate the fraction of symbols trading above MA20."""
    quote_prices = _quote_prices(quotes)
    above_count = 0
    symbol_count = 0
    end_ts = pd.Timestamp(trade_date)
    repository = CacheBarRepository(bars_cache_dir)

    for symbol in symbols:
        bars = repository.load_latest_until(symbol, end_ts)
        if len(bars) < ma_window:
            continue

        close = pd.to_numeric(bars["close"], errors="coerce").dropna()
        if len(close) < ma_window:
            continue

        ma_value = float(close.tail(ma_window).mean())
        price = quote_prices.get(symbol, float(close.iloc[-1]))
        if price <= 0 or ma_value <= 0:
            continue

        symbol_count += 1
        if price > ma_value:
            above_count += 1

    breadth = above_count / symbol_count if symbol_count else 0.0
    return MarketBreadthResult(
        breadth=round(breadth, 6),
        above_count=above_count,
        symbol_count=symbol_count,
    )


def _quote_prices(quotes: pd.DataFrame | None) -> dict[str, float]:
    if quotes is None or quotes.empty or "symbol" not in quotes.columns:
        return {}
    price_col = "price" if "price" in quotes.columns else "close"
    if price_col not in quotes.columns:
        return {}
    prices = {}
    for _, row in quotes.iterrows():
        price = float(row[price_col])
        if price > 0:
            prices[str(row["symbol"])] = price
    return prices
