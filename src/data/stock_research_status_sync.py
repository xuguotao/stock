"""Build research eligibility status and data gap audit for stocks."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from src.core.constants import is_st


SUPPORTED_MARKETS = {"SH", "SZ", "BJ"}


def sync_stock_research_status(
    *,
    client: Any | None = None,
    checked_at: str | datetime | None = None,
) -> dict[str, Any]:
    clickhouse = client or _default_client()
    checked_time = _datetime_value(checked_at) if checked_at is not None else datetime.now().replace(microsecond=0)
    _ensure_table(clickhouse)
    stocks = _stock_rows(clickhouse)
    daily_latest = _latest_daily_date(clickhouse)
    minute5_trade_date = _latest_minute5_date(clickhouse)
    daily_symbols = _symbols_for_daily_date(clickhouse, daily_latest) if daily_latest else set()
    minute5_symbols = _symbols_for_minute5_date(clickhouse, minute5_trade_date) if minute5_trade_date else set()
    rows = [
        _research_row(
            stock=stock,
            daily_latest=daily_latest,
            daily_symbols=daily_symbols,
            minute5_trade_date=minute5_trade_date,
            minute5_symbols=minute5_symbols,
            checked_at=checked_time,
        )
        for stock in stocks
    ]
    if rows:
        clickhouse.execute(
            """
            insert into stock_research_status
                (symbol, name, market, board, is_st, is_delisting_period, is_delisted,
                 list_date, latest_trade_date, research_eligible, excluded_reasons,
                 daily_latest_date, daily_missing, minute5_trade_date, minute5_missing,
                 source, checked_at)
            values
            """,
            rows,
        )
    eligible_rows = sum(1 for row in rows if row[9])
    return {
        "source": "stock_research_status",
        "total_rows": len(rows),
        "eligible_rows": eligible_rows,
        "excluded_rows": len(rows) - eligible_rows,
        "daily_missing_rows": sum(1 for row in rows if row[12]),
        "minute5_missing_rows": sum(1 for row in rows if row[14]),
        "daily_latest_date": daily_latest.isoformat() if daily_latest else None,
        "minute5_trade_date": minute5_trade_date.isoformat() if minute5_trade_date else None,
    }


def _ensure_table(client: Any) -> None:
    client.execute(
        """
        create table if not exists stock_research_status (
            symbol String,
            name String,
            market LowCardinality(String),
            board LowCardinality(String),
            is_st UInt8,
            is_delisting_period UInt8,
            is_delisted UInt8,
            list_date String,
            latest_trade_date Nullable(Date),
            research_eligible UInt8,
            excluded_reasons String,
            daily_latest_date Nullable(Date),
            daily_missing UInt8,
            minute5_trade_date Nullable(Date),
            minute5_missing UInt8,
            source LowCardinality(String),
            checked_at DateTime
        )
        engine = ReplacingMergeTree(checked_at)
        order by symbol
        """
    )


def _stock_rows(client: Any) -> list[dict[str, Any]]:
    rows = client.execute(
        """
        select symbol, name, market, list_date
        from stocks final
        order by symbol
        """
    )
    result = []
    for symbol, name, market, list_date in rows:
        result.append({
            "symbol": str(symbol).zfill(6),
            "name": str(name or ""),
            "market": str(market or "").upper(),
            "list_date": str(list_date or ""),
        })
    return result


def _latest_daily_date(client: Any) -> date | None:
    rows = client.execute("select max(date) from daily_kline")
    return _date_value(rows[0][0]) if rows and rows[0][0] else None


def _latest_minute5_date(client: Any) -> date | None:
    rows = client.execute("select max(toDate(datetime)) from minute5_kline")
    return _date_value(rows[0][0]) if rows and rows[0][0] else None


def _symbols_for_daily_date(client: Any, value: date) -> set[str]:
    rows = client.execute(
        """
        select distinct symbol
        from daily_kline
        where date = %(date)s
        """,
        {"date": value},
    )
    return {str(row[0]).zfill(6) for row in rows}


def _symbols_for_minute5_date(client: Any, value: date) -> set[str]:
    rows = client.execute(
        """
        select distinct symbol
        from minute5_kline
        where toDate(datetime) = %(date)s
        """,
        {"date": value},
    )
    return {str(row[0]).zfill(6) for row in rows}


def _research_row(
    *,
    stock: dict[str, Any],
    daily_latest: date | None,
    daily_symbols: set[str],
    minute5_trade_date: date | None,
    minute5_symbols: set[str],
    checked_at: datetime,
) -> tuple[Any, ...]:
    symbol = stock["symbol"]
    name = stock["name"]
    market = stock["market"]
    stock_is_st = is_st(name)
    is_delisting_period = _is_delisting_period_name(name)
    is_delisted = False
    daily_missing = bool(daily_latest and symbol not in daily_symbols)
    minute5_missing = bool(minute5_trade_date and symbol not in minute5_symbols)
    reasons = _excluded_reasons(
        name=name,
        market=market,
        stock_is_st=stock_is_st,
        is_delisting_period=is_delisting_period,
        is_delisted=is_delisted,
        daily_missing=daily_missing,
        minute5_missing=minute5_missing,
    )
    return (
        symbol,
        name,
        market,
        _board_from_symbol(symbol, market),
        int(stock_is_st),
        int(is_delisting_period),
        int(is_delisted),
        stock["list_date"],
        daily_latest,
        int(not reasons),
        json.dumps(reasons, ensure_ascii=False),
        daily_latest,
        int(daily_missing),
        minute5_trade_date,
        int(minute5_missing),
        "stock_master_sync",
        checked_at,
    )


def _excluded_reasons(
    *,
    name: str,
    market: str,
    stock_is_st: bool,
    is_delisting_period: bool,
    is_delisted: bool,
    daily_missing: bool,
    minute5_missing: bool,
) -> list[str]:
    reasons = []
    if not name:
        reasons.append("status_unknown")
    if market not in SUPPORTED_MARKETS:
        reasons.append("unsupported_market")
    if stock_is_st:
        reasons.append("st_stock")
    if is_delisting_period:
        reasons.append("delisting_period")
    if is_delisted:
        reasons.append("delisted")
    if daily_missing:
        reasons.append("daily_missing")
    if minute5_missing:
        reasons.append("minute5_missing")
    return reasons


def _is_delisting_period_name(name: str) -> bool:
    return bool(name) and (name.endswith("退") or name.endswith("退市"))


def _board_from_symbol(symbol: str, market: str) -> str:
    if market == "BJ":
        return "BJ"
    if market == "SH" and symbol.startswith("688"):
        return "STAR"
    if market == "SZ" and symbol.startswith("300"):
        return "CHINEXT"
    return "MAIN"


def _datetime_value(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T"))


def _date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _default_client() -> Any:
    from src.data.clickhouse_source import ClickHouseStockDataSource

    return ClickHouseStockDataSource()._client_instance()
