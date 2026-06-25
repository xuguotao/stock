"""Incremental synchronization for ClickHouse 1-minute A-share bars."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.tencent_source import TencentQuoteSource


ProgressCallback = Callable[[int, str, str], None]


def sync_clickhouse_minute1_kline(
    *,
    trade_date: date,
    limit: int = 0,
    symbols: list[str] | None = None,
    source: Any | None = None,
    include_st: bool = False,
    progress: ProgressCallback | None = None,
    target_time: time | None = None,
    max_fetch_symbols: int = 0,
    db_path: str | Path | None = None,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, Any]:
    """Fetch 1-minute bars and append missing rows into ClickHouse."""
    del db_path
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    data_source = source or TencentQuoteSource(rate_limit=0.0)
    _ensure_minute1_table(clickhouse)
    _report(progress, 5, "preparing", "准备 ClickHouse 1m 分钟线更新")

    target_symbols = _target_symbols(clickhouse, symbols=symbols, include_st=include_st, limit=limit)
    target_dt = _target_datetime(trade_date, target_time=target_time)
    latest_by_code = _latest_datetimes(clickhouse, trade_date, [symbol.split(".")[0] for symbol in target_symbols])
    symbols_to_fetch = [
        symbol for symbol in target_symbols
        if _needs_refresh(latest_by_code.get(symbol.split(".")[0].zfill(6)), target_dt)
    ]

    remaining_before_batch = len(symbols_to_fetch)
    if max_fetch_symbols and max_fetch_symbols > 0:
        symbols_to_fetch = symbols_to_fetch[:max_fetch_symbols]
    total = len(symbols_to_fetch)
    skipped = len(target_symbols) - remaining_before_batch
    remaining_after_batch = max(0, remaining_before_batch - total)
    success = 0
    no_data = 0
    failed = 0
    inserted_rows = 0
    no_data_symbols: list[str] = []
    failures: list[dict[str, str]] = []

    if total == 0:
        return {
            "trade_date": trade_date.isoformat(),
            "target_datetime": _stringify_dt(target_dt),
            "target_symbols": len(target_symbols),
            "skipped": skipped,
            "partial": False,
            "remaining_symbols": 0,
            "success": 0,
            "no_data": 0,
            "no_data_symbols": [],
            "failed": 0,
            "inserted_rows": 0,
            "failures": [],
            "coverage_after": _minute1_coverage(clickhouse),
        }

    batch_bars = _fetch_intraday_bars_batch(data_source, symbols_to_fetch, trade_date)
    for index, symbol in enumerate(symbols_to_fetch, start=1):
        percent = 5 + int(index / total * 90)
        _report(progress, min(percent, 95), "fetching", f"更新 {symbol} ClickHouse 1m 分钟线 {index}/{total}")
        try:
            bars = batch_bars.get(symbol)
            if bars is None:
                bars = data_source.fetch_intraday_bars(symbol, trade_date, "1m")
            rows = _bar_rows(symbol, bars)
            if not rows:
                no_data += 1
                no_data_symbols.append(symbol)
                continue
            inserted = _insert_incremental_rows(
                clickhouse,
                symbol,
                rows,
                latest_by_code.get(symbol.split(".")[0].zfill(6)),
            )
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
        "target_datetime": _stringify_dt(target_dt),
        "target_symbols": len(target_symbols),
        "skipped": skipped,
        "partial": remaining_after_batch > 0,
        "remaining_symbols": remaining_after_batch,
        "success": success,
        "no_data": no_data,
        "no_data_symbols": no_data_symbols[:100],
        "failed": failed,
        "inserted_rows": inserted_rows,
        "failures": failures[:50],
        "coverage_after": _minute1_coverage(clickhouse),
    }
    _report(progress, 100, "completed", "ClickHouse 1m 分钟线更新完成")
    return result


def _client(*, host: str | None, user: str | None, password: str | None, database: str | None) -> Any:
    source = ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
    return source._client_instance()


def _ensure_minute1_table(client: Any) -> None:
    client.execute(
        """
        create table if not exists minute1_kline (
            symbol String,
            datetime DateTime,
            open Float64,
            high Float64,
            low Float64,
            close Float64,
            volume Float64,
            amount Float64,
            updated_at DateTime default now()
        )
        engine = ReplacingMergeTree(updated_at)
        partition by toYYYYMM(datetime)
        order by (symbol, datetime)
        """
    )


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


def _target_datetime(trade_date: date, *, target_time: time | None) -> datetime:
    if target_time is not None:
        return datetime.combine(trade_date, target_time)
    if trade_date == date.today():
        now = datetime.now().time()
        return datetime.combine(trade_date, time(now.hour, now.minute, 0))
    return datetime.combine(trade_date, time(15, 0))


def _needs_refresh(latest: datetime | None, target_dt: datetime) -> bool:
    return latest is None or latest < target_dt


def _latest_datetimes(client: Any, trade_date: date, codes: list[str]) -> dict[str, datetime]:
    code_list = tuple(str(code).zfill(6) for code in codes)
    if not code_list:
        return {}
    rows = client.execute(
        """
        select symbol, max(datetime) as latest_datetime
        from minute1_kline
        where symbol in %(symbols)s and datetime >= %(start)s and datetime <= %(end)s
        group by symbol
        """,
        {
            "symbols": code_list,
            "start": datetime.combine(trade_date, time(0, 0)),
            "end": datetime.combine(trade_date, time(23, 59, 59)),
        },
    )
    return {
        str(symbol).zfill(6): pd.Timestamp(latest).to_pydatetime()
        for symbol, latest in rows
        if latest is not None
    }


def _insert_incremental_rows(
    client: Any,
    symbol: str,
    rows: list[tuple[Any, ...]],
    latest: datetime | None,
) -> int:
    missing = [row for row in rows if latest is None or row[1] > latest]
    if not missing:
        return 0
    client.execute(
        """
        insert into minute1_kline
            (symbol, datetime, open, high, low, close, volume, amount)
        values
        """,
        missing,
    )
    return len(missing)


def _fetch_intraday_bars_batch(source: Any, symbols: list[str], trade_date: date) -> dict[str, pd.DataFrame]:
    batch_fetcher = getattr(source, "fetch_intraday_bars_batch", None)
    if batch_fetcher is None or not symbols:
        return {}
    try:
        bars = batch_fetcher(symbols, trade_date, "1m")
    except Exception:
        return {}
    if bars is None or bars.empty or "symbol" not in bars.columns:
        return {}
    result: dict[str, pd.DataFrame] = {}
    prepared = bars.copy()
    prepared["symbol"] = prepared["symbol"].map(format_symbol)
    for symbol, frame in prepared.groupby("symbol"):
        result[str(symbol)] = frame.reset_index(drop=True)
    return result


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


def _minute1_coverage(client: Any) -> dict[str, Any]:
    rows = client.execute(
        """
        select count(), min(datetime), max(datetime), uniqExact(symbol)
        from minute1_kline
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
