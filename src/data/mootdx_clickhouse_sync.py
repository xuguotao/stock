"""Persist mootdx data into isolated ClickHouse tables."""

from __future__ import annotations

import json
from datetime import date, datetime
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

import pandas as pd

from src.core.constants import is_st
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.mootdx_source import MootdxSource


ProgressCallback = Callable[[int, str, str], None]

DEFAULT_TASKS = [
    "stock_catalog",
    "quote_snapshot",
    "stock_kline_daily",
    "stock_kline_intraday",
    "index_kline",
    "xdxr",
    "finance_snapshot",
]
DEFAULT_INDEX_SYMBOLS = ["000001.SH", "399001.SZ", "399006.SZ"]


def ensure_mootdx_tables(client: Any) -> None:
    for sql in MOOTDX_TABLE_SQL:
        client.execute(sql)


def sync_mootdx_offline_data(
    *,
    client: Any | None = None,
    source: Any | None = None,
    symbols: list[str] | None = None,
    trade_date: date | None = None,
    frequencies: list[str] | None = None,
    tasks: list[str] | None = None,
    include_beijing: bool = False,
    limit: int = 0,
    ensure_tables: bool = True,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    run_started_at = datetime.now().replace(microsecond=0)
    run_id = uuid4().hex
    clickhouse = client or ClickHouseStockDataSource()._client_instance()
    data_source = source or MootdxSource(include_beijing=include_beijing)
    selected_tasks = tasks or list(DEFAULT_TASKS)
    selected_frequencies = frequencies or ["5m"]
    selected_trade_date = trade_date or date.today()
    inserted: dict[str, int] = {}
    failed: dict[str, str] = {}

    if ensure_tables:
        _progress(progress, 5, "ensure_tables", "准备 mootdx 独立表")
        ensure_mootdx_tables(clickhouse)

    target_symbols = _resolve_symbols(data_source, symbols=symbols, limit=limit)
    _progress(progress, 15, "resolved_symbols", f"解析 mootdx 股票池 {len(target_symbols)} 只")

    task_count = max(1, len(selected_tasks))
    for index, task in enumerate(selected_tasks, start=1):
        _progress(progress, 15 + int(index / task_count * 75), task, f"执行 mootdx 离线任务 {task}")
        try:
            rows_by_table = _run_task(
                task=task,
                source=data_source,
                symbols=target_symbols,
                trade_date=selected_trade_date,
                frequencies=selected_frequencies,
                client=clickhouse,
            )
            for table, rows in rows_by_table.items():
                if not rows:
                    inserted[table] = inserted.get(table, 0)
                    continue
                _insert_rows(clickhouse, table, rows)
                inserted[table] = inserted.get(table, 0) + len(rows)
                if table == "mootdx_stock_catalog":
                    clickhouse.execute("optimize table mootdx_stock_catalog final")
        except Exception as exc:  # noqa: BLE001 - offline sync records per-task failures.
            failed[task] = f"{type(exc).__name__}: {str(exc)[:240]}"

    result = {
        "run_id": run_id,
        "trade_date": selected_trade_date.isoformat(),
        "tasks": selected_tasks,
        "symbols": target_symbols,
        "inserted": inserted,
        "failed": failed,
        "duration_seconds": round(perf_counter() - started, 3),
    }
    _write_run_row(
        clickhouse,
        run_id=run_id,
        task_key="mootdx_offline_sync",
        started_at=run_started_at,
        status="failed" if failed else "success",
        params={
            "symbols": symbols,
            "trade_date": selected_trade_date.isoformat(),
            "frequencies": selected_frequencies,
            "tasks": selected_tasks,
            "limit": limit,
            "include_beijing": include_beijing,
        },
        result=result,
        error=json.dumps(failed, ensure_ascii=False) if failed else "",
    )
    _progress(progress, 100, "completed", "mootdx 离线同步完成")
    return result


def _run_task(
    *,
    task: str,
    source: Any,
    symbols: list[str],
    trade_date: date,
    frequencies: list[str],
    client: Any = None,
) -> dict[str, list[tuple]]:
    if task == "stock_catalog":
        return {"mootdx_stock_catalog": _stock_catalog_rows(source, symbols, client)}
    if task == "quote_snapshot":
        return {"mootdx_quote_snapshots": _quote_snapshot_rows(source, symbols)}
    if task == "stock_kline_daily":
        return {"mootdx_stock_kline": _daily_kline_rows(source, symbols, trade_date)}
    if task == "stock_kline_intraday":
        return {"mootdx_stock_kline": _intraday_kline_rows(source, symbols, trade_date, frequencies)}
    if task == "index_kline":
        return {"mootdx_index_kline": _index_kline_rows(source, frequencies)}
    if task == "xdxr":
        return {"mootdx_xdxr": _xdxr_rows(source, symbols)}
    if task == "finance_snapshot":
        return {"mootdx_finance_snapshot": _finance_rows(source, symbols)}
    if task == "minutes_probe":
        return {"mootdx_minutes": _minutes_rows(source, symbols, trade_date, "minutes")}
    if task == "realtime_minute_probe":
        return {"mootdx_minutes": _minutes_rows(source, symbols, trade_date, "realtime_minute")}
    if task == "transaction_probe":
        return {"mootdx_transactions": _transaction_rows(source, symbols, None, "transaction")}
    if task == "historical_transaction_probe":
        return {"mootdx_transactions": _transaction_rows(source, symbols, trade_date, "transactions")}
    if task == "f10_catalog_probe":
        return {"mootdx_f10_catalog": _f10_catalog_rows(source, symbols)}
    if task == "f10_detail_probe":
        return {"mootdx_f10_detail": _f10_detail_rows(source, symbols)}
    if task == "affair_file_list_probe":
        return {"mootdx_affair_files": _affair_file_rows(source)}
    raise ValueError(f"unknown mootdx offline task: {task}")


def _resolve_symbols(source: Any, *, symbols: list[str] | None, limit: int) -> list[str]:
    if symbols:
        result = list(dict.fromkeys(symbols))
    else:
        result = [stock.symbol for stock in source.fetch_stock_list() if not getattr(stock, "is_st", False)]
    if limit > 0:
        return result[:limit]
    return result


def _stock_catalog_rows(source: Any, symbols: list[str], client: Any) -> list[tuple]:
    captured_at = _now()
    selected = set(symbols)
    latest = _latest_catalog_by_symbol(client)
    rows = []
    for stock in source.fetch_stock_list():
        if selected and stock.symbol not in selected:
            continue
        market_code = _market_code(stock.symbol)
        is_st_flag = 1 if stock.is_st or is_st(stock.name) else 0
        current = (market_code, stock.code, stock.name, is_st_flag)
        if latest.get(stock.symbol) == current:
            continue
        rows.append((
            captured_at,
            market_code,
            stock.symbol,
            stock.code,
            stock.name,
            is_st_flag,
            "mootdx",
            _json({"symbol": stock.symbol, "code": stock.code, "name": stock.name}),
        ))
    return rows


def _latest_catalog_by_symbol(client: Any) -> dict[str, tuple]:
    if client is None:
        return {}
    try:
        rows = client.execute(
            "select symbol, argMax(market, captured_at), argMax(code, captured_at), "
            "argMax(name, captured_at), argMax(is_st, captured_at) "
            "from mootdx_stock_catalog group by symbol"
        )
    except Exception:  # noqa: BLE001 - missing table or unreadable catalog => treat as empty.
        return {}
    return {row[0]: (int(row[1]), row[2], row[3], int(row[4])) for row in rows}


def _quote_snapshot_rows(source: Any, symbols: list[str]) -> list[tuple]:
    snapshot_at = _now()
    if not symbols:
        return []
    frame = source.fetch_realtime_quotes(symbols)
    rows = []
    for _, row in _safe_frame(frame).iterrows():
        rows.append((
            snapshot_at,
            str(row.get("symbol") or ""),
            _float(row.get("price")),
            _float(row.get("open")),
            _float(row.get("prev_close")),
            _float(row.get("high")),
            _float(row.get("low")),
            int(_float(row.get("volume"))),
            _float(row.get("amount")),
            _float(row.get("change_pct")),
            _nullable_datetime(row.get("timestamp")),
            "mootdx",
            _json(row.to_dict()),
        ))
    return rows


def _daily_kline_rows(source: Any, symbols: list[str], trade_date: date) -> list[tuple]:
    rows = []
    for symbol in symbols:
        frame = source.fetch_bars(symbol, trade_date, trade_date, "daily")
        rows.extend(_stock_kline_rows_from_frame(frame, frequency="daily"))
    return rows


def _intraday_kline_rows(source: Any, symbols: list[str], trade_date: date, frequencies: list[str]) -> list[tuple]:
    rows = []
    intraday_frequencies = [frequency for frequency in frequencies if frequency not in {"daily", "day"}]
    for symbol in symbols:
        for frequency in intraday_frequencies:
            frame = source.fetch_intraday_bars(symbol, trade_date, frequency)
            rows.extend(_stock_kline_rows_from_frame(frame, frequency=frequency))
    return rows


def _stock_kline_rows_from_frame(frame: pd.DataFrame, *, frequency: str) -> list[tuple]:
    ingested_at = _now()
    rows = []
    for _, row in _safe_frame(frame).iterrows():
        dt = _row_datetime(row)
        if dt is None:
            continue
        rows.append((
            dt,
            dt.date(),
            frequency,
            str(row.get("symbol") or ""),
            _float(row.get("open")),
            _float(row.get("high")),
            _float(row.get("low")),
            _float(row.get("close")),
            int(_float(row.get("volume"))),
            _float(row.get("amount")),
            "mootdx",
            ingested_at,
            _json(row.to_dict()),
        ))
    return rows


def _index_kline_rows(source: Any, frequencies: list[str]) -> list[tuple]:
    ingested_at = _now()
    rows = []
    selected = [frequency for frequency in frequencies if frequency in {"daily", "day", "1m", "5m", "15m", "30m", "60m"}]
    selected = selected or ["daily"]
    for symbol in DEFAULT_INDEX_SYMBOLS:
        for frequency in selected:
            frame = source.fetch_index_bars(symbol, frequency)
            for _, row in _safe_frame(frame).iterrows():
                dt = _row_datetime(row)
                if dt is None:
                    continue
                rows.append((
                    dt,
                    dt.date(),
                    frequency,
                    symbol,
                    _float(row.get("open")),
                    _float(row.get("high")),
                    _float(row.get("low")),
                    _float(row.get("close")),
                    int(_float(row.get("volume", row.get("vol")))),
                    _float(row.get("amount")),
                    _nullable_uint(row.get("up_count")),
                    _nullable_uint(row.get("down_count")),
                    "mootdx",
                    ingested_at,
                    _json(row.to_dict()),
                ))
    return rows


def _xdxr_rows(source: Any, symbols: list[str]) -> list[tuple]:
    ingested_at = _now()
    rows = []
    for symbol in symbols:
        frame = source.fetch_xdxr(symbol)
        for _, row in _safe_frame(frame).iterrows():
            event_date = _ymd_date(row)
            if event_date is None:
                continue
            rows.append((
                symbol,
                event_date,
                int(_float(row.get("category"))),
                str(row.get("name") or ""),
                _float(row.get("fenhong")),
                _float(row.get("peigujia")),
                _float(row.get("songzhuangu")),
                _float(row.get("peigu")),
                _float(row.get("suogu")),
                _float(row.get("panqianliutong")),
                _float(row.get("panhouliutong")),
                _float(row.get("qianzongguben")),
                _float(row.get("houzongguben")),
                ingested_at,
                _json(row.to_dict()),
            ))
    return rows


def _finance_rows(source: Any, symbols: list[str]) -> list[tuple]:
    captured_at = _now()
    rows = []
    for symbol in symbols:
        frame = source.fetch_finance_frame(symbol)
        for _, row in _safe_frame(frame).iterrows():
            rows.append((
                captured_at,
                symbol,
                _nullable_date(row.get("updated_date")),
                _nullable_date(row.get("ipo_date")),
                str(row.get("industry") or ""),
                _float(row.get("liutongguben")),
                _float(row.get("zongguben")),
                _float(row.get("zongzichan")),
                _float(row.get("jingzichan")),
                _float(row.get("zhuyingshouru")),
                _float(row.get("jinglirun")),
                _float(row.get("meigujingzichan")),
                "mootdx",
                _json(row.to_dict()),
            ))
    return rows


def _minutes_rows(source: Any, symbols: list[str], trade_date: date, source_method: str) -> list[tuple]:
    captured_at = _now()
    rows = []
    for symbol in symbols:
        frame = source.fetch_minutes(symbol, trade_date) if source_method == "minutes" else source.fetch_realtime_minute(symbol)
        for index, row in _safe_frame(frame).reset_index(drop=True).iterrows():
            rows.append((
                captured_at,
                trade_date,
                symbol,
                source_method,
                int(index),
                _float(row.get("price")),
                int(_float(row.get("volume", row.get("vol")))),
                _json(row.to_dict()),
            ))
    return rows


def _transaction_rows(source: Any, symbols: list[str], trade_date: date | None, source_method: str) -> list[tuple]:
    captured_at = _now()
    rows = []
    for symbol in symbols:
        frame = source.fetch_transactions(symbol, trade_date=trade_date, offset=80)
        for index, row in _safe_frame(frame).reset_index(drop=True).iterrows():
            rows.append((
                captured_at,
                trade_date,
                symbol,
                source_method,
                int(index),
                _float(row.get("price")),
                int(_float(row.get("volume", row.get("vol")))),
                _float(row.get("amount")),
                _json(row.to_dict()),
            ))
    return rows


def _f10_catalog_rows(source: Any, symbols: list[str]) -> list[tuple]:
    captured_at = _now()
    rows = []
    for symbol in symbols:
        frame = source.fetch_f10_catalog(symbol)
        for _, row in _safe_frame(frame).iterrows():
            title = str(row.get("title") or row.get("name") or "")
            if title:
                rows.append((captured_at, symbol, title, _json(row.to_dict())))
    return rows


def _f10_detail_rows(source: Any, symbols: list[str]) -> list[tuple]:
    captured_at = _now()
    rows = []
    for symbol in symbols:
        catalog = _safe_frame(source.fetch_f10_catalog(symbol))
        for _, row in catalog.head(3).iterrows():
            title = str(row.get("title") or row.get("name") or "")
            if not title:
                continue
            rows.append((captured_at, symbol, title, source.fetch_f10_detail(symbol, title)))
    return rows


def _affair_file_rows(source: Any) -> list[tuple]:
    captured_at = _now()
    rows = []
    for item in source.fetch_affair_files():
        rows.append((
            captured_at,
            str(item.get("filename") or ""),
            str(item.get("hash") or ""),
            int(_float(item.get("filesize"))),
            _json(item),
        ))
    return rows


def _insert_rows(client: Any, table: str, rows: list[tuple]) -> None:
    if table in {"mootdx_stock_kline", "mootdx_index_kline"}:
        batches: dict[tuple[Any, Any], list[tuple]] = {}
        for row in rows:
            batches.setdefault((row[1], row[2]), []).append(row)
        for batch in batches.values():
            client.execute(f"insert into {table} values", batch)
        return
    client.execute(f"insert into {table} values", rows)


def _write_run_row(
    client: Any,
    *,
    run_id: str,
    task_key: str,
    started_at: datetime,
    status: str,
    params: dict[str, Any],
    result: dict[str, Any],
    error: str,
) -> None:
    client.execute(
        "insert into mootdx_sync_runs values",
        [(
            run_id,
            task_key,
            started_at,
            _now(),
            status,
            json.dumps(params, ensure_ascii=False, default=str),
            json.dumps(result, ensure_ascii=False, default=str),
            error,
            "mootdx",
        )],
    )


def _progress(progress: ProgressCallback | None, percent: int, stage: str, message: str) -> None:
    if progress is not None:
        progress(percent, stage, message)


def _market_code(symbol: str) -> int:
    suffix = symbol.split(".")[-1].upper() if "." in symbol else ""
    return {"SZ": 0, "SH": 1, "BJ": 2}.get(suffix, 255)


def _row_datetime(row: pd.Series) -> datetime | None:
    if "datetime" in row and pd.notna(row["datetime"]):
        value = pd.to_datetime(row["datetime"], errors="coerce")
        if pd.notna(value):
            return value.to_pydatetime()
    if "date" in row and pd.notna(row["date"]):
        value = pd.to_datetime(row["date"], errors="coerce")
        if pd.notna(value):
            return value.replace(hour=15, minute=0, second=0).to_pydatetime()
    return None


def _ymd_date(row: pd.Series) -> date | None:
    year = int(_float(row.get("year")))
    month = int(_float(row.get("month")))
    day = int(_float(row.get("day")))
    if year <= 0 or month <= 0 or day <= 0:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _nullable_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _nullable_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value)
    if text.isdigit() and len(text) == 8:
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _nullable_uint(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(_float(value))


def _safe_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    return pd.DataFrame()


def _float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


MOOTDX_TABLE_SQL = [
    """
    create table if not exists mootdx_sync_runs (
        run_id String,
        task_key LowCardinality(String),
        started_at DateTime,
        finished_at DateTime,
        status LowCardinality(String),
        params_json String,
        result_json String,
        error String,
        source_version String
    )
    engine = MergeTree
    partition by toDate(started_at)
    order by (task_key, started_at, run_id)
    ttl started_at + interval 365 day delete
    """,
    """
    create table if not exists mootdx_stock_catalog (
        captured_at DateTime,
        market UInt8,
        symbol String,
        code String,
        name String,
        is_st UInt8,
        source LowCardinality(String),
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by tuple()
    order by (symbol)
    ttl captured_at + interval 365 day delete
    """,
    """
    create table if not exists mootdx_quote_snapshots (
        snapshot_at DateTime,
        symbol String,
        price Float64,
        open Float64,
        prev_close Float64,
        high Float64,
        low Float64,
        volume UInt64,
        amount Float64,
        change_pct Float64,
        quote_time Nullable(DateTime),
        source LowCardinality(String),
        raw_json String
    )
    engine = MergeTree
    partition by toDate(snapshot_at)
    order by (snapshot_at, symbol)
    ttl snapshot_at + interval 180 day delete
    """,
    """
    create table if not exists mootdx_stock_kline (
        datetime DateTime,
        trade_date Date,
        frequency LowCardinality(String),
        symbol String,
        open Float64,
        high Float64,
        low Float64,
        close Float64,
        volume UInt64,
        amount Float64,
        source LowCardinality(String),
        ingested_at DateTime,
        raw_json String
    )
    engine = ReplacingMergeTree(ingested_at)
    partition by (trade_date, frequency)
    order by (frequency, symbol, datetime)
    ttl trade_date + interval 1095 day delete
    """,
    """
    create table if not exists mootdx_index_kline (
        datetime DateTime,
        trade_date Date,
        frequency LowCardinality(String),
        symbol String,
        open Float64,
        high Float64,
        low Float64,
        close Float64,
        volume UInt64,
        amount Float64,
        up_count Nullable(UInt32),
        down_count Nullable(UInt32),
        source LowCardinality(String),
        ingested_at DateTime,
        raw_json String
    )
    engine = ReplacingMergeTree(ingested_at)
    partition by (trade_date, frequency)
    order by (frequency, symbol, datetime)
    ttl trade_date + interval 1095 day delete
    """,
    """
    create table if not exists mootdx_xdxr (
        symbol String,
        event_date Date,
        category Int16,
        name String,
        fenhong Float64,
        peigujia Float64,
        songzhuangu Float64,
        peigu Float64,
        suogu Float64,
        panqianliutong Float64,
        panhouliutong Float64,
        qianzongguben Float64,
        houzongguben Float64,
        ingested_at DateTime,
        raw_json String
    )
    engine = ReplacingMergeTree(ingested_at)
    partition by toYYYYMM(event_date)
    order by (symbol, event_date, category)
    """,
    """
    create table if not exists mootdx_finance_snapshot (
        captured_at DateTime,
        symbol String,
        updated_date Nullable(Date),
        ipo_date Nullable(Date),
        industry String,
        liutongguben Float64,
        zongguben Float64,
        zongzichan Float64,
        jingzichan Float64,
        zhuyingshouru Float64,
        jinglirun Float64,
        meigujingzichan Float64,
        source LowCardinality(String),
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by toDate(captured_at)
    order by (symbol, captured_at)
    ttl captured_at + interval 1095 day delete
    """,
    """
    create table if not exists mootdx_minutes (
        captured_at DateTime,
        trade_date Date,
        symbol String,
        source_method LowCardinality(String),
        row_index UInt16,
        price Float64,
        volume UInt64,
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by trade_date
    order by (trade_date, symbol, source_method, row_index)
    ttl trade_date + interval 180 day delete
    """,
    """
    create table if not exists mootdx_transactions (
        captured_at DateTime,
        trade_date Nullable(Date),
        symbol String,
        source_method LowCardinality(String),
        row_index UInt32,
        price Float64,
        volume UInt64,
        amount Float64,
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by toDate(captured_at)
    order by (symbol, source_method, captured_at, row_index)
    ttl captured_at + interval 180 day delete
    """,
    """
    create table if not exists mootdx_f10_catalog (
        captured_at DateTime,
        symbol String,
        title String,
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by toDate(captured_at)
    order by (symbol, title, captured_at)
    ttl captured_at + interval 365 day delete
    """,
    """
    create table if not exists mootdx_f10_detail (
        captured_at DateTime,
        symbol String,
        title String,
        content String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by toDate(captured_at)
    order by (symbol, title, captured_at)
    ttl captured_at + interval 365 day delete
    """,
    """
    create table if not exists mootdx_affair_files (
        captured_at DateTime,
        filename String,
        hash String,
        filesize UInt64,
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by toDate(captured_at)
    order by (filename, captured_at)
    ttl captured_at + interval 365 day delete
    """,
]
