"""Watchlist monitoring helpers.

The pure functions in this module classify manually configured entry zones
against objective price, return, and volume metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml


@dataclass(frozen=True)
class WatchlistLevels:
    observe: tuple[float, float]
    entry: tuple[float, float]
    add: tuple[float, float]
    invalid: float
    breakout: float | None = None


@dataclass(frozen=True)
class WatchlistStockConfig:
    symbol: str
    name: str
    theme: str
    notes: str
    levels: WatchlistLevels


@dataclass(frozen=True)
class WatchlistConfig:
    stocks: list[WatchlistStockConfig]


@dataclass(frozen=True)
class WatchlistStockAnalysis:
    symbol: str
    name: str
    theme: str
    notes: str
    latest_price: float | None
    daily_change_pct: float | None
    return_5d: float | None
    return_20d: float | None
    ma5: float | None
    ma20: float | None
    volume_ratio: float | None
    status: str
    reasons: list[str]
    levels: WatchlistLevels
    data_status: str = "ok"
    quote_snapshot_at: str | None = None
    quote_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "theme": self.theme,
            "notes": self.notes,
            "latest_price": self.latest_price,
            "daily_change_pct": self.daily_change_pct,
            "return_5d": self.return_5d,
            "return_20d": self.return_20d,
            "ma5": self.ma5,
            "ma20": self.ma20,
            "volume_ratio": self.volume_ratio,
            "status": self.status,
            "reasons": self.reasons,
            "levels": {
                "observe": list(self.levels.observe),
                "entry": list(self.levels.entry),
                "add": list(self.levels.add),
                "invalid": self.levels.invalid,
                "breakout": self.levels.breakout,
            },
            "data_status": self.data_status,
            "quote_snapshot_at": self.quote_snapshot_at,
            "quote_time": self.quote_time,
        }


@dataclass(frozen=True)
class WatchlistReport:
    trade_date: str
    items: list[WatchlistStockAnalysis]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "summary": summarize_statuses(self.items),
            "items": [item.to_dict() for item in self.items],
        }


QuoteLookup = Callable[[str], dict[str, Any] | None]
BarsLookup = Callable[[str], pd.DataFrame | None]


def load_watchlist_config(path: str | Path) -> WatchlistConfig:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    stocks = []
    for raw in payload.get("stocks", []):
        levels = raw["levels"]
        stocks.append(
            WatchlistStockConfig(
                symbol=str(raw["symbol"]),
                name=str(raw["name"]),
                theme=str(raw.get("theme", "")),
                notes=str(raw.get("notes", "")),
                levels=WatchlistLevels(
                    observe=_range(levels["observe"], "observe"),
                    entry=_range(levels["entry"], "entry"),
                    add=_range(levels["add"], "add"),
                    invalid=float(levels["invalid"]),
                    breakout=float(levels["breakout"]) if levels.get("breakout") is not None else None,
                ),
            )
        )
    if not stocks:
        raise ValueError(f"{config_path} must contain at least one stock")
    return WatchlistConfig(stocks=stocks)


def compute_stock_metrics(bars: pd.DataFrame) -> dict[str, float | None]:
    if bars is None or bars.empty or "close" not in bars.columns:
        return {"return_5d": None, "return_20d": None, "ma5": None, "ma20": None, "volume_ratio": None}
    df = bars.copy()
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    volumes = pd.to_numeric(df.get("volume", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "return_5d": _period_return(closes, 5),
        "return_20d": _period_return(closes, 20),
        "ma5": _mean_tail(closes, 5),
        "ma20": _mean_tail(closes, 20),
        "volume_ratio": _volume_ratio(volumes, 5),
    }


def classify_watchlist_stock(
    stock: WatchlistStockConfig,
    *,
    latest_price: float | None,
    daily_change_pct: float | None,
    return_5d: float | None,
    return_20d: float | None,
    volume_ratio: float | None,
    ma5: float | None = None,
    ma20: float | None = None,
    data_status: str = "ok",
    quote_snapshot_at: str | None = None,
    quote_time: str | None = None,
) -> WatchlistStockAnalysis:
    reasons: list[str] = []
    status = "neutral"
    levels = stock.levels

    if latest_price is None:
        return WatchlistStockAnalysis(
            symbol=stock.symbol,
            name=stock.name,
            theme=stock.theme,
            notes=stock.notes,
            latest_price=None,
            daily_change_pct=daily_change_pct,
            return_5d=return_5d,
            return_20d=return_20d,
            ma5=ma5,
            ma20=ma20,
            volume_ratio=volume_ratio,
            status="neutral",
            reasons=["最新行情不可用，仅展示配置区间。"],
            levels=levels,
            data_status=data_status,
            quote_snapshot_at=quote_snapshot_at,
            quote_time=quote_time,
        )

    if latest_price <= levels.invalid:
        status = "risk_off"
        reasons.append(f"价格 {latest_price:.2f} 已低于失效位 {levels.invalid:.2f}。")
    elif _inside(latest_price, levels.add):
        status = "add_zone"
        reasons.append(f"价格 {latest_price:.2f} 进入加仓区 {levels.add[0]:.2f}-{levels.add[1]:.2f}。")
    elif _inside(latest_price, levels.entry):
        status = "entry_zone"
        reasons.append(f"价格 {latest_price:.2f} 进入试仓区 {levels.entry[0]:.2f}-{levels.entry[1]:.2f}。")
    elif _inside(latest_price, levels.observe) or latest_price <= levels.observe[1] * 1.02:
        status = "watch_pullback"
        reasons.append(f"价格 {latest_price:.2f} 接近观察区 {levels.observe[0]:.2f}-{levels.observe[1]:.2f}。")
    elif levels.breakout is not None and latest_price >= levels.breakout and (volume_ratio or 0) >= 1.2:
        status = "breakout_confirm"
        reasons.append(f"价格突破 {levels.breakout:.2f} 且量能达到近5日均量的 {volume_ratio:.2f} 倍。")
    elif (return_5d is not None and return_5d > 0.15) or (return_20d is not None and return_20d > 0.35):
        status = "hot_wait"
        reasons.append("近期涨幅过大，优先等待回踩或缩量企稳。")
    else:
        reasons.append("未触发明确买点或风险条件。")

    if daily_change_pct is not None:
        reasons.append(f"当日涨跌幅 {daily_change_pct:.2f}%。")
    if return_5d is not None:
        reasons.append(f"近5日涨幅 {return_5d * 100:.2f}%。")
    if return_20d is not None:
        reasons.append(f"近20日涨幅 {return_20d * 100:.2f}%。")

    return WatchlistStockAnalysis(
        symbol=stock.symbol,
        name=stock.name,
        theme=stock.theme,
        notes=stock.notes,
        latest_price=round(float(latest_price), 4),
        daily_change_pct=daily_change_pct,
        return_5d=return_5d,
        return_20d=return_20d,
        ma5=ma5,
        ma20=ma20,
        volume_ratio=volume_ratio,
        status=status,
        reasons=reasons,
        levels=levels,
        data_status=data_status,
        quote_snapshot_at=quote_snapshot_at,
        quote_time=quote_time,
    )


def summarize_statuses(items: list[WatchlistStockAnalysis]) -> dict[str, int]:
    summary = {status: 0 for status in [
        "entry_zone",
        "add_zone",
        "watch_pullback",
        "hot_wait",
        "breakout_confirm",
        "risk_off",
        "neutral",
    ]}
    for item in items:
        summary[item.status] = summary.get(item.status, 0) + 1
    return summary


def build_watchlist_report(
    config: WatchlistConfig,
    *,
    trade_date: date,
    quote_lookup: QuoteLookup,
    bars_lookup: BarsLookup,
) -> WatchlistReport:
    items: list[WatchlistStockAnalysis] = []
    for stock in config.stocks:
        quote = quote_lookup(stock.symbol) or {}
        bars = bars_lookup(stock.symbol)
        metrics = compute_stock_metrics(bars) if bars is not None else compute_stock_metrics(pd.DataFrame())
        items.append(
            classify_watchlist_stock(
                stock,
                latest_price=quote.get("latest_price"),
                daily_change_pct=quote.get("daily_change_pct"),
                return_5d=metrics.get("return_5d"),
                return_20d=metrics.get("return_20d"),
                ma5=metrics.get("ma5"),
                ma20=metrics.get("ma20"),
                volume_ratio=metrics.get("volume_ratio"),
                data_status=quote.get("data_status", "ok"),
                quote_snapshot_at=quote.get("quote_snapshot_at"),
                quote_time=quote.get("quote_time"),
            )
        )
    return WatchlistReport(trade_date=trade_date.isoformat(), items=items)


def _range(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain exactly two values")
    low, high = float(value[0]), float(value[1])
    return (min(low, high), max(low, high))


def _period_return(values: pd.Series, periods: int) -> float | None:
    if len(values) <= periods:
        return None
    base = float(values.iloc[-periods - 1])
    if base == 0:
        return None
    return round(float(values.iloc[-1]) / base - 1, 6)


def _mean_tail(values: pd.Series, window: int) -> float | None:
    if len(values) < window:
        return None
    return round(float(values.tail(window).mean()), 6)


def _volume_ratio(values: pd.Series, window: int) -> float | None:
    if len(values) <= window:
        return None
    recent_average = float(values.iloc[-window - 1:-1].mean())
    if recent_average == 0:
        return None
    return round(float(values.iloc[-1]) / recent_average, 6)


def _inside(price: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= price <= bounds[1]
