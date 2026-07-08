"""Incremental synchronization for ClickHouse 5-minute A-share bars."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.akshare_source import AKShareSource
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.minute5_sync import FallbackIntradaySource
from src.data.sina_source import SinaSource
from src.data.tencent_source import TencentQuoteSource


ProgressCallback = Callable[[int, str, str], None]


def sync_clickhouse_minute5_kline(
    *,
    trade_date: date,
    limit: int = 0,
    symbols: list[str] | None = None,
    source: Any | None = None,
    include_st: bool = False,
    progress: ProgressCallback | None = None,
    target_time: time | None = None,
    max_fetch_symbols: int = 0,
    insert_batch_size: int = 50000,
    fetch_batch_size: int = 1000,
    commit_per_batch: bool = True,
    db_path: str | Path | None = None,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, Any]:
    """Fetch 5-minute bars and append missing rows into ClickHouse."""
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    data_source = source or _default_intraday_source(trade_date)
    _report(progress, 5, "preparing", "准备 ClickHouse 5m 分钟线更新")

    target_symbols = _target_symbols(
        clickhouse,
        symbols=symbols,
        include_st=include_st,
        limit=limit,
    )

    # Determine initial target datetime
    target_dt = _target_datetime(trade_date, target_time=target_time)
    target_expected_bars = _expected_5m_bars(target_dt.time())
    stats_by_code = _bar_stats(clickhouse, trade_date, [symbol.split(".")[0] for symbol in target_symbols])

    # Identify symbols that need refresh
    symbols_to_fetch: list[str] = []
    incremental_watermarks: dict[str, datetime] = {}
    gap_codes: set[str] = set()
    for symbol in target_symbols:
        code = symbol.split(".")[0].zfill(6)
        stats = stats_by_code.get(code)
        if not _needs_refresh(stats, target_dt, target_expected_bars):
            continue
        symbols_to_fetch.append(symbol)
        latest = stats.get("latest") if stats else None
        if latest is None:
            continue
        if latest < target_dt:
            incremental_watermarks[code] = latest
        else:
            gap_codes.add(code)

    remaining_before_batch = len(symbols_to_fetch)
    if max_fetch_symbols and max_fetch_symbols > 0:
        symbols_to_fetch = symbols_to_fetch[:max_fetch_symbols]

    total = len(symbols_to_fetch)
    skipped = len(target_symbols) - remaining_before_batch
    remaining_after_batch = max(0, remaining_before_batch - total)
    success = 0
    no_data = 0
    failed = 0
    no_data_symbols: list[str] = []
    failures: list[dict[str, str]] = []
    total_inserted_rows = 0

    # Track batches for progress reporting
    batches_completed = 0
    total_batches = (total + fetch_batch_size - 1) // fetch_batch_size if total > 0 else 0

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
            "coverage_after": _minute5_coverage(clickhouse),
        }

    # Process in batches for streaming commits
    for batch_start in range(0, total, fetch_batch_size):
        batch_end = min(batch_start + fetch_batch_size, total)
        batch_symbols = symbols_to_fetch[batch_start:batch_end]

        # Recalculate target_dt at the start of each batch (if not fixed by target_time)
        if target_time is None and commit_per_batch and batch_start > 0:
            target_dt = _target_datetime(trade_date, target_time=None)
            target_expected_bars = _expected_5m_bars(target_dt.time())

        _report(
            progress,
            5 + int((batch_start / total) * 90),
            "fetching",
            f"批次 {batches_completed + 1}/{total_batches} ({len(batch_symbols)} 只股票) 目标桶: {target_dt.strftime('%H:%M')}",
        )

        # Fetch batch
        batch_bars = _fetch_intraday_bars_batch(data_source, batch_symbols, trade_date)

        # Process batch
        rows_to_insert: list[tuple[Any, ...]] = []
        selected_codes = {symbol.split(".")[0].zfill(6) for symbol in batch_symbols}
        existing_by_code = _existing_datetimes_by_symbol(
            clickhouse,
            trade_date,
            sorted(gap_codes & selected_codes),
        )

        for symbol in batch_symbols:
            try:
                bars = batch_bars.get(symbol)
                if bars is None:
                    bars = data_source.fetch_intraday_bars(symbol, trade_date, "5m")
                rows = _bar_rows(symbol, bars)
                if not rows:
                    no_data += 1
                    no_data_symbols.append(symbol)
                    continue
                code = symbol.split(".")[0].zfill(6)
                if code in existing_by_code:
                    missing = _missing_rows(rows, existing_by_code[code], target_dt=target_dt)
                elif code in incremental_watermarks:
                    missing = _rows_after_datetime(rows, incremental_watermarks[code], target_dt=target_dt)
                else:
                    missing = _missing_rows(rows, set(), target_dt=target_dt)
                if missing:
                    rows_to_insert.extend(missing)
                    success += 1
                else:
                    no_data += 1
                    no_data_symbols.append(symbol)
            except Exception as exc:  # noqa: BLE001 - keep batch sync resilient per symbol.
                failed += 1
                failures.append({"symbol": symbol, "error": str(exc)})

        # Deduplicate and insert batch
        rows_to_insert = _deduplicate_rows(rows_to_insert)
        if rows_to_insert:
            _insert_rows_batched(clickhouse, rows_to_insert, batch_size=insert_batch_size)
            total_inserted_rows += len(rows_to_insert)

        batches_completed += 1

        # Report progress with processed/total for heartbeat
        if progress is not None:
            progress(
                5 + int((batch_end / total) * 90),
                "fetching",
                f"批次 {batches_completed}/{total_batches} 已提交，目标桶: {target_dt.strftime('%H:%M')}",
                processed=batch_end,
                total=total,
            )

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
        "inserted_rows": total_inserted_rows,
        "failures": failures[:50],
        "coverage_after": _minute5_coverage(clickhouse),
    }
    _report(progress, 100, "completed", "ClickHouse 5m 分钟线更新完成")
    return result


def sync_clickhouse_minute5_history_window(
    *,
    start: date,
    end: date,
    limit: int = 0,
    symbols: list[str] | None = None,
    source: Any | None = None,
    include_st: bool = False,
    batch_size: int = 500,
    progress: ProgressCallback | None = None,
    client: Any | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> dict[str, Any]:
    """Backfill 5-minute bars by fetching each symbol's recent history window once."""
    if end < start:
        raise ValueError("end must be greater than or equal to start")
    clickhouse = client or _client(host=host, user=user, password=password, database=database)
    data_source = source or SinaSource(rate_limit=0.0, intraday_datalen=10000, intraday_workers=30)
    window_fetcher = getattr(data_source, "fetch_intraday_bars_window", None)
    if window_fetcher is None:
        raise ValueError("source must provide fetch_intraday_bars_window")

    _report(progress, 5, "preparing", f"准备 ClickHouse 5m 历史窗口回填 {start.isoformat()} -> {end.isoformat()}")
    target_symbols = _target_symbols(
        clickhouse,
        symbols=symbols,
        include_st=include_st,
        limit=limit,
    )
    total = len(target_symbols)
    inserted_rows = 0
    no_data = 0
    failed = 0
    failures: list[dict[str, str]] = []

    for offset in range(0, total, max(1, batch_size)):
        batch_symbols = target_symbols[offset:offset + max(1, batch_size)]
        batch_index = offset + len(batch_symbols)
        percent = 5 + int(batch_index / max(1, total) * 90)
        _report(
            progress,
            min(percent, 95),
            "fetching",
            f"回填 ClickHouse 5m 历史窗口 {batch_index}/{total}",
        )
        try:
            bars = window_fetcher(batch_symbols, start, end, "5m")
            if bars is None or bars.empty:
                no_data += len(batch_symbols)
                continue
            rows = _window_bar_rows(bars, start, end)
            if not rows:
                no_data += len(batch_symbols)
                continue
            existing = _existing_datetimes_by_symbol_window(
                clickhouse,
                start,
                end,
                [symbol.split(".")[0] for symbol in batch_symbols],
            )
            inserted_rows += _insert_missing_window_rows(clickhouse, rows, existing)
        except Exception as exc:  # noqa: BLE001 - keep historical backfill resilient per batch.
            failed += len(batch_symbols)
            failures.append({"symbols": ",".join(batch_symbols[:5]), "error": str(exc)})

    result = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "target_symbols": total,
        "inserted_rows": inserted_rows,
        "no_data": no_data,
        "failed": failed,
        "failures": failures[:50],
        "coverage_after": _minute5_coverage(clickhouse),
    }
    _report(progress, 100, "completed", "ClickHouse 5m 历史窗口回填完成")
    return result


def _client(*, host: str | None, user: str | None, password: str | None, database: str | None) -> Any:
    source = ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
    return source._client_instance()


def _default_intraday_source(trade_date: date) -> FallbackIntradaySource:
    if trade_date < date.today() - timedelta(days=7):
        return FallbackIntradaySource([
            SinaSource(rate_limit=0.2, intraday_datalen=10000),
            TencentQuoteSource(rate_limit=0.0),
            AKShareSource(rate_limit=0.2),
        ])
    return FallbackIntradaySource([
        TencentQuoteSource(rate_limit=0.0),
        SinaSource(rate_limit=0.2, intraday_datalen=10000),
    ])


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
        rows = client.execute("select symbol, name, market from stocks final order by symbol")
        filtered = [
            format_symbol(str(code))
            for code, name, market in rows
            if (include_st or not is_st(str(name or "")))
            and str(market or "").upper() in ("SH", "SZ")
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
        return datetime.combine(trade_date, _completed_5m_bar_time(datetime.now().time()))
    return datetime.combine(trade_date, time(15, 0))


def _completed_5m_bar_time(value: time) -> time:
    minute = value.minute - (value.minute % 5)
    return time(value.hour, minute, 0)


def _needs_refresh(stats: dict[str, Any] | None, target_dt: datetime, expected_bars: int) -> bool:
    if stats is None:
        return True
    latest = stats.get("latest")
    count = int(stats.get("count") or 0)
    return latest is None or latest < target_dt or count < expected_bars


def _bar_stats(client: Any, trade_date: date, codes: list[str]) -> dict[str, dict[str, Any]]:
    code_list = tuple(str(code).zfill(6) for code in codes)
    if not code_list:
        return {}
    rows = client.execute(
        """
        select symbol, max(datetime) as latest_datetime, count() as bars
        from minute5_kline
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
        str(symbol).zfill(6): {
            "latest": pd.Timestamp(latest).to_pydatetime(),
            "count": int(count or 0),
        }
        for symbol, latest, count in rows
        if latest is not None
    }


def _existing_datetimes_by_symbol(client: Any, trade_date: date, codes: list[str]) -> dict[str, set[datetime]]:
    code_list = tuple(str(code).zfill(6) for code in codes)
    if not code_list:
        return {}
    rows = client.execute(
        """
        select symbol, groupArray(datetime) as datetimes
        from minute5_kline
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
        str(symbol).zfill(6): {pd.Timestamp(value).to_pydatetime() for value in values}
        for symbol, values in rows
    }


def _existing_datetimes_by_symbol_window(
    client: Any,
    start: date,
    end: date,
    codes: list[str],
) -> dict[str, set[datetime]]:
    code_list = tuple(str(code).zfill(6) for code in codes)
    if not code_list:
        return {}
    rows = client.execute(
        """
        select symbol, groupArray(datetime) as datetimes
        from minute5_kline
        where symbol in %(symbols)s and datetime >= %(start)s and datetime <= %(end)s
        group by symbol
        """,
        {
            "symbols": code_list,
            "start": datetime.combine(start, time(0, 0)),
            "end": datetime.combine(end, time(23, 59, 59)),
        },
    )
    return {
        str(symbol).zfill(6): {pd.Timestamp(value).to_pydatetime() for value in values}
        for symbol, values in rows
    }


def _missing_rows(
    rows: list[tuple[Any, ...]],
    existing: set[datetime],
    *,
    target_dt: datetime,
) -> list[tuple[Any, ...]]:
    return [row for row in rows if row[1] <= target_dt and row[1] not in existing]


def _rows_after_datetime(
    rows: list[tuple[Any, ...]],
    latest: datetime,
    *,
    target_dt: datetime,
) -> list[tuple[Any, ...]]:
    return [row for row in rows if latest < row[1] <= target_dt]


def _insert_rows_batched(client: Any, rows: list[tuple[Any, ...]], *, batch_size: int) -> None:
    size = max(1, int(batch_size or 50000))
    for offset in range(0, len(rows), size):
        client.execute(
            """
            insert into minute5_kline
                (symbol, datetime, open, high, low, close, volume, amount)
            values
            """,
            rows[offset:offset + size],
        )


def _deduplicate_rows(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    by_key: dict[tuple[str, datetime], tuple[Any, ...]] = {}
    for row in rows:
        by_key[(str(row[0]).zfill(6), row[1])] = row
    return [by_key[key] for key in sorted(by_key)]


def _insert_missing_window_rows(
    client: Any,
    rows: list[tuple[Any, ...]],
    existing: dict[str, set[datetime]],
) -> int:
    missing = [
        row for row in rows
        if row[1] not in existing.get(str(row[0]).zfill(6), set())
    ]
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


def _expected_5m_bars(target: time) -> int:
    slots = []
    current = datetime.combine(date(2000, 1, 1), time(9, 35))
    end_morning = datetime.combine(date(2000, 1, 1), time(11, 30))
    while current <= end_morning:
        slots.append(current.time())
        current += pd.Timedelta(minutes=5).to_pytimedelta()
    current = datetime.combine(date(2000, 1, 1), time(13, 5))
    end_afternoon = datetime.combine(date(2000, 1, 1), time(15, 0))
    while current <= end_afternoon:
        slots.append(current.time())
        current += pd.Timedelta(minutes=5).to_pytimedelta()
    return sum(1 for slot in slots if slot <= target)


def _fetch_intraday_bars_batch(source: Any, symbols: list[str], trade_date: date) -> dict[str, pd.DataFrame]:
    batch_fetcher = getattr(source, "fetch_intraday_bars_batch", None)
    if batch_fetcher is None or not symbols:
        return {}
    try:
        bars = batch_fetcher(symbols, trade_date, "5m")
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


def _window_bar_rows(bars: pd.DataFrame, start: date, end: date) -> list[tuple[Any, ...]]:
    if bars is None or bars.empty or "symbol" not in bars.columns:
        return []
    prepared = bars.copy()
    prepared["symbol"] = prepared["symbol"].map(format_symbol)
    prepared["datetime"] = pd.to_datetime(prepared["datetime"], errors="coerce")
    prepared = prepared.dropna(subset=["datetime"])
    prepared = prepared[
        (prepared["datetime"].dt.date >= start)
        & (prepared["datetime"].dt.date <= end)
    ]
    rows = []
    for _, row in prepared.sort_values(["symbol", "datetime"]).iterrows():
        code = str(row["symbol"]).split(".")[0].zfill(6)
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
