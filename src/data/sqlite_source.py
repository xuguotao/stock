"""SQLite-backed local stock data source."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo


class SQLiteStockDataSource(DataSourceBase):
    """Read local A-share data from a SQLite database."""

    name = "sqlite"

    def __init__(self, db_path: str | Path = "data/stock.db"):
        super().__init__(rate_limit=0.0)
        self.db_path = Path(db_path)

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        """Fetch daily bars from the local SQLite database."""
        if frequency != "daily":
            return pd.DataFrame()
        code = symbol.split(".")[0].zfill(6)
        sql = """
            select symbol, date, open, high, low, close, volume, amount
            from daily_kline
            where symbol = ? and date >= ? and date <= ?
            order by date
        """
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(code, start.isoformat(), end.isoformat()))
        if df.empty:
            return pd.DataFrame()
        return _daily_rows(df)

    def fetch_stock_list(self) -> list[StockInfo]:
        """Fetch all stock metadata from the local SQLite database."""
        sql = """
            select symbol, name, industry, market, list_date
            from stocks
            order by symbol
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        stocks = []
        for code, name, industry, _market, list_date in rows:
            parsed_list_date = _parse_date(list_date)
            stock_name = str(name or "")
            stocks.append(
                StockInfo(
                    symbol=format_symbol(str(code)),
                    code=str(code).zfill(6),
                    name=stock_name,
                    industry=str(industry or ""),
                    list_date=parsed_list_date,
                    is_st=is_st(stock_name),
                )
            )
        return stocks

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        """Fetch 5-minute bars from the local SQLite database."""
        if frequency != "5m":
            return pd.DataFrame()
        code = symbol.split(".")[0].zfill(6)
        day = trade_date.isoformat()
        sql = """
            select symbol, datetime, open, high, low, close, volume, amount
            from minute5_kline
            where symbol = ? and datetime >= ? and datetime <= ?
            order by datetime
        """
        with self._connect() as conn:
            df = pd.read_sql_query(
                sql,
                conn,
                params=(code, f"{day} 00:00:00", f"{day} 23:59:59"),
            )
        if df.empty:
            return pd.DataFrame()
        return _intraday_rows(df)

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Realtime quotes are not stored in the SQLite snapshot."""
        return pd.DataFrame()

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        """Financial statement mapping is intentionally deferred."""
        return []

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)


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


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
