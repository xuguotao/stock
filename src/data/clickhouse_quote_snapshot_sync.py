"""Sync realtime quote snapshots into ClickHouse."""

from __future__ import annotations

from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Callable

import pandas as pd

from src.core.constants import format_symbol, is_st


ProgressCallback = Callable[[int, str, str], None]


def sync_clickhouse_quote_snapshots(
    *,
    symbols: list[str] | None = None,
    limit: int = 0,
    include_st: bool = False,
    chunk_size: int = 400,
    timeout_seconds: int | float | None = None,
    checked_at: str | None = None,
    quote_source: Any | None = None,
    client: Any | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fetch realtime quotes and persist one snapshot batch into ClickHouse."""
    started = perf_counter()
    prepare_started = started
    snapshot_at = _datetime_value(checked_at) if checked_at else datetime.now().replace(microsecond=0)
    clickhouse = client or _default_client()
    source = quote_source or _default_quote_source()
    _progress(progress, 5, "preparing", "准备行情快照表")
    _ensure_table(clickhouse)
    _ensure_rollup_tables(clickhouse)

    target_symbols = _normalize_symbols(symbols) if symbols else _resolve_symbols(clickhouse, limit=limit, include_st=include_st)
    prepare_seconds = perf_counter() - prepare_started
    if not target_symbols:
        total_seconds = perf_counter() - started
        _progress(progress, 100, "completed", "行情快照同步完成")
        return {
            "snapshot_at": _format_datetime(snapshot_at),
            "target_symbols": 0,
            "quote_rows": 0,
            "inserted_rows": 0,
            "failed_chunks": 0,
            "latest_quote_time": None,
            "duration_seconds": round(total_seconds, 3),
            "timeout_seconds": timeout_seconds,
            "timings": _timings(
                total_seconds=total_seconds,
                prepare_seconds=prepare_seconds,
                fetch_seconds=0,
                write_seconds=0,
                rollup_seconds=0,
            ),
        }

    rows: list[tuple] = []
    failed_chunks = 0
    latest_quote_time: str | None = None
    chunks = list(_chunks(target_symbols, max(1, chunk_size)))
    fetch_started = perf_counter()
    for index, chunk in enumerate(chunks, start=1):
        _progress(progress, 10 + int(index / len(chunks) * 70), "fetching", f"拉取行情快照 {index}/{len(chunks)}")
        try:
            quotes = source.fetch_realtime_quotes(chunk)
        except Exception:  # noqa: BLE001 - keep the batch running and report failures.
            failed_chunks += 1
            continue
        if quotes is None or quotes.empty:
            continue
        rows.extend(_quote_rows(snapshot_at, quotes))
        quote_time = _latest_quote_time(quotes)
        if quote_time and (latest_quote_time is None or quote_time > latest_quote_time):
            latest_quote_time = quote_time
    fetch_seconds = perf_counter() - fetch_started

    write_seconds = 0.0
    rollup_seconds = 0.0
    if rows:
        _progress(progress, 90, "writing", "写入 ClickHouse 行情快照")
        write_started = perf_counter()
        clickhouse.execute(
            """
            insert into stock_quote_snapshots (
                snapshot_at, symbol, name, price, change_pct, volume, amount,
                turnover_pct, pe_ttm, pb, mcap, float_mcap, limit_up, limit_down,
                source, quote_time
            ) values
            """,
            rows,
        )
        write_seconds = perf_counter() - write_started
        rollup_started = perf_counter()
        rollups = _refresh_rollups(clickhouse, snapshot_at)
        rollup_seconds = perf_counter() - rollup_started
    else:
        rollups = {}

    total_seconds = perf_counter() - started
    _progress(progress, 100, "completed", "行情快照同步完成")
    return {
        "snapshot_at": _format_datetime(snapshot_at),
        "target_symbols": len(target_symbols),
        "quote_rows": len(rows),
        "inserted_rows": len(rows),
        "failed_chunks": failed_chunks,
        "latest_quote_time": latest_quote_time,
        "rollups": rollups,
        "timeout_seconds": timeout_seconds,
        "duration_seconds": round(total_seconds, 3),
        "timings": _timings(
            total_seconds=total_seconds,
            prepare_seconds=prepare_seconds,
            fetch_seconds=fetch_seconds,
            write_seconds=write_seconds,
            rollup_seconds=rollup_seconds,
        ),
    }


def _ensure_table(client: Any) -> None:
    client.execute(
        """
        create table if not exists stock_quote_snapshots (
            snapshot_at DateTime,
            symbol String,
            name String,
            price Float64,
            change_pct Float64,
            volume UInt64,
            amount Float64,
            turnover_pct Float64,
            pe_ttm Float64,
            pb Float64,
            mcap Float64,
            float_mcap Float64,
            limit_up Float64,
            limit_down Float64,
            source LowCardinality(String),
            quote_time Nullable(DateTime)
        )
        engine = MergeTree
        partition by toDate(snapshot_at)
        order by (snapshot_at, symbol, source)
        """
    )
    client.execute(
        """
        alter table stock_quote_snapshots
        modify ttl snapshot_at + interval 120 day delete
        """
    )


def _ensure_rollup_tables(client: Any, *, retention_days: int = 1095) -> None:
    for table in ("stock_quote_snapshots_1m", "stock_quote_snapshots_5m"):
        client.execute(
            f"""
            create table if not exists {table} (
                bucket_start DateTime,
                symbol String,
                name String,
                open_price Float64,
                high_price Float64,
                low_price Float64,
                close_price Float64,
                change_pct Float64,
                volume UInt64,
                amount Float64,
                turnover_pct Float64,
                pe_ttm Float64,
                pb Float64,
                mcap Float64,
                float_mcap Float64,
                limit_up Float64,
                limit_down Float64,
                source LowCardinality(String),
                quote_time Nullable(DateTime),
                sample_count UInt32,
                updated_at DateTime
            )
            engine = ReplacingMergeTree(updated_at)
            partition by toDate(bucket_start)
            order by (bucket_start, symbol, source)
            ttl bucket_start + interval {int(retention_days)} day delete
            """
        )


def _refresh_rollups(client: Any, snapshot_at: datetime) -> dict[str, dict[str, str]]:
    result = {}
    for label, minutes in (("1m", 1), ("5m", 5)):
        bucket_start = _bucket_start(snapshot_at, minutes)
        previous_bucket_start = bucket_start - timedelta(minutes=minutes)
        table = f"stock_quote_snapshots_{label}"
        _refresh_rollup_bucket(client, table=table, bucket_start=previous_bucket_start, minutes=minutes)
        _refresh_rollup_bucket(client, table=table, bucket_start=bucket_start, minutes=minutes)
        result[label] = {"bucket_start": _format_datetime(bucket_start), "refreshed_buckets": 2}
    return result


def _refresh_rollup_bucket(client: Any, *, table: str, bucket_start: datetime, minutes: int) -> None:
    bucket_end = bucket_start + timedelta(minutes=minutes)
    client.execute(
        f"""
        insert into {table}
        select
            %(bucket_start)s as bucket_start,
            symbol,
            argMin(name, snapshot_at) as name,
            argMin(price, snapshot_at) as open_price,
            max(price) as high_price,
            min(price) as low_price,
            argMax(price, snapshot_at) as close_price,
            argMax(change_pct, snapshot_at) as change_pct,
            toUInt64(argMax(volume, snapshot_at)) as volume,
            argMax(amount, snapshot_at) as amount,
            argMax(turnover_pct, snapshot_at) as turnover_pct,
            argMax(pe_ttm, snapshot_at) as pe_ttm,
            argMax(pb, snapshot_at) as pb,
            argMax(mcap, snapshot_at) as mcap,
            argMax(float_mcap, snapshot_at) as float_mcap,
            argMax(limit_up, snapshot_at) as limit_up,
            argMax(limit_down, snapshot_at) as limit_down,
            argMax(source, snapshot_at) as source,
            argMax(quote_time, snapshot_at) as quote_time,
            toUInt32(count()) as sample_count,
            now() as updated_at
        from stock_quote_snapshots
        where snapshot_at >= %(bucket_start)s and snapshot_at < %(bucket_end)s
        group by symbol
        """,
        {"bucket_start": bucket_start, "bucket_end": bucket_end},
    )


def _bucket_start(value: datetime, minutes: int) -> datetime:
    minute = value.minute - (value.minute % minutes)
    return value.replace(minute=minute, second=0, microsecond=0)


def _resolve_symbols(client: Any, *, limit: int, include_st: bool) -> list[str]:
    rows = client.execute("select symbol, name from stocks order by symbol")
    result = []
    for symbol, name in rows:
        stock_name = str(name or "")
        if not include_st and is_st(stock_name):
            continue
        result.append(format_symbol(str(symbol)))
        if limit > 0 and len(result) >= limit:
            break
    return result


def _normalize_symbols(symbols: list[str]) -> list[str]:
    return [format_symbol(symbol) for symbol in symbols]


def _quote_rows(snapshot_at: datetime, quotes: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, row in quotes.iterrows():
        rows.append(
            (
                snapshot_at,
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
                _nullable_datetime(row.get("timestamp")),
            )
        )
    return rows


def _latest_quote_time(quotes: pd.DataFrame) -> str | None:
    if "timestamp" not in quotes.columns:
        return None
    values = [str(value) for value in quotes["timestamp"].dropna().tolist() if str(value)]
    return max(values) if values else None


def _nullable_datetime(value: Any) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return _datetime_value(value)


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(microsecond=0)
    text = str(value).strip()
    if not text:
        raise ValueError("empty datetime value")
    return pd.to_datetime(text).to_pydatetime().replace(microsecond=0)


def _format_datetime(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else None


def _float(value: Any) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _chunks(symbols: list[str], size: int):
    for start in range(0, len(symbols), size):
        yield symbols[start : start + size]


def _progress(progress: ProgressCallback | None, percent: int, stage: str, message: str) -> None:
    if progress is not None:
        progress(percent, stage, message)


def _timings(
    *,
    total_seconds: float,
    prepare_seconds: float,
    fetch_seconds: float,
    write_seconds: float,
    rollup_seconds: float,
) -> dict[str, float]:
    return {
        "total_seconds": round(total_seconds, 3),
        "prepare_seconds": round(prepare_seconds, 3),
        "fetch_seconds": round(fetch_seconds, 3),
        "write_seconds": round(write_seconds, 3),
        "rollup_seconds": round(rollup_seconds, 3),
    }


def _default_client() -> Any:
    from src.data.clickhouse_source import ClickHouseStockDataSource

    return ClickHouseStockDataSource()._client_instance()


def _default_quote_source() -> Any:
    from src.data.tencent_source import TencentQuoteSource

    return TencentQuoteSource(rate_limit=0.0)
