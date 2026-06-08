"""Abstract base classes for data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Protocol

import pandas as pd

from src.data.models import DailyBar, FinancialStatement, StockInfo


class DataSource(Protocol):
    """Protocol for all data source adapters.

    Implementations must provide methods to fetch market data.
    The DataAggregator will call these methods in priority order.
    """

    name: str

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        """Fetch daily bars for a single symbol.

        Returns DataFrame with columns:
            date, open, high, low, close, volume, amount, adjusted_close
        Index is not set; caller should set MultiIndex (date, symbol).
        """
        ...

    def fetch_stock_list(self) -> list[StockInfo]:
        """Fetch the list of all A-share stocks."""
        ...

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch real-time quotes for given symbols.

        Returns DataFrame with columns:
            symbol, price, change_pct, volume, amount, timestamp
        """
        ...

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        """Fetch historical financial statements for a symbol."""
        ...


class DataSourceBase(ABC):
    """ABC with shared rate limiting and error handling."""

    name: str = "base"

    def __init__(self, rate_limit: float = 0.1):
        """Initialize with rate limit (seconds between requests)."""
        self._rate_limit = rate_limit
        self._last_request: float = 0

    def _wait_for_rate_limit(self) -> None:
        """Block until rate limit allows next request."""
        import time
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_request = time.time()

    def _bars_to_df(self, bars: list[DailyBar]) -> pd.DataFrame:
        """Convert list of DailyBar to DataFrame."""
        if not bars:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "amount": b.amount,
                "adjusted_close": b.adjusted_close,
            }
            for b in bars
        ])
