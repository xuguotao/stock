"""Backend adapter for the watchlist monitor page."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.monitoring.watchlist import build_watchlist_report, load_watchlist_config


DEFAULT_WATCHLIST_CONFIG = Path("config/watchlist_monitor.yaml")


def get_watchlist_report(
    trade_date: date | None = None,
    *,
    config_path: str | Path = DEFAULT_WATCHLIST_CONFIG,
    aggregator: DataAggregator | None = None,
) -> dict[str, Any]:
    """Build a watchlist report from configured levels and daily bars."""
    end = trade_date or date.today()
    source = aggregator or DataAggregator()
    config = load_watchlist_config(config_path)
    snapshot_quotes = _latest_quote_snapshots(source, [stock.symbol for stock in config.stocks], end)

    def quote_lookup(symbol: str) -> dict[str, Any]:
        snapshot = snapshot_quotes.get(format_symbol(symbol))
        if snapshot:
            return snapshot
        bars = _daily_bars(source, symbol, end, days=90)
        if bars is None or bars.empty:
            return {"latest_price": None, "daily_change_pct": None, "data_status": "quote_unavailable"}
        df = bars.copy().sort_values("date")
        closes = pd.to_numeric(df["close"], errors="coerce").dropna()
        if closes.empty:
            return {"latest_price": None, "daily_change_pct": None, "data_status": "quote_unavailable"}
        latest = float(closes.iloc[-1])
        previous = float(closes.iloc[-2]) if len(closes) > 1 else None
        daily_change_pct = round((latest / previous - 1) * 100, 4) if previous else None
        return {"latest_price": latest, "daily_change_pct": daily_change_pct, "data_status": "ok"}

    def bars_lookup(symbol: str):
        return _daily_bars(source, symbol, end, days=120)

    return build_watchlist_report(
        config,
        trade_date=end,
        quote_lookup=quote_lookup,
        bars_lookup=bars_lookup,
    ).to_dict()


def get_watchlist_config(
    *,
    config_path: str | Path = DEFAULT_WATCHLIST_CONFIG,
) -> dict[str, Any]:
    """Return the configured watchlist without live analysis."""
    config = load_watchlist_config(config_path)
    return {
        "items": [
            {
                "symbol": stock.symbol,
                "name": stock.name,
                "theme": stock.theme,
                "notes": stock.notes,
                "levels": {
                    "observe": list(stock.levels.observe),
                    "entry": list(stock.levels.entry),
                    "add": list(stock.levels.add),
                    "invalid": stock.levels.invalid,
                    "breakout": stock.levels.breakout,
                },
            }
            for stock in config.stocks
        ]
    }


def _daily_bars(source: DataAggregator, symbol: str, end: date, *, days: int) -> pd.DataFrame:
    normalized = format_symbol(symbol)
    return source.get_bars(normalized, end - timedelta(days=days), end, "daily")


def _latest_quote_snapshots(
    source: DataAggregator,
    symbols: list[str],
    trade_date: date,
) -> dict[str, dict[str, Any]]:
    for data_source in source.sources:
        fetcher = getattr(data_source, "fetch_latest_quote_snapshots", None)
        if fetcher is None:
            continue
        try:
            quotes = fetcher(symbols, trade_date)
        except Exception:  # noqa: BLE001 - fall back to daily bars when snapshots are unavailable.
            continue
        if quotes is None or quotes.empty:
            continue
        result: dict[str, dict[str, Any]] = {}
        for _, row in quotes.iterrows():
            symbol = format_symbol(str(row["symbol"]))
            result[symbol] = {
                "latest_price": _float_or_none(row.get("price")),
                "daily_change_pct": _float_or_none(row.get("change_pct")),
                "data_status": "snapshot_ok",
                "quote_snapshot_at": _time_text(row.get("snapshot_at")),
                "quote_time": _time_text(row.get("quote_time")),
            }
        return result
    return {}


def _float_or_none(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), 6)


def _time_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")
