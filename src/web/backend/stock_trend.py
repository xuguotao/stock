"""Stock trend analysis helpers for the dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.strategy.scanner import IntradayScanner, TailSessionSignal


def analyze_stock_trend(
    symbol: str,
    *,
    trade_date: date | None = None,
    daily_window: int = 90,
    granularity: str = "5m",
) -> dict[str, Any]:
    """Build daily and intraday trend data for a single stock."""
    normalized_symbol = format_symbol(symbol)
    intraday_granularity = _normalize_granularity(granularity)
    end = trade_date or date.today()
    start = end - timedelta(days=max(30, daily_window * 2))
    aggregator = DataAggregator()
    daily = aggregator.get_bars(normalized_symbol, start, end, "daily")
    intraday = aggregator.get_intraday_bars(normalized_symbol, end, intraday_granularity)
    stock_name = _stock_name(aggregator, normalized_symbol)
    quote = _latest_quote(aggregator, normalized_symbol, end)
    if quote.get("name"):
        stock_name = str(quote["name"])

    daily_rows = _daily_rows(daily, daily_window=daily_window)
    intraday_rows = _intraday_rows(intraday)
    latest_price = quote.get("price") if quote.get("price") is not None else _latest_price(daily_rows, intraday_rows)
    metrics = _metrics(daily_rows, intraday_rows)
    tail_evidence = _tail_evidence(aggregator, normalized_symbol, end, intraday, intraday_granularity)

    return {
        "symbol": normalized_symbol,
        "name": stock_name,
        "trade_date": end.isoformat(),
        "granularity": intraday_granularity,
        "latest_price": latest_price,
        "latest_intraday_time": intraday_rows[-1]["time"] if intraday_rows else None,
        "quote": quote,
        "metrics": metrics,
        "tail_evidence": tail_evidence,
        "daily": daily_rows,
        "intraday": intraday_rows,
    }


def _normalize_granularity(value: str) -> str:
    return value if value in {"1m", "5m"} else "5m"


def _stock_name(aggregator: DataAggregator, symbol: str) -> str:
    try:
        for stock in aggregator.get_stock_list():
            if stock.symbol == symbol:
                return stock.name
    except Exception:
        return ""
    return ""


def _daily_rows(frame: pd.DataFrame, *, daily_window: int) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    df = frame.copy().sort_values("date").tail(daily_window)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
    df["amount"] = pd.to_numeric(df.get("amount", 0), errors="coerce").fillna(0)
    df["ma5"] = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "date": _date_text(row["date"]),
            "open": _float(row.get("open")),
            "high": _float(row.get("high")),
            "low": _float(row.get("low")),
            "close": _float(row.get("close")),
            "volume": _float(row.get("volume")),
            "amount": _float(row.get("amount")),
            "ma5": _float(row.get("ma5")),
            "ma10": _float(row.get("ma10")),
            "ma20": _float(row.get("ma20")),
            "ma60": _float(row.get("ma60")),
        })
    return rows


def _intraday_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    df = frame.copy().sort_values("datetime" if "datetime" in frame.columns else "time")
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "time": _time_text(row.get("time") or row.get("datetime")),
            "open": _float(row.get("open")),
            "high": _float(row.get("high")),
            "low": _float(row.get("low")),
            "close": _float(row.get("close")),
            "volume": _float(row.get("volume")),
            "amount": _float(row.get("amount")),
        })
    return rows


def _metrics(daily: list[dict[str, Any]], intraday: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [row["close"] for row in daily if isinstance(row.get("close"), float)]
    intraday_closes = [row["close"] for row in intraday if isinstance(row.get("close"), float)]
    return {
        "daily_return_5d": _period_return(closes, 5),
        "daily_return_20d": _period_return(closes, 20),
        "ma5": daily[-1].get("ma5") if daily else None,
        "ma10": daily[-1].get("ma10") if daily else None,
        "ma20": daily[-1].get("ma20") if daily else None,
        "ma60": daily[-1].get("ma60") if daily else None,
        "intraday_return": _period_return(intraday_closes, len(intraday_closes) - 1) if len(intraday_closes) > 1 else None,
        "intraday_volume": sum(row.get("volume") or 0 for row in intraday),
    }


def _tail_evidence(
    aggregator: DataAggregator,
    symbol: str,
    trade_date: date,
    intraday: pd.DataFrame,
    granularity: str,
) -> dict[str, Any]:
    scanner = IntradayScanner(aggregator, frequency=granularity)
    # Reuse scanner scoring so this evidence matches tail live selection.
    signal = scanner._score_symbol(symbol, trade_date, intraday)  # noqa: SLF001
    mode = "tail_window"
    if signal is None:
        signal = scanner._score_recent_window(symbol, trade_date, intraday, preview_window_bars=6)  # noqa: SLF001
        mode = "recent_preview"
    if signal is None:
        return {
            "status": "missing",
            "source": granularity,
            "mode": mode,
            "reason": "分钟数据不足，无法计算尾盘策略证据",
        }
    return _tail_signal_evidence(signal, source=granularity, mode=mode)


def _tail_signal_evidence(signal: TailSessionSignal, *, source: str, mode: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "source": source,
        "mode": mode,
        "strength": round(float(signal.strength), 6),
        "last_price": round(float(signal.last_price), 6),
        "volume_ratio": round(float(signal.volume_ratio), 6),
        "tail_return": round(float(signal.tail_return), 6),
        "tail_high_return": round(float(signal.tail_high_return), 6),
        "pullback_from_high": round(float(signal.pullback_from_high), 6),
        "close_position": round(float(signal.close_position), 6),
        "reason": signal.reason,
    }


def _latest_quote(aggregator: DataAggregator, symbol: str, trade_date: date) -> dict[str, Any]:
    for source in getattr(aggregator, "sources", []):
        fetcher = getattr(source, "fetch_latest_quote_snapshots", None)
        if fetcher is None:
            continue
        try:
            frame = fetcher([symbol], trade_date)
        except Exception:
            continue
        if frame is None or frame.empty:
            continue
        row = frame.iloc[0]
        return {
            "price": _float(row.get("price")),
            "change_pct": _float(row.get("change_pct")),
            "volume": _float(row.get("volume")),
            "amount": _float(row.get("amount")),
            "turnover_pct": _float(row.get("turnover_pct")),
            "pe_ttm": _float(row.get("pe_ttm")),
            "pb": _float(row.get("pb")),
            "mcap": _float(row.get("mcap")),
            "float_mcap": _float(row.get("float_mcap")),
            "limit_up": _float(row.get("limit_up")),
            "limit_down": _float(row.get("limit_down")),
            "snapshot_at": _datetime_text(row.get("snapshot_at")),
            "quote_time": _datetime_text(row.get("quote_time")),
            "name": str(row.get("name") or ""),
            "source": "snapshot",
        }
    return {"source": "bars"}


def _latest_price(daily: list[dict[str, Any]], intraday: list[dict[str, Any]]) -> float | None:
    if intraday:
        return intraday[-1].get("close")
    if daily:
        return daily[-1].get("close")
    return None


def _period_return(values: list[float], periods: int) -> float | None:
    if periods <= 0 or len(values) <= periods:
        return None
    base = values[-periods - 1]
    if not base:
        return None
    return round(values[-1] / base - 1, 6)


def _date_text(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


def _time_text(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    text = str(value)
    return text[-8:] if len(text) >= 8 else text


def _datetime_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None
