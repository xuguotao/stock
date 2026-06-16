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
        ranking = _rank_liquid_symbols_from_source(
            aggregator=aggregator,
            start=liquidity_start,
            end=liquidity_end,
            limit=limit,
            min_bars=liquidity_min_bars,
            min_end_date=liquidity_min_end_date,
        )
        if not ranking:
            ranking = CacheBarRepository(bars_cache_dir).rank_liquid_symbols(
                start=liquidity_start,
                end=liquidity_end,
                limit=limit,
                min_bars=liquidity_min_bars,
                min_end_date=liquidity_min_end_date,
            )
        symbols = [row["symbol"] for row in ranking]
        if symbols:
            if len(symbols) >= limit:
                return symbols
            _append_default_scan_symbols(aggregator, symbols, limit)
            return symbols

    symbols = []
    _append_default_scan_symbols(aggregator, symbols, limit)
    return symbols


def _rank_liquid_symbols_from_source(
    *,
    aggregator: Any,
    start: date,
    end: date,
    limit: int,
    min_bars: int,
    min_end_date: date | None,
) -> list[dict[str, Any]]:
    ranker = getattr(aggregator, "rank_liquid_symbols", None)
    if ranker is None:
        return []
    try:
        return ranker(
            start=start,
            end=end,
            limit=limit,
            min_bars=min_bars,
            min_end_date=min_end_date,
        )
    except Exception:
        return []


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


def _append_default_scan_symbols(aggregator: Any, symbols: list[str], limit: int) -> None:
    seen = set(symbols)
    for symbol in _default_scan_symbols(aggregator):
        if symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
        if len(symbols) >= limit:
            break


def _default_scan_symbols(aggregator: Any) -> list[str]:
    get_stock_list = getattr(aggregator, "get_stock_list", None)
    if get_stock_list is not None:
        try:
            stocks = get_stock_list()
        except Exception:
            stocks = []
        symbols = [
            stock.symbol
            for stock in stocks
            if not getattr(stock, "is_st", False)
        ]
        if symbols:
            return _balance_symbols_by_exchange(symbols)
    return _balance_symbols_by_exchange(aggregator.get_csi300_symbols())


def _balance_symbols_by_exchange(symbols: list[str]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for symbol in symbols:
        exchange = symbol.rsplit(".", 1)[-1] if "." in symbol else ""
        grouped.setdefault(exchange, []).append(symbol)

    balanced: list[str] = []
    while grouped:
        for exchange in list(grouped):
            group = grouped[exchange]
            balanced.append(group.pop(0))
            if not group:
                del grouped[exchange]
    return balanced
