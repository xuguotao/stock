"""Incremental synchronization for ClickHouse 5-minute A-share bars."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.akshare_source import AKShareSource
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.minute5_sync import FallbackIntradaySource
from src.data.sina_source import SinaSource


ProgressCallback = Callable[[int, str, str], None]


def sync_clickhouse_minute5_kline(
    *,
    trade_date: date,
    limit: int = 0,
    symbols: list[str] | None = None,
    source: Any | None = None,
    include_st: bool = False,
    progress: ProgressCallback | None = None,
    db_path: str | Path | None = None,
    client: Any | None = None,
    host: str = "10.211.49.42",
    user: str = "default",
    password: str = "stock123",
    database: str = "stock",
) -> dict[str, Any]:
    """Fetch 5-minute bars and append missing rows into ClickHouse."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    data_source = source or FallbackIntradaySource([
        SinaSource(rate_limit=0.2),
        AKShareSource(rate_limit=0.2),
    ])
    _report(progress, 5, "preparing", "准备 ClickHouse 5m 分钟线更新")

    target_symbols = _target_symbols(
        clickhouse,
        symbols=symbols,
        include_st=include_st,
        limit=limit,
    )
    complete_codes = _complete_codes(clickhouse, trade_date)
    symbols_to_fetch = [symbol for symbol in target_symbols if symbol.split(".")[0] not in complete_codes]

    total = len(symbols_to_fetch)
    skipped = len(target_symbols) - total
    success = 0
    no_data = 0
    failed = 0
    inserted_rows = 0
    no_data_symbols: list[str] = []
    failures: list[dict[str, str]] = []

    if total == 0:
        return {
            "trade_date": trade_date.isoformat(),
            "target_symbols": len(target_symbols),
            "skipped": skipped,
            "success": 0,
            "no_data": 0,
            "no_data_symbols": [],
            "failed": 0,
            "inserted_rows": 0,
            "failures": [],
            "coverage_after": _minute5_coverage(clickhouse),
        }

    for index, symbol in enumerate(symbols_to_fetch, start=1):
        percent = 5 + int(index / total * 90)
        _report(progress, min(percent, 95), "fetching", f"更新 {symbol} ClickHouse 5m 分钟线 {index}/{total}")
        try:
            bars = data_source.fetch_intraday_bars(symbol, trade_date, "5m")
            rows = _bar_rows(symbol, bars)
            if not rows:
                no_data += 1
                no_data_symbols.append(symbol)
                continue
            inserted = _insert_missing_rows(clickhouse, symbol, trade_date, rows)
            if inserted:
                inserted_rows += inserted
                success += 1
            else:
                no_data += 1
                no_data_symbols.append(symbol)
        except Exception as exc:  # noqa: BLE001 - keep batch sync resilient per symbol.
            failed += 1
            failures.append({"symbol": symbol, "error": str(exc)})

    result = {
        "trade_date": trade_date.isoformat(),
        "target_symbols": len(target_symbols),
        "skipped": skipped,
        "success": success,
        "no_data": no_data,
        "no_data_symbols": no_data_symbols[:100],
        "failed": failed,
        "inserted_rows": inserted_rows,
        "failures": failures[:50],
        "coverage_after": _minute5_coverage(clickhouse),
    }
    _report(progress, 100, "completed", "ClickHouse 5m 分钟线更新完成")
    return result


def _client(*, host: str, user: str, password: str, database: str) -> Any:
    source = ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
    return source._client_instance()


def _target_symbols(
    client: Any,
    *,
    symbols: list[str] | None,
    include_st: bool,
    limit: int,
) -> list[str]:
    if symbols:
        requested = [format_symbol(symbol) for symbol in symbols]
        names = _stock_names(client, [symbol.split(".")[0] for symbol in requested])
        filtered = [
            symbol
            for symbol in requested
            if include_st or not is_st(names.get(symbol.split(".")[0], ""))
        ]
    else:
        rows = client.execute("select symbol, name from stocks order by symbol")
        filtered = [
            format_symbol(str(code))
            for code, name in rows
            if include_st or not is_st(str(name or ""))
        ]
    if limit and limit > 0:
        return filtered[:limit]
    return filtered


def _stock_names(client: Any, codes: Iterable[str]) -> dict[str, str]:
    code_list = tuple(str(code).zfill(6) for code in codes)
    if not code_list:
        return {}
    rows = client.execute(
        """
        select symbol, name
        from stocks
        where symbol in %(symbols)s
        """,
        {"symbols": code_list},
    )
    return {str(code).zfill(6): str(name or "") for code, name in rows}


def _complete_codes(client: Any, trade_date: date) -> set[str]:
    rows = client.execute(
        """
        select distinct symbol
        from minute5_kline
        where datetime >= %(start)s and datetime <= %(end)s
        """,
        {
            "start": datetime.combine(trade_date, time(15, 0)),
            "end": datetime.combine(trade_date, time(15, 0, 59)),
        },
    )
    return {str(row[0]).zfill(6) for row in rows}


def _insert_missing_rows(client: Any, symbol: str, trade_date: date, rows: list[tuple[Any, ...]]) -> int:
    existing = _existing_datetimes(client, symbol, trade_date)
    missing = [row for row in rows if row[1] not in existing]
    if not missing:
        return 0
    client.execute(
        """
        insert into minute5_kline
            (symbol, datetime, open, high, low, close, volume, amount)
        values
        """,
        missing,
    )
    return len(missing)


def _existing_datetimes(client: Any, symbol: str, trade_date: date) -> set[datetime]:
    rows = client.execute(
        """
        select datetime
        from minute5_kline
        where symbol = %(symbol)s and datetime >= %(start)s and datetime <= %(end)s
        """,
        {
            "symbol": symbol.split(".")[0].zfill(6),
            "start": datetime.combine(trade_date, time(0, 0)),
            "end": datetime.combine(trade_date, time(23, 59, 59)),
        },
    )
    return {pd.Timestamp(row[0]).to_pydatetime() for row in rows}


def _bar_rows(symbol: str, bars: pd.DataFrame | None) -> list[tuple[Any, ...]]:
    if bars is None or bars.empty:
        return []
    code = symbol.split(".")[0].zfill(6)
    prepared = bars.copy()
    prepared["datetime"] = pd.to_datetime(prepared["datetime"], errors="coerce")
    prepared = prepared.dropna(subset=["datetime"])
    rows = []
    for _, row in prepared.iterrows():
        rows.append(
            (
                code,
                row["datetime"].to_pydatetime(),
                float(row.get("open", 0) or 0),
                float(row.get("high", 0) or 0),
                float(row.get("low", 0) or 0),
                float(row.get("close", 0) or 0),
                float(row.get("volume", 0) or 0),
                float(row.get("amount", 0) or 0),
            )
        )
    return rows


def _minute5_coverage(client: Any) -> dict[str, Any]:
    rows = client.execute(
        """
        select count(), min(datetime), max(datetime), uniqExact(symbol)
        from minute5_kline
        """
    )
    row_count, start, end, symbol_count = rows[0] if rows else (0, None, None, 0)
    return {
        "row_count": int(row_count or 0),
        "symbol_count": int(symbol_count or 0),
        "date_range": {"start": _stringify_dt(start), "end": _stringify_dt(end)},
    }


def _stringify_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _report(progress: ProgressCallback | None, percent: int, stage: str, message: str) -> None:
    if progress is not None:
        progress(percent, stage, message)
