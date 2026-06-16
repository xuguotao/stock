"""Optional mootdx data source for Tongdaxin market data."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable

import pandas as pd

from src.core.constants import format_symbol
from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo

logger = logging.getLogger(__name__)

_CATEGORY_BY_FREQUENCY = {
    "daily": 4,
    "1m": 7,
    "5m": 8,
    "15m": 9,
    "30m": 10,
    "60m": 11,
}


def is_mootdx_available() -> bool:
    """Return whether the optional mootdx dependency can be imported."""
    try:
        __import__("mootdx.quotes")
        return True
    except ImportError:
        return False


class MootdxSource(DataSourceBase):
    """mootdx adapter for K-line, intraday bars, and real-time quotes."""

    name = "mootdx"

    def __init__(
        self,
        rate_limit: float = 0.1,
        client_factory: Callable[[], Any] | None = None,
        bar_offset: int = 800,
    ):
        super().__init__(rate_limit=rate_limit)
        self._client_factory = client_factory or _default_client_factory
        self._client_instance: Any | None = None
        self.bar_offset = bar_offset

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        """Fetch daily bars from mootdx and normalize to the project schema."""
        if frequency != "daily":
            return pd.DataFrame()
        raw = self._fetch_bars(symbol, category=_CATEGORY_BY_FREQUENCY["daily"])
        result = _parse_mootdx_bars(raw, symbol, intraday=False)
        if result.empty:
            return result
        return result[(result["date"] >= start) & (result["date"] <= end)].reset_index(drop=True)

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday bars from mootdx."""
        category = _CATEGORY_BY_FREQUENCY.get(frequency)
        if category is None or frequency == "daily":
            return pd.DataFrame()
        raw = self._fetch_bars(symbol, category=category)
        result = _parse_mootdx_bars(raw, symbol, intraday=True)
        if result.empty:
            return result
        return result[result["datetime"].dt.date == trade_date].reset_index(drop=True)

    def fetch_stock_list(self) -> list[StockInfo]:
        return []

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        self._wait_for_rate_limit()
        codes = [_code(symbol) for symbol in symbols]
        try:
            raw = self._client().quotes(symbol=codes)
        except Exception as exc:
            logger.warning("mootdx quotes failed: %s", exc)
            return pd.DataFrame()
        return _parse_mootdx_quotes(raw)

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        return []

    def _fetch_bars(self, symbol: str, category: int) -> pd.DataFrame:
        self._wait_for_rate_limit()
        code = _code(symbol)
        try:
            return self._client().bars(
                symbol=code,
                category=category,
                market=_market(code),
                offset=self.bar_offset,
            )
        except Exception as exc:
            logger.warning("mootdx bars failed for %s category %s: %s", symbol, category, exc)
            return pd.DataFrame()

    def _client(self) -> Any:
        if self._client_instance is None:
            self._client_instance = self._client_factory()
        return self._client_instance


def _default_client_factory() -> Any:
    from mootdx.quotes import Quotes

    return Quotes.factory(market="std")


def _parse_mootdx_bars(raw: Any, symbol: str, *, intraday: bool) -> pd.DataFrame:
    if raw is None:
        return pd.DataFrame()
    df = pd.DataFrame(raw).copy()
    if df.empty:
        return pd.DataFrame()
    if "datetime" not in df.columns:
        return pd.DataFrame()

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).copy()
    if df.empty:
        return pd.DataFrame()
    df["symbol"] = format_symbol(symbol)

    for source, target in [("vol", "volume")]:
        if source in df.columns and target not in df.columns:
            df[target] = df[source]
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column not in df.columns:
            df[column] = 0.0
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df["volume"] = df["volume"].astype(int)

    if intraday:
        df["time"] = df["datetime"].dt.time
        return df[
            ["time", "datetime", "open", "high", "low", "close", "volume", "amount", "symbol"]
        ].sort_values("datetime").reset_index(drop=True)

    df["date"] = df["datetime"].dt.date
    df["adjusted_close"] = df["close"]
    return df[
        ["date", "open", "high", "low", "close", "volume", "amount", "adjusted_close", "symbol"]
    ].sort_values("date").reset_index(drop=True)


def _parse_mootdx_quotes(raw: Any) -> pd.DataFrame:
    df = pd.DataFrame(raw).copy()
    if df.empty:
        return pd.DataFrame()
    code_col = "code" if "code" in df.columns else "symbol"
    if code_col not in df.columns:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["symbol"] = df[code_col].astype(str).map(format_symbol)
    result["name"] = df["name"] if "name" in df.columns else ""
    for column in ["price", "open", "high", "low", "last_close", "vol", "amount"]:
        result[_quote_column_name(column)] = _numeric_series(df, column)

    result["prev_close"] = result.pop("last_close")
    result["volume"] = result.pop("vol").astype(int)
    result["change_pct"] = result.apply(
        lambda row: round((row["price"] - row["prev_close"]) / row["prev_close"] * 100, 2)
        if row["prev_close"] > 0 and row["price"] > 0 else 0.0,
        axis=1,
    )
    for level in range(1, 6):
        for column in [f"bid{level}", f"ask{level}", f"bid_vol{level}", f"ask_vol{level}"]:
            result[column] = _numeric_series(df, column)
    result["timestamp"] = df["servertime"].astype(str) if "servertime" in df.columns else ""
    return result


def _quote_column_name(column: str) -> str:
    return column


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    values = df[column] if column in df.columns else pd.Series(0, index=df.index)
    return pd.to_numeric(values, errors="coerce").fillna(0.0)


def _code(symbol: str) -> str:
    return symbol.split(".")[0].zfill(6)


def _market(code: str) -> int:
    return 1 if code.startswith(("6", "9")) else 0
