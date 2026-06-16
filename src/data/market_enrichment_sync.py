"""Persist market enrichment data into the local SQLite stock database."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.constants import format_symbol


def sync_market_enrichment(
    *,
    db_path: str | Path = "data/stock.db",
    symbols: list[str],
    quote_source: Any | None = None,
    signal_source: Any | None = None,
    cninfo_source: Any | None = None,
    checked_at: str | None = None,
    announcement_page_size: int = 5,
) -> dict[str, int]:
    """Sync quote snapshots, concepts, announcements, and source health."""
    normalized_symbols = [format_symbol(symbol) for symbol in symbols]
    timestamp = checked_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if quote_source is None:
        from src.data.tencent_source import TencentQuoteSource

        quote_source = TencentQuoteSource(rate_limit=0.0)
    if signal_source is None:
        from src.data.eastmoney_source import EastmoneyClient, EastmoneySignalSource

        signal_source = EastmoneySignalSource(
            client=EastmoneyClient(min_interval=1.0, jitter=(0.1, 0.5))
        )
    if cninfo_source is None:
        from src.data.cninfo_source import CninfoAnnouncementSource

        cninfo_source = CninfoAnnouncementSource()

    with sqlite3.connect(path) as conn:
        _ensure_tables(conn)
        quote_rows, quote_health = _sync_quotes(conn, normalized_symbols, quote_source, timestamp)
        concept_rows, concept_health = _sync_concepts(conn, normalized_symbols, signal_source, timestamp)
        fund_flow_health = _check_fund_flow(normalized_symbols, signal_source)
        announcement_rows, cninfo_health = _sync_announcements(
            conn,
            normalized_symbols,
            cninfo_source,
            timestamp,
            announcement_page_size,
        )
        for row in [quote_health, concept_health, fund_flow_health, cninfo_health]:
            _upsert_health(conn, row["source"], row["ok"], row["detail"], timestamp)
        conn.commit()

    return {
        "symbols": len(normalized_symbols),
        "quote_rows": quote_rows,
        "concept_rows": concept_rows,
        "announcement_rows": announcement_rows,
        "health_rows": 4,
    }


def resolve_symbols_from_database(
    db_path: str | Path,
    *,
    limit: int = 20,
    include_st: bool = False,
) -> list[str]:
    """Resolve symbols from stocks table for enrichment sync."""
    path = Path(db_path)
    if not path.exists():
        return []
    sql = "select symbol, name from stocks order by symbol"
    symbols = []
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        for code, name in conn.execute(sql):
            if not include_st and "ST" in str(name or "").upper():
                continue
            symbols.append(format_symbol(str(code)))
            if limit > 0 and len(symbols) >= limit:
                break
    return symbols


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists stock_quote_snapshots (
            snapshot_at text not null,
            symbol text not null,
            name text,
            price real,
            change_pct real,
            volume integer,
            amount real,
            turnover_pct real,
            pe_ttm real,
            pb real,
            mcap real,
            float_mcap real,
            limit_up real,
            limit_down real,
            source text not null,
            primary key (snapshot_at, symbol, source)
        );
        create table if not exists stock_concept_blocks (
            symbol text not null,
            block_code text not null,
            block_name text not null,
            change_pct real,
            lead_stock text,
            updated_at text not null,
            source text not null,
            primary key (symbol, block_code, source)
        );
        create table if not exists stock_announcements (
            symbol text not null,
            title text not null,
            type text,
            date text,
            url text not null,
            fetched_at text not null,
            source text not null,
            primary key (symbol, url)
        );
        create table if not exists data_source_health (
            source text primary key,
            ok integer not null,
            detail text,
            checked_at text not null
        );
        """
    )


def _sync_quotes(
    conn: sqlite3.Connection,
    symbols: list[str],
    quote_source: Any,
    checked_at: str,
) -> tuple[int, dict[str, Any]]:
    try:
        quotes = quote_source.fetch_realtime_quotes(symbols)
    except Exception as exc:
        return 0, {"source": "tencent", "ok": False, "detail": str(exc)}
    if quotes is None or quotes.empty:
        return 0, {"source": "tencent", "ok": False, "detail": "quotes=0"}

    rows = []
    for _, row in quotes.iterrows():
        rows.append((
            checked_at,
            str(row.get("symbol", "")),
            str(row.get("name", "")),
            _float(row.get("price")),
            _float(row.get("change_pct")),
            int(_float(row.get("volume"))),
            _float(row.get("amount")),
            _float(row.get("turnover_pct")),
            _float(row.get("pe_ttm")),
            _float(row.get("pb")),
            _float(row.get("mcap")),
            _float(row.get("float_mcap")),
            _float(row.get("limit_up")),
            _float(row.get("limit_down")),
            "tencent",
        ))
    conn.executemany(
        """
        insert or replace into stock_quote_snapshots (
            snapshot_at, symbol, name, price, change_pct, volume, amount,
            turnover_pct, pe_ttm, pb, mcap, float_mcap, limit_up, limit_down, source
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows), {"source": "tencent", "ok": True, "detail": f"quotes={len(rows)}"}


def _sync_concepts(
    conn: sqlite3.Connection,
    symbols: list[str],
    signal_source: Any,
    checked_at: str,
) -> tuple[int, dict[str, Any]]:
    total = 0
    ok_count = 0
    for symbol in symbols:
        try:
            blocks = signal_source.fetch_concept_blocks(symbol)
        except Exception:
            blocks = {"boards": [], "total": 0}
        boards = blocks.get("boards", []) or []
        conn.execute(
            "delete from stock_concept_blocks where symbol = ? and source = ?",
            (symbol, "eastmoney"),
        )
        rows = [
            (
                symbol,
                str(board.get("code", "")),
                str(board.get("name", "")),
                _float(board.get("change_pct")),
                str(board.get("lead_stock", "")),
                checked_at,
                "eastmoney",
            )
            for board in boards
            if board.get("code") and board.get("name")
        ]
        if rows:
            ok_count += 1
            total += len(rows)
            conn.executemany(
                """
                insert or replace into stock_concept_blocks (
                    symbol, block_code, block_name, change_pct, lead_stock, updated_at, source
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    return total, {
        "source": "eastmoney_concepts",
        "ok": ok_count > 0,
        "detail": f"blocks={total}",
    }


def _check_fund_flow(symbols: list[str], signal_source: Any) -> dict[str, Any]:
    if not symbols:
        return {"source": "eastmoney_fund_flow", "ok": False, "detail": "rows=0"}
    try:
        rows = signal_source.fetch_minute_fund_flow(symbols[0])
    except Exception as exc:
        return {"source": "eastmoney_fund_flow", "ok": False, "detail": str(exc)}
    return {
        "source": "eastmoney_fund_flow",
        "ok": len(rows) > 0,
        "detail": f"rows={len(rows)}",
    }


def _sync_announcements(
    conn: sqlite3.Connection,
    symbols: list[str],
    cninfo_source: Any,
    checked_at: str,
    page_size: int,
) -> tuple[int, dict[str, Any]]:
    total = 0
    ok_count = 0
    for symbol in symbols:
        try:
            announcements = cninfo_source.fetch_announcements(symbol, page_size=page_size)
        except Exception:
            announcements = []
        rows = [
            (
                symbol,
                str(item.get("title", "")),
                str(item.get("type", "")),
                str(item.get("date", "")),
                str(item.get("url", "")),
                checked_at,
                "cninfo",
            )
            for item in announcements
            if item.get("title") and item.get("url")
        ]
        if rows:
            ok_count += 1
            total += len(rows)
            conn.executemany(
                """
                insert or replace into stock_announcements (
                    symbol, title, type, date, url, fetched_at, source
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    return total, {
        "source": "cninfo",
        "ok": ok_count > 0,
        "detail": f"announcements={total}",
    }


def _upsert_health(
    conn: sqlite3.Connection,
    source: str,
    ok: bool,
    detail: str,
    checked_at: str,
) -> None:
    conn.execute(
        """
        insert into data_source_health (source, ok, detail, checked_at)
        values (?, ?, ?, ?)
        on conflict(source) do update set
            ok = excluded.ok,
            detail = excluded.detail,
            checked_at = excluded.checked_at
        """,
        (source, 1 if ok else 0, detail, checked_at),
    )


def _float(value: Any) -> float:
    if pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
