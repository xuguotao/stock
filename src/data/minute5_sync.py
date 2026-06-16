"""Incremental synchronization for local 5-minute A-share bars."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.akshare_source import AKShareSource
from src.data.sina_source import SinaSource


ProgressCallback = Callable[[int, str, str], None]


def sync_minute5_kline(
    *,
    db_path: str | Path = "data/stock.db",
    trade_date: date,
    limit: int = 0,
    symbols: list[str] | None = None,
    source: Any | None = None,
    include_st: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fetch 5-minute bars and upsert them into ``minute5_kline``."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Stock database not found: {path}")

    data_source = source or FallbackIntradaySource([
        SinaSource(rate_limit=0.2),
        AKShareSource(rate_limit=0.2),
    ])
    _report(progress, 5, "preparing", "准备 5m 分钟线更新")

    with sqlite3.connect(path) as conn:
        _ensure_minute5_table(conn)
        target_symbols = _target_symbols(conn, symbols=symbols, include_st=include_st, limit=limit)
        complete_codes = _complete_codes(conn, trade_date)

    symbols_to_fetch = [symbol for symbol in target_symbols if symbol.split(".")[0] not in complete_codes]
    total = len(symbols_to_fetch)
    skipped = len(target_symbols) - total
    success = 0
    no_data = 0
    failed = 0
    inserted_rows = 0
    failures: list[dict[str, str]] = []

    if total == 0:
        return {
            "trade_date": trade_date.isoformat(),
            "target_symbols": len(target_symbols),
            "skipped": skipped,
            "success": 0,
            "no_data": 0,
            "failed": 0,
            "inserted_rows": 0,
            "failures": [],
            "coverage_after": _minute5_coverage(path),
        }

    for index, symbol in enumerate(symbols_to_fetch, start=1):
        percent = 5 + int(index / total * 90)
        _report(progress, min(percent, 95), "fetching", f"更新 {symbol} 5m 分钟线 {index}/{total}")
        try:
            bars = data_source.fetch_intraday_bars(symbol, trade_date, "5m")
            rows = _bar_rows(symbol, bars)
            if not rows:
                no_data += 1
                continue
            with sqlite3.connect(path) as conn:
                _ensure_minute5_table(conn)
                conn.executemany(
                    """
                    insert or replace into minute5_kline
                        (symbol, datetime, open, high, low, close, volume, amount)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            inserted_rows += len(rows)
            success += 1
        except Exception as exc:  # noqa: BLE001 - keep batch sync resilient per symbol.
            failed += 1
            failures.append({"symbol": symbol, "error": str(exc)})

    result = {
        "trade_date": trade_date.isoformat(),
        "target_symbols": len(target_symbols),
        "skipped": skipped,
        "success": success,
        "no_data": no_data,
        "failed": failed,
        "inserted_rows": inserted_rows,
        "failures": failures[:50],
        "coverage_after": _minute5_coverage(path),
    }
    _report(progress, 100, "completed", "5m 分钟线更新完成")
    return result


class FallbackIntradaySource:
    """Try multiple intraday sources and return the first non-empty result."""

    def __init__(self, sources: list[Any]) -> None:
        self.sources = sources

    def fetch_intraday_bars(self, symbol: str, trade_date: date, frequency: str = "5m") -> pd.DataFrame:
        for source in self.sources:
            bars = source.fetch_intraday_bars(symbol, trade_date, frequency)
            if bars is not None and not bars.empty:
                return bars
        return pd.DataFrame()


def _ensure_minute5_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists minute5_kline (
            symbol text,
            datetime text,
            open real,
            high real,
            low real,
            close real,
            volume real,
            amount real,
            primary key (symbol, datetime)
        )
        """
    )
    conn.execute("create index if not exists idx_min5_symbol on minute5_kline(symbol)")
    conn.execute("create index if not exists idx_min5_dt on minute5_kline(datetime)")


def _target_symbols(
    conn: sqlite3.Connection,
    *,
    symbols: list[str] | None,
    include_st: bool,
    limit: int,
) -> list[str]:
    if symbols:
        requested = [format_symbol(symbol) for symbol in symbols]
        known = _stock_names(conn, [symbol.split(".")[0] for symbol in requested])
        filtered = [
            symbol
            for symbol in requested
            if include_st or not is_st(known.get(symbol.split(".")[0], ""))
        ]
    else:
        rows = conn.execute("select symbol, name from stocks order by symbol").fetchall()
        filtered = [
            format_symbol(str(code))
            for code, name in rows
            if include_st or not is_st(str(name or ""))
        ]
    if limit and limit > 0:
        return filtered[:limit]
    return filtered


def _stock_names(conn: sqlite3.Connection, codes: Iterable[str]) -> dict[str, str]:
    code_list = [str(code).zfill(6) for code in codes]
    if not code_list:
        return {}
    placeholders = ",".join("?" for _ in code_list)
    return {
        str(code).zfill(6): str(name or "")
        for code, name in conn.execute(
            f"select symbol, name from stocks where symbol in ({placeholders})",
            code_list,
        ).fetchall()
    }


def _complete_codes(conn: sqlite3.Connection, trade_date: date) -> set[str]:
    rows = conn.execute(
        """
        select distinct symbol
        from minute5_kline
        where datetime >= ? and datetime <= ?
        """,
        (f"{trade_date.isoformat()} 15:00:00", f"{trade_date.isoformat()} 15:00:59"),
    ).fetchall()
    return {str(row[0]).zfill(6) for row in rows}


def _bar_rows(symbol: str, bars: pd.DataFrame | None) -> list[tuple[Any, ...]]:
    if bars is None or bars.empty:
        return []
    code = symbol.split(".")[0].zfill(6)
    rows = []
    prepared = bars.copy()
    prepared["datetime"] = pd.to_datetime(prepared["datetime"], errors="coerce")
    prepared = prepared.dropna(subset=["datetime"])
    for _, row in prepared.iterrows():
        rows.append(
            (
                code,
                row["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                float(row.get("open", 0) or 0),
                float(row.get("high", 0) or 0),
                float(row.get("low", 0) or 0),
                float(row.get("close", 0) or 0),
                float(row.get("volume", 0) or 0),
                float(row.get("amount", 0) or 0),
            )
        )
    return rows


def _minute5_coverage(path: Path) -> dict[str, Any]:
    with sqlite3.connect(path) as conn:
        row_count = conn.execute("select count(*) from minute5_kline").fetchone()[0]
        symbol_count = conn.execute("select count(distinct symbol) from minute5_kline").fetchone()[0]
        start, end = conn.execute("select min(datetime), max(datetime) from minute5_kline").fetchone()
    return {
        "row_count": row_count,
        "symbol_count": symbol_count,
        "date_range": {"start": start, "end": end},
    }


def _report(progress: ProgressCallback | None, percent: int, stage: str, message: str) -> None:
    if progress is not None:
        progress(percent, stage, message)
