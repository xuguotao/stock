"""ClickHouse-backed stock data source."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pandas as pd

from config.settings import get_settings
from src.core.constants import format_symbol, is_st
from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo


class ClickHouseStockDataSource(DataSourceBase):
    """Read A-share data from ClickHouse."""

    name = "clickhouse"

    def __init__(
        self,
        host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        client: Any | None = None,
    ):
        super().__init__(rate_limit=0.0)
        settings = get_settings().clickhouse
        self.host = host if host is not None else settings.host
        self.user = user if user is not None else settings.user
        self.password = password if password is not None else settings.password
        self.database = database if database is not None else settings.database
        self._client = client

    @classmethod
    def from_env(cls) -> "ClickHouseStockDataSource | None":
        """Create from STOCK_CLICKHOUSE_* env vars when enabled."""
        import os

        host = os.getenv("STOCK_CLICKHOUSE_HOST")
        if not host:
            return None
        return cls()

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
            return self._fetch_quote_snapshot_5m_bars([symbol], trade_date)
        df = pd.DataFrame(
            rows,
            columns=["symbol", "datetime", "open", "high", "low", "close", "volume", "amount"],
        )
        result = _intraday_rows(df)
        fallback = self._fetch_quote_snapshot_5m_bars([symbol], trade_date)
        return _merge_intraday_with_snapshot_fallback(result, fallback)

    def fetch_intraday_bars_batch(
        self,
        symbols: list[str],
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        if frequency != "5m" or not symbols:
            return pd.DataFrame()
        start = datetime.combine(trade_date, time(0, 0))
        end = datetime.combine(trade_date, time(23, 59, 59))
        codes = tuple(_code(symbol) for symbol in symbols)
        rows = self._execute(
            """
            select symbol, datetime, open, high, low, close, volume, amount
            from minute5_kline
            where symbol in %(symbols)s and datetime >= %(start)s and datetime <= %(end)s
            order by symbol, datetime
            """,
            {"symbols": codes, "start": start, "end": end},
        )
        if rows:
            df = _intraday_rows(
                pd.DataFrame(
                    rows,
                    columns=[
                        "symbol",
                        "datetime",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                    ],
                )
            )
            found = set(df["symbol"].dropna().astype(str))
            missing = [symbol for symbol in symbols if format_symbol(symbol) not in found]
        else:
            df = pd.DataFrame()
            missing = symbols
        fallback_symbols = list(dict.fromkeys([*symbols, *missing]))
        fallback = self._fetch_quote_snapshot_5m_bars(fallback_symbols, trade_date)
        return _merge_intraday_with_snapshot_fallback(df, fallback)

    def _fetch_quote_snapshot_5m_bars(self, symbols: list[str], trade_date: date) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        start = datetime.combine(trade_date, time(0, 0))
        end = datetime.combine(trade_date, time(23, 59, 59))
        rows = self._execute(
            """
            select symbol, bucket_start as datetime, open_price, high_price, low_price, close_price, volume, amount
            from stock_quote_snapshots_5m final
            where symbol in %(symbols)s and bucket_start >= %(start)s and bucket_start <= %(end)s
            order by symbol, bucket_start
            """,
            {"symbols": tuple(_code(symbol) for symbol in symbols), "start": start, "end": end},
        )
        if not rows:
            return pd.DataFrame()
        return _intraday_rows(
            pd.DataFrame(
                rows,
                columns=["symbol", "datetime", "open", "high", "low", "close", "volume", "amount"],
            )
        )

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        return self.fetch_latest_quote_snapshots(symbols, date.today())

    def fetch_latest_quote_snapshots(
        self,
        symbols: list[str],
        trade_date: date,
    ) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        codes = tuple(format_symbol(symbol) for symbol in symbols)
        rows = self._execute(
            """
            select
                symbol,
                argMax(name, snapshot_at) as name,
                argMax(price, snapshot_at) as price,
                argMax(change_pct, snapshot_at) as change_pct,
                argMax(volume, snapshot_at) as volume,
                argMax(amount, snapshot_at) as amount,
                argMax(turnover_pct, snapshot_at) as turnover_pct,
                argMax(pe_ttm, snapshot_at) as pe_ttm,
                argMax(pb, snapshot_at) as pb,
                argMax(mcap, snapshot_at) as mcap,
                argMax(float_mcap, snapshot_at) as float_mcap,
                argMax(limit_up, snapshot_at) as limit_up,
                argMax(limit_down, snapshot_at) as limit_down,
                max(snapshot_at) as latest_snapshot_at,
                argMax(quote_time, snapshot_at) as latest_quote_time
            from stock_quote_snapshots
            where symbol in %(symbols)s
                and toDate(snapshot_at) = %(trade_date)s
            group by symbol
            order by symbol
            """,
            {"symbols": codes, "trade_date": trade_date},
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "name",
                "price",
                "change_pct",
                "volume",
                "amount",
                "turnover_pct",
                "pe_ttm",
                "pb",
                "mcap",
                "float_mcap",
                "limit_up",
                "limit_down",
                "snapshot_at",
                "quote_time",
            ],
        )
        df["symbol"] = df["symbol"].astype(str).map(format_symbol)
        for column in [
            "price",
            "change_pct",
            "volume",
            "amount",
            "turnover_pct",
            "pe_ttm",
            "pb",
            "mcap",
            "float_mcap",
            "limit_up",
            "limit_down",
        ]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df["snapshot_at"] = pd.to_datetime(df["snapshot_at"], errors="coerce")
        df["quote_time"] = pd.to_datetime(df["quote_time"], errors="coerce")
        return df

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


def _merge_intraday_with_snapshot_fallback(primary: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    if primary.empty:
        return fallback
    if fallback.empty:
        return primary
    combined = pd.concat(
        [
            primary.assign(_source_priority=0),
            fallback.assign(_source_priority=1),
        ],
        ignore_index=True,
    ).sort_values(["symbol", "datetime", "_source_priority"])
    combined = combined.drop_duplicates(["symbol", "datetime"], keep="first")
    return combined.drop(columns=["_source_priority"]).sort_values(["symbol", "datetime"]).reset_index(drop=True)


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
