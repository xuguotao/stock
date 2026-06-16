"""ClickHouse-backed stock data source."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import Any

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo


class ClickHouseStockDataSource(DataSourceBase):
    """Read A-share data from ClickHouse."""

    name = "clickhouse"

    def __init__(
        self,
        host: str = "10.211.49.42",
        user: str = "default",
        password: str = "stock123",
        database: str = "stock",
        client: Any | None = None,
    ):
        super().__init__(rate_limit=0.0)
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self._client = client

    @classmethod
    def from_env(cls) -> "ClickHouseStockDataSource | None":
        """Create from STOCK_CLICKHOUSE_* env vars when enabled."""
        host = os.getenv("STOCK_CLICKHOUSE_HOST")
        if not host:
            return None
        return cls(
            host=host,
            user=os.getenv("STOCK_CLICKHOUSE_USER", "default"),
            password=os.getenv("STOCK_CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("STOCK_CLICKHOUSE_DATABASE", "stock"),
        )

    def fetch_stock_list(self) -> list[StockInfo]:
        rows = self._execute(
            """
            select symbol, name, industry, market, list_date
            from stocks
            order by symbol
            """
        )
        result = []
        for code, name, industry, _market, list_date in rows:
            stock_name = str(name or "")
            result.append(
                StockInfo(
                    symbol=format_symbol(str(code)),
                    code=str(code).zfill(6),
                    name=stock_name,
                    industry=str(industry or ""),
                    list_date=_as_date(list_date),
                    is_st=is_st(stock_name),
                )
            )
        return result

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        if frequency != "daily":
            return pd.DataFrame()
        rows = self._execute(
            """
            select symbol, date, open, high, low, close, volume, amount
            from daily_kline
            where symbol = %(symbol)s and date >= %(start)s and date <= %(end)s
            order by date
            """,
            {"symbol": _code(symbol), "start": start, "end": end},
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
        )
        return _daily_rows(df)

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        if frequency != "5m":
            return pd.DataFrame()
        start = datetime.combine(trade_date, time(0, 0))
        end = datetime.combine(trade_date, time(23, 59, 59))
        rows = self._execute(
            """
            select symbol, datetime, open, high, low, close, volume, amount
            from minute5_kline
            where symbol = %(symbol)s and datetime >= %(start)s and datetime <= %(end)s
            order by datetime
            """,
            {"symbol": _code(symbol), "start": start, "end": end},
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=["symbol", "datetime", "open", "high", "low", "close", "volume", "amount"],
        )
        return _intraday_rows(df)

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        return pd.DataFrame()

    def rank_liquid_symbols(
        self,
        start: date,
        end: date,
        limit: int,
        min_bars: int,
        min_end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        having = "having bars >= %(min_bars)s"
        params: dict[str, Any] = {
            "start": start,
            "end": end,
            "min_bars": min_bars,
            "limit": limit,
        }
        if min_end_date is not None:
            having += " and end_date >= %(min_end_date)s"
            params["min_end_date"] = min_end_date
        rows = self._execute(
            f"""
            select
                symbol,
                count() as bars,
                max(date) as end_date,
                avg(amount) as avg_amount,
                avg(volume) as avg_volume
            from daily_kline
            where date >= %(start)s and date <= %(end)s
            group by symbol
            {having}
            order by avg_amount desc, avg_volume desc, symbol asc
            limit %(limit)s
            """,
            params,
        )
        return [
            {
                "symbol": format_symbol(str(symbol)),
                "bars": int(bars or 0),
                "end_date": _as_date(end_date),
                "avg_amount": float(avg_amount or 0),
                "avg_volume": float(avg_volume or 0),
            }
            for symbol, bars, end_date, avg_amount, avg_volume in rows
        ]

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        return []

    def _execute(self, query: str, params: dict[str, Any] | None = None) -> list[tuple]:
        return self._client_instance().execute(query, params)

    def _client_instance(self) -> Any:
        if self._client is None:
            from clickhouse_driver import Client

            self._client = Client(
                self.host,
                user=self.user,
                password=self.password,
                database=self.database,
            )
        return self._client


def _daily_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["symbol"] = result["symbol"].astype(str).map(format_symbol)
    result["date"] = pd.to_datetime(result["date"]).dt.date
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    result["volume"] = result["volume"].astype(int)
    result["adjusted_close"] = result["close"]
    return result[
        ["date", "open", "high", "low", "close", "volume", "amount", "adjusted_close", "symbol"]
    ]


def _intraday_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["symbol"] = result["symbol"].astype(str).map(format_symbol)
    result["datetime"] = pd.to_datetime(result["datetime"])
    result["time"] = result["datetime"].dt.time
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    result["volume"] = result["volume"].astype(int)
    return result[
        ["time", "datetime", "open", "high", "low", "close", "volume", "amount", "symbol"]
    ]


def _code(symbol: str) -> str:
    return symbol.split(".")[0].zfill(6)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None
