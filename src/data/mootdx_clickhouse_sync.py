"""Persist mootdx data into isolated ClickHouse tables."""

from __future__ import annotations

import fcntl
import json
from hashlib import sha256
from datetime import date, datetime, timedelta
from pathlib import Path
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
_INGESTION_SEQUENCE_LOCK = Path("/tmp/mootdx_ingestion_sequence.lock")


def ensure_mootdx_tables(client: Any) -> None:
    for sql in MOOTDX_TABLE_SQL:
        client.execute(sql)
    client.execute(MOOTDX_XDXR_CURRENT_VIEW_SQL)
    _ensure_mootdx_xdxr_nullable_columns(client)
    _ensure_mootdx_ingest_sequence_columns(client)
    _ensure_mootdx_ingestion_runs_retention(client)
    _ensure_mootdx_xdxr_symbol_runs_columns(client)
    _ensure_mootdx_catalog_lifecycle_columns(client)
    client.execute(MOOTDX_DAILY_XDXR_EVENTS_VIEW_SQL)


def sync_mootdx_offline_data(
    *,
    client: Any | None = None,
    source: Any | None = None,
    baostock_source: Any | None = None,
    symbols: list[str] | None = None,
    trade_date: date | None = None,
    frequencies: list[str] | None = None,
    tasks: list[str] | None = None,
    include_beijing: bool = False,
    limit: int = 0,
    ensure_tables: bool = True,
    recheck_no_data: bool = False,
    daily_mode: str = "incremental",
    daily_offset: int = 800,
    start_date: date | None = None,
    end_date: date | None = None,
    daily_reconcile: bool = False,
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
    diagnostics: dict[str, Any] = {}

    if ensure_tables:
        _progress(progress, 5, "ensure_tables", "准备 mootdx 独立表")
        ensure_mootdx_tables(clickhouse)

    ingest_seq = _allocate_ingest_seq(
        clickhouse,
        run_id=run_id,
        task_key=selected_tasks[0] if len(selected_tasks) == 1 else "mootdx_offline_sync",
        started_at=run_started_at,
    )

    try:
        target_symbols = _resolve_symbols(data_source, symbols=symbols, limit=limit, client=clickhouse, include_beijing=include_beijing)
        reconciliation_diagnostics = None
        if daily_reconcile:
            candidate_symbols = target_symbols
            target_symbols = _symbols_missing_daily_kline(clickhouse, candidate_symbols, selected_trade_date)
            reconciliation_diagnostics = {
                "candidate_symbols": len(candidate_symbols),
                "missing_symbols": len(target_symbols),
                "missing_symbols_sample": target_symbols[:20],
            }
        _progress(progress, 15, "resolved_symbols", f"解析 mootdx 股票池 {len(target_symbols)} 只")
    except Exception as exc:
        _mark_ingestion_run_failed(
            clickhouse,
            ingest_seq=ingest_seq,
            run_id=run_id,
            task_key=selected_tasks[0] if len(selected_tasks) == 1 else "mootdx_offline_sync",
            started_at=run_started_at,
            exc=exc,
        )
        raise

    task_count = max(1, len(selected_tasks))
    for index, task in enumerate(selected_tasks, start=1):
        try:
            _progress(progress, 15 + int(index / task_count * 75), task, f"执行 mootdx 离线任务 {task}")
            rows_by_table = _run_task(
                task=task,
                source=data_source,
                baostock_source=baostock_source,
                symbols=target_symbols,
                catalog_symbols=symbols,
                run_id=run_id,
                trade_date=selected_trade_date,
                frequencies=selected_frequencies,
                client=clickhouse,
                ingest_seq=ingest_seq,
                diagnostics=diagnostics,
                progress=progress,
                recheck_no_data=recheck_no_data,
                daily_mode=daily_mode,
                daily_offset=daily_offset,
                start_date=start_date,
                end_date=end_date,
            )
            for table, rows in rows_by_table.items():
                if not rows:
                    inserted[table] = inserted.get(table, 0)
                    continue
                rows_to_insert = _with_ingest_seq(rows, ingest_seq) if table in {"mootdx_stock_kline", "mootdx_xdxr"} else rows
                _insert_rows(clickhouse, table, rows_to_insert)
                inserted[table] = inserted.get(table, 0) + len(rows)
                if table == "mootdx_stock_catalog":
                    clickhouse.execute("optimize table mootdx_stock_catalog final")
                if table == "mootdx_stock_kline" and task == "stock_kline_daily":
                    _optimize_stock_kline_partitions(clickhouse, rows)
            if task == "xdxr" and diagnostics.get("xdxr", {}).get("circuit_breaker_triggered"):
                failed[task] = "RuntimeError: XDXR circuit breaker triggered after 3 consecutive symbol errors"
            if task == "stock_kline_daily" and reconciliation_diagnostics is not None:
                diagnostics.setdefault("stock_kline_daily", {})["reconciliation"] = reconciliation_diagnostics
        except Exception as exc:  # noqa: BLE001 - offline sync records per-task failures.
            failed[task] = f"{type(exc).__name__}: {str(exc)[:240]}"

    result = {
        "run_id": run_id,
        "ingest_seq": ingest_seq,
        "trade_date": selected_trade_date.isoformat(),
        "tasks": selected_tasks,
        "symbols": target_symbols,
        "inserted": inserted,
        "failed": failed,
        "diagnostics": diagnostics,
        "duration_seconds": round(perf_counter() - started, 3),
    }
    _write_run_row(
        clickhouse,
        run_id=run_id,
        task_key=selected_tasks[0] if len(selected_tasks) == 1 else "mootdx_offline_sync",
        started_at=run_started_at,
        status="failed" if failed else "success",
        params={
            "symbols": symbols,
            "trade_date": selected_trade_date.isoformat(),
            "frequencies": selected_frequencies,
            "tasks": selected_tasks,
            "limit": limit,
            "include_beijing": include_beijing,
            "recheck_no_data": recheck_no_data,
            "daily_mode": daily_mode,
            "daily_offset": daily_offset,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "daily_reconcile": daily_reconcile,
        },
        result=result,
        error=json.dumps(failed, ensure_ascii=False) if failed else "",
    )
    _write_ingestion_run_row(
        clickhouse,
        ingest_seq=ingest_seq,
        run_id=run_id,
        task_key=selected_tasks[0] if len(selected_tasks) == 1 else "mootdx_offline_sync",
        started_at=run_started_at,
        finished_at=_now(),
        status="failed" if failed else "succeeded",
        row_count=sum(inserted.get(table, 0) for table in ("mootdx_stock_kline", "mootdx_xdxr_event_versions")),
        error=json.dumps(failed, ensure_ascii=False) if failed else "",
        version=2,
    )
    _progress(progress, 100, "completed", "mootdx 离线同步完成")
    return result


def _run_task(
    *,
    task: str,
    source: Any,
    baostock_source: Any | None = None,
    symbols: list[str],
    catalog_symbols: list[str] | None = None,
    run_id: str = "",
    trade_date: date,
    frequencies: list[str],
    client: Any = None,
    ingest_seq: int = 0,
    diagnostics: dict[str, Any] | None = None,
    progress: ProgressCallback | None = None,
    recheck_no_data: bool = False,
    daily_mode: str = "incremental",
    daily_offset: int = 800,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, list[tuple]]:
    if task == "stock_catalog":
        rows, catalog_diagnostics, event_rows = _stock_catalog_rows(source, catalog_symbols, client, run_id=run_id)
        if diagnostics is not None:
            diagnostics["stock_catalog"] = catalog_diagnostics
        return {"mootdx_stock_catalog": rows, "mootdx_catalog_change_events": event_rows}
    if task == "quote_snapshot":
        return {"mootdx_quote_snapshots": _quote_snapshot_rows(source, symbols)}
    if task == "stock_kline_daily":
        return {
            "mootdx_stock_kline": _daily_kline_rows(
                source,
                symbols,
                trade_date,
                baostock_source=baostock_source,
                run_id=run_id,
                client=client,
                diagnostics=diagnostics,
                progress=progress,
                recheck_no_data=recheck_no_data,
                mode=daily_mode,
                backfill_offset=daily_offset,
                start_date=start_date,
                end_date=end_date,
            )
        }
    if task == "stock_kline_intraday":
        return {"mootdx_stock_kline": _intraday_kline_rows(source, symbols, trade_date, frequencies)}
    if task == "index_kline":
        return {"mootdx_index_kline": _index_kline_rows(source, frequencies)}
    if task == "xdxr":
        rows, audit_rows, xdxr_diagnostics = _xdxr_rows(source, symbols, run_id=run_id)
        version_rows, observation_rows = _xdxr_version_rows(
            client,
            rows,
            audit_rows,
            ingest_seq=ingest_seq,
        )
        if diagnostics is not None:
            diagnostics["xdxr"] = xdxr_diagnostics
        return {
            # Kept only until Task 3 replaces this table with the compatible current view.
            "mootdx_xdxr": rows,
            "mootdx_xdxr_event_versions": version_rows,
            "mootdx_xdxr_symbol_observations": observation_rows,
            "mootdx_xdxr_symbol_runs": audit_rows,
        }
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


def _resolve_symbols(
    source: Any,
    *,
    symbols: list[str] | None,
    limit: int,
    client: Any | None = None,
    include_beijing: bool = False,
) -> list[str]:
    if symbols:
        result = list(dict.fromkeys(symbols))
    else:
        result = _latest_catalog_symbols(client, include_beijing=include_beijing)
        if not result:
            result = [stock.symbol for stock in source.fetch_stock_list() if not getattr(stock, "is_st", False)]
    if limit > 0:
        return result[:limit]
    return result


def _latest_catalog_symbols(client: Any | None, *, include_beijing: bool) -> list[str]:
    if client is None:
        return []
    try:
        rows = client.execute(
            "select symbol, argMax(market, captured_at), argMax(is_st, captured_at), argMax(is_active, captured_at) "
            "from mootdx_stock_catalog group by symbol order by symbol"
        )
    except Exception:  # noqa: BLE001 - empty or missing catalog falls back to source stock list.
        return []
    symbols = []
    allowed_markets = {0, 1, *({2} if include_beijing else set())}
    for row in rows:
        symbol = str(row[0] or "")
        market = int(row[1])
        is_st_flag = int(row[2])
        is_active_flag = int(row[3]) if len(row) > 3 else 1
        if symbol and market in allowed_markets and not is_st_flag and is_active_flag:
            symbols.append(symbol)
    return symbols


def _symbols_missing_daily_kline(client: Any, symbols: list[str], trade_date: date) -> list[str]:
    if not symbols:
        return []
    rows = client.execute(
        "select distinct symbol from mootdx_stock_kline final "
        "where trade_date = %(trade_date)s and frequency = 'daily' and symbol in %(symbols)s",
        {"trade_date": trade_date, "symbols": tuple(symbols)},
    )
    loaded_symbols = {str(row[0]) for row in rows}
    return [symbol for symbol in symbols if symbol not in loaded_symbols]


def _stock_catalog_rows(
    source: Any,
    symbols: list[str] | None,
    client: Any,
    *,
    run_id: str,
) -> tuple[list[tuple], dict[str, Any], list[tuple]]:
    captured_at = _now()
    selected = set(symbols) if symbols is not None else None
    latest = _latest_catalog_by_symbol(client)
    source_snapshot: dict[str, tuple] = {}
    source_rows = source.fetch_stock_list()
    for stock in source_rows:
        if selected is not None and stock.symbol not in selected:
            continue
        market_code = _market_code(stock.symbol)
        is_st_flag = 1 if stock.is_st or is_st(stock.name) else 0
        # Mootdx may expose newly listed stock codes as integers, while the
        # ClickHouse catalog schema stores ``code`` as String.
        source_snapshot[stock.symbol] = (market_code, str(stock.code or ""), stock.name, is_st_flag)
    source_symbols = set(source_snapshot)
    common_symbols = source_symbols & set(latest)
    previous_active_symbols = {symbol for symbol, snapshot in latest.items() if snapshot[4]}
    audit = _catalog_audit({"source_symbols": len(source_symbols)}, previous_symbols=len(previous_active_symbols))
    snapshot_healthy = audit["status"] == "healthy"
    rows = []
    dormant_symbols = 0
    for symbol, current in source_snapshot.items():
        previous = latest.get(symbol)
        reactivated = previous is not None and not previous[4]
        if previous is not None and previous[:4] == current and previous[4] and previous[5] == 0:
            continue
        rows.append(_catalog_row(
            captured_at, symbol, current, is_active=1, missing_catalog_runs=0,
            last_seen_at=captured_at, deactivated_at=None,
            reactivated_at=captured_at if reactivated else None,
        ))
    if snapshot_healthy:
        for symbol in sorted(set(latest) - source_symbols):
            previous = latest[symbol]
            next_missing_runs = previous[5] + 1
            next_active = 0 if next_missing_runs >= 2 else previous[4]
            if not next_active:
                dormant_symbols += 1
            rows.append(_catalog_row(
                captured_at, symbol, previous[:4], is_active=next_active,
                missing_catalog_runs=next_missing_runs, last_seen_at=previous[6],
                deactivated_at=captured_at if previous[4] and not next_active else previous[7],
                reactivated_at=None,
            ))
    diagnostics: dict[str, Any] = {
        "source_symbols": len(source_symbols),
        "inserted_symbols": len(rows),
        "new_symbols": len(source_symbols - set(latest)),
        "changed_symbols": sum(source_snapshot[symbol] != latest[symbol][:4] for symbol in common_symbols),
        "removed_symbols": len(set(latest) - source_symbols),
        "dormant_symbols": dormant_symbols,
        "st_changed_symbols": sum(source_snapshot[symbol][3] != latest[symbol][3] for symbol in common_symbols),
    }
    diagnostics["audit"] = audit
    return rows, diagnostics, _catalog_change_event_rows(
        captured_at=captured_at,
        source_snapshot=source_snapshot,
        latest_snapshot=latest,
        run_id=run_id,
        snapshot_healthy=snapshot_healthy,
    )


def _catalog_change_event_rows(
    *,
    captured_at: datetime,
    source_snapshot: dict[str, tuple],
    latest_snapshot: dict[str, tuple],
    run_id: str,
    snapshot_healthy: bool,
) -> list[tuple]:
    rows = []
    for symbol in sorted(set(source_snapshot) - set(latest_snapshot)):
        rows.append(_catalog_change_event_row(captured_at, symbol, "added", None, source_snapshot[symbol], run_id))
    if snapshot_healthy:
        for symbol in sorted(set(latest_snapshot) - set(source_snapshot)):
            previous = latest_snapshot[symbol]
            if previous[4] and previous[5] + 1 >= 2:
                rows.append(_catalog_change_event_row(captured_at, symbol, "removed", previous[:4], None, run_id))
    for symbol in sorted(set(source_snapshot) & set(latest_snapshot)):
        previous = latest_snapshot[symbol][:4]
        current = source_snapshot[symbol]
        if previous[2] != current[2]:
            rows.append(_catalog_change_event_row(captured_at, symbol, "name_changed", previous, current, run_id))
        if previous[3] != current[3]:
            rows.append(_catalog_change_event_row(captured_at, symbol, "st_changed", previous, current, run_id))
        if previous[0] != current[0]:
            rows.append(_catalog_change_event_row(captured_at, symbol, "market_changed", previous, current, run_id))
    return rows


def _catalog_change_event_row(
    event_at: datetime,
    symbol: str,
    event_type: str,
    previous: tuple | None,
    current: tuple | None,
    run_id: str,
) -> tuple:
    return (
        event_at,
        symbol,
        event_type,
        _json(_catalog_snapshot_json(previous)),
        _json(_catalog_snapshot_json(current)),
        run_id,
        "mootdx",
    )


def _catalog_snapshot_json(snapshot: tuple | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {"market": snapshot[0], "code": snapshot[1], "name": snapshot[2], "is_st": snapshot[3]}


def _catalog_audit(diagnostics: dict[str, Any], *, previous_symbols: int) -> dict[str, Any]:
    if diagnostics["source_symbols"] == 0:
        return {"status": "failed", "reasons": ["catalog_source_empty"]}
    if previous_symbols and abs(diagnostics["source_symbols"] - previous_symbols) / previous_symbols > 0.02:
        return {"status": "degraded", "reasons": ["catalog_count_changed"]}
    return {"status": "healthy", "reasons": []}


def _latest_catalog_by_symbol(client: Any) -> dict[str, tuple]:
    if client is None:
        return {}
    try:
        rows = client.execute(
            "select symbol, argMax(market, captured_at), argMax(code, captured_at), "
            "argMax(name, captured_at), argMax(is_st, captured_at), argMax(is_active, captured_at), "
            "argMax(missing_catalog_runs, captured_at), argMax(last_seen_at, captured_at), "
            "argMax(deactivated_at, captured_at) "
            "from mootdx_stock_catalog group by symbol"
        )
    except Exception:  # noqa: BLE001 - missing table or unreadable catalog => treat as empty.
        return {}
    return {
        row[0]: (
            int(row[1]), row[2], row[3], int(row[4]),
            int(row[5]) if len(row) > 5 else 1,
            int(row[6]) if len(row) > 6 else 0,
            row[7] if len(row) > 7 else None,
            row[8] if len(row) > 8 else None,
        )
        for row in rows
    }


def _catalog_row(
    captured_at: datetime,
    symbol: str,
    snapshot: tuple,
    *,
    is_active: int,
    missing_catalog_runs: int,
    last_seen_at: datetime | None,
    deactivated_at: datetime | None,
    reactivated_at: datetime | None,
) -> tuple:
    return (
        captured_at, snapshot[0], symbol, snapshot[1], snapshot[2], snapshot[3], is_active,
        missing_catalog_runs, last_seen_at, deactivated_at, reactivated_at, "mootdx",
        _json({"symbol": symbol, "code": snapshot[1], "name": snapshot[2]}),
    )


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


def _daily_kline_rows(
    source: Any,
    symbols: list[str],
    trade_date: date,
    *,
    baostock_source: Any | None = None,
    run_id: str = "",
    client: Any | None = None,
    diagnostics: dict[str, Any] | None = None,
    progress: ProgressCallback | None = None,
    offsets: tuple[int, ...] = (5, 20, 800),
    recheck_no_data: bool = False,
    mode: str = "incremental",
    backfill_offset: int = 800,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[tuple]:
    if mode not in {"incremental", "backfill"}:
        raise ValueError(f"unknown daily kline mode: {mode}")
    rows = []
    dropped_rows = 0
    empty_symbols: list[str] = []
    confirmed_no_data_symbols: list[str] = []
    failed_symbols: list[dict[str, Any]] = []
    no_data_status_rows: list[tuple] = []
    active_status_rows: list[tuple] = []
    temporary_failed_status_rows: list[tuple] = []
    verification_rows: list[tuple] = []
    baostock_counts = {"available": 0, "no_data": 0, "error": 0}
    retry_success_count = 0
    effective_offsets = (backfill_offset,) if mode == "backfill" else offsets
    status_by_symbol = _latest_symbol_data_status_records(client, data_kind="stock_kline_daily")
    skipped_no_data_symbols = [] if recheck_no_data else [
        symbol
        for symbol in symbols
        if _should_skip_daily_symbol(status_by_symbol.get(symbol), trade_date=trade_date)
    ]
    active_symbols = [symbol for symbol in symbols if symbol not in set(skipped_no_data_symbols)]
    for symbol_index, symbol in enumerate(active_symbols, start=1):
        _progress(progress, 20 + int((symbol_index - 1) / max(1, len(active_symbols)) * 70), "stock_kline_daily", f"同步日线 {symbol}", processed=symbol_index - 1, total=len(active_symbols))
        attempts = []
        symbol_rows: list[tuple] = []
        symbol_dropped = 0
        fetch_start = start_date or trade_date
        fetch_end = end_date or trade_date
        for attempt_index, offset in enumerate(effective_offsets):
            try:
                frame = source.fetch_bars(symbol, fetch_start, fetch_end, "daily", offset=offset)
            except Exception as exc:  # noqa: BLE001 - symbol-level failures should not fail the whole daily task.
                attempts.append({
                    "offset": offset,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:160],
                })
                continue
            candidate_rows = _stock_kline_rows_from_frame(frame, frequency="daily")
            valid_rows, invalid_count = _filter_stock_kline_rows(
                candidate_rows,
                trade_date=trade_date if mode == "incremental" else None,
                start_date=start_date if mode == "backfill" else None,
                end_date=end_date if mode == "backfill" else None,
            )
            symbol_dropped += invalid_count
            if valid_rows:
                attempts.append({"offset": offset, "status": "success", "rows": len(valid_rows), "dropped_rows": invalid_count})
                symbol_rows = valid_rows
                if attempt_index > 0:
                    retry_success_count += 1
                break
            if invalid_count:
                attempts.append({"offset": offset, "status": "invalid", "rows": len(candidate_rows), "dropped_rows": invalid_count})
                break
            attempts.append({"offset": offset, "status": "empty", "rows": 0})
        dropped_rows += symbol_dropped
        if symbol_rows:
            rows.extend(symbol_rows)
            active_status_rows.append(_symbol_data_status_row(
                symbol=symbol,
                data_kind="stock_kline_daily",
                status="active",
                reason="daily_bar_loaded",
                consecutive_failures=0,
                last_success_at=_now(),
                previous=status_by_symbol.get(symbol),
                details={"trade_date": trade_date.isoformat(), "rows": len(symbol_rows), "attempts": attempts},
            ))
            continue
        if any(attempt["status"] == "error" for attempt in attempts):
            failed_symbols.append({"symbol": symbol, "attempts": attempts, "final_status": "failed"})
            temporary_failed_status_rows.append(_symbol_data_status_row(
                symbol=symbol,
                data_kind="stock_kline_daily",
                status="temporary_failed",
                reason="fetch_error",
                previous=status_by_symbol.get(symbol),
                details={"trade_date": trade_date.isoformat(), "attempts": attempts},
            ))
            continue
        if symbol_dropped:
            empty_symbols.append(symbol)
            no_data_status_rows.append(_symbol_data_status_row(
                symbol=symbol,
                data_kind="stock_kline_daily",
                status="no_data",
                reason="invalid_rows",
                previous=status_by_symbol.get(symbol),
                details={"trade_date": trade_date.isoformat(), "attempts": attempts},
            ))
            continue
        verification = _verify_baostock_daily(
            baostock_source,
            symbol=symbol,
            start_date=fetch_start,
            end_date=fetch_end,
        )
        verified_rows = _stock_kline_rows_from_frame(
            _tradable_baostock_daily_frame(verification["frame"]),
            frequency="daily",
            source="baostock",
        )
        verified_rows, verified_invalid = _filter_stock_kline_rows(
            verified_rows,
            trade_date=trade_date if mode == "incremental" else None,
            start_date=start_date if mode == "backfill" else None,
            end_date=end_date if mode == "backfill" else None,
        )
        verdict_by_date = _baostock_verdicts(
            symbol=symbol,
            start_date=fetch_start,
            end_date=fetch_end,
            verified_rows=verified_rows,
            error=verification["error"],
        )
        verification_rows.extend(
            _daily_gap_verification_row(
                run_id=run_id,
                symbol=symbol,
                trade_date=verified_date,
                verdict=verdict,
                details={"error": verification["error"], "invalid_rows": verified_invalid},
            )
            for verified_date, verdict in verdict_by_date.items()
        )
        for verdict in verdict_by_date.values():
            baostock_counts[verdict] += 1
        if verified_rows:
            rows.extend(verified_rows)
            active_status_rows.append(_symbol_data_status_row(
                symbol=symbol,
                data_kind="stock_kline_daily",
                status="active",
                reason="baostock_backfill",
                consecutive_failures=0,
                last_success_at=_now(),
                previous=status_by_symbol.get(symbol),
                details={"trade_date": trade_date.isoformat(), "rows": len(verified_rows)},
            ))
            continue
        if verification["error"]:
            failed_symbols.append({"symbol": symbol, "attempts": attempts, "final_status": "baostock_verification_error"})
            temporary_failed_status_rows.append(_symbol_data_status_row(
                symbol=symbol,
                data_kind="stock_kline_daily",
                status="temporary_failed",
                reason="baostock_verification_error",
                previous=status_by_symbol.get(symbol),
                details={"trade_date": trade_date.isoformat(), "attempts": attempts, "error": verification["error"]},
            ))
            continue
        empty_symbols.append(symbol)
        confirmed_no_data_symbols.append(symbol)
        no_data_status_rows.append(_symbol_data_status_row(
            symbol=symbol,
            data_kind="stock_kline_daily",
            status="no_data",
            reason="empty_all_offsets",
            previous=status_by_symbol.get(symbol),
            details={"trade_date": trade_date.isoformat(), "attempts": attempts},
        ))
    status_rows = [*active_status_rows, *temporary_failed_status_rows, *no_data_status_rows]
    if status_rows and client is not None:
        _insert_symbol_data_status_rows(client, status_rows)
    if verification_rows and client is not None:
        client.execute("insert into mootdx_daily_gap_verifications values", verification_rows)
    if diagnostics is not None:
        requested_count = len(active_symbols)
        loaded_symbol_count = len({row[3] for row in rows})
        known_no_data_count = len(skipped_no_data_symbols) + len(confirmed_no_data_symbols)
        logical_covered_count = loaded_symbol_count + known_no_data_count
        daily_diagnostics = {
            "mode": mode,
            "target_symbols": len(symbols),
            "requested_symbols": requested_count,
            "inserted_rows": len(rows),
            "empty_symbols_count": len(empty_symbols),
            "failed_symbols_count": len(failed_symbols),
            "skipped_no_data_symbols_count": len(skipped_no_data_symbols),
            "new_no_data_symbols_count": len(no_data_status_rows),
            "known_no_data_symbols_count": known_no_data_count,
            "active_status_updates_count": len(active_status_rows),
            "temporary_failed_status_updates_count": len(temporary_failed_status_rows),
            "retry_success_count": retry_success_count,
            "dropped_rows": dropped_rows,
            # Known no-data symbols are resolved exclusions, not failed requests.
            "coverage_rate": round(logical_covered_count / len(symbols), 4) if symbols else 1.0,
            "catalog_coverage_rate": round(loaded_symbol_count / len(symbols), 4) if symbols else 1.0,
            "daily_offsets": list(effective_offsets),
            "daily_offset": backfill_offset if mode == "backfill" else None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "skipped_no_data_symbols_sample": skipped_no_data_symbols[:20],
            "empty_symbols_sample": empty_symbols[:20],
            "failed_symbols_sample": failed_symbols[:20],
            "baostock": baostock_counts,
        }
        daily_diagnostics["audit"] = _daily_kline_audit(daily_diagnostics)
        diagnostics["stock_kline_daily"] = daily_diagnostics
    _progress(progress, 90, "stock_kline_daily", "日线同步完成", processed=len(active_symbols), total=len(active_symbols))
    return rows


def _daily_kline_audit(diagnostics: dict[str, Any]) -> dict[str, Any]:
    if diagnostics["target_symbols"] == 0:
        return {"status": "healthy", "reasons": []}
    reasons = []
    if diagnostics["coverage_rate"] < 0.995:
        reasons.append("coverage_below_target")
    if diagnostics["failed_symbols_count"]:
        reasons.append("symbol_fetch_failed")
    if diagnostics["dropped_rows"]:
        reasons.append("invalid_rows_dropped")
    if diagnostics["coverage_rate"] < 0.98:
        return {"status": "failed", "reasons": reasons}
    if reasons:
        return {"status": "degraded", "reasons": reasons}
    return {"status": "healthy", "reasons": []}


def _filter_stock_kline_rows(
    rows: list[tuple],
    *,
    trade_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[tuple], int]:
    valid = []
    dropped = 0
    for row in rows:
        if _is_valid_stock_kline_row(row, trade_date=trade_date, start_date=start_date, end_date=end_date):
            valid.append(row)
        else:
            dropped += 1
    return valid, dropped


def _is_valid_stock_kline_row(
    row: tuple,
    *,
    trade_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> bool:
    if len(row) < 10:
        return False
    row_trade_date = row[1]
    symbol = str(row[3] or "")
    open_price = float(row[4])
    high_price = float(row[5])
    low_price = float(row[6])
    close_price = float(row[7])
    volume = int(row[8])
    amount = float(row[9])
    if trade_date is not None and row_trade_date != trade_date:
        return False
    if start_date is not None and row_trade_date < start_date:
        return False
    if end_date is not None and row_trade_date > end_date:
        return False
    if not symbol:
        return False
    if min(open_price, high_price, low_price, close_price) <= 0:
        return False
    if high_price < max(open_price, low_price, close_price):
        return False
    if low_price > min(open_price, high_price, close_price):
        return False
    return volume >= 0 and amount >= 0


def _latest_symbol_data_status_records(client: Any | None, *, data_kind: str) -> dict[str, dict[str, Any]]:
    if client is None:
        return {}
    try:
        rows = client.execute(
            "select symbol, argMax(status, last_checked_at), argMax(first_seen_at, last_checked_at), "
            "argMax(last_checked_at, last_checked_at), argMax(consecutive_failures, last_checked_at), "
            "argMax(last_success_at, last_checked_at), argMax(raw_json, last_checked_at) "
            "from mootdx_symbol_data_status "
            "where data_kind = %(data_kind)s group by symbol",
            {"data_kind": data_kind},
        )
    except Exception:  # noqa: BLE001 - missing status table should not block first sync.
        return {}
    return {
        str(row[0]): {
            "status": str(row[1]),
            "first_seen_at": row[2] if len(row) > 2 else None,
            "last_checked_at": row[3] if len(row) > 3 else None,
            "consecutive_failures": int(row[4]) if len(row) > 4 else 0,
            "last_success_at": row[5] if len(row) > 5 else None,
            "no_data_trade_date": _status_trade_date(row[6]) if len(row) > 6 else None,
        }
        for row in rows
    }


def _should_skip_daily_symbol(record: dict[str, Any] | None, *, trade_date: date) -> bool:
    if record is None:
        return False
    status = record.get("status")
    if status == "disabled":
        return True
    if status != "no_data":
        return False
    no_data_trade_date = record.get("no_data_trade_date")
    if isinstance(no_data_trade_date, date):
        return no_data_trade_date == trade_date
    checked_at = record.get("last_checked_at")
    if not isinstance(checked_at, datetime):
        return True
    return checked_at.date() > trade_date - timedelta(days=30)


def _status_trade_date(raw_json: Any) -> date | None:
    try:
        value = json.loads(str(raw_json or "{}")).get("trade_date")
        return date.fromisoformat(str(value)) if value else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _symbol_data_status_row(
    *,
    symbol: str,
    data_kind: str,
    status: str,
    reason: str,
    details: dict[str, Any],
    consecutive_failures: int | None = None,
    last_success_at: datetime | None = None,
    previous: dict[str, Any] | None = None,
) -> tuple:
    checked_at = _now()
    first_seen_at = (previous or {}).get("first_seen_at") or checked_at
    if consecutive_failures is None:
        consecutive_failures = int((previous or {}).get("consecutive_failures") or 0) + 1 if status == "temporary_failed" else 0
    return (
        symbol,
        data_kind,
        status,
        reason,
        first_seen_at,
        checked_at,
        consecutive_failures,
        last_success_at,
        "mootdx",
        _json(details),
    )


def _insert_symbol_data_status_rows(client: Any, rows: list[tuple]) -> None:
    client.execute("insert into mootdx_symbol_data_status values", rows)


def _intraday_kline_rows(source: Any, symbols: list[str], trade_date: date, frequencies: list[str]) -> list[tuple]:
    rows = []
    intraday_frequencies = [frequency for frequency in frequencies if frequency not in {"daily", "day"}]
    for symbol in symbols:
        for frequency in intraday_frequencies:
            frame = source.fetch_intraday_bars(symbol, trade_date, frequency)
            rows.extend(_stock_kline_rows_from_frame(frame, frequency=frequency))
    return rows


def _stock_kline_rows_from_frame(frame: pd.DataFrame, *, frequency: str, source: str = "mootdx") -> list[tuple]:
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
            source,
            ingested_at,
            _json(row.to_dict()),
        ))
    return rows


def _verify_baostock_daily(
    source: Any | None,
    *,
    symbol: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    try:
        if source is None:
            from src.data.baostock_source import BaostockSource

            source = BaostockSource()
        return {"frame": source.fetch_daily_bars(symbol, start_date, end_date), "error": ""}
    except Exception as exc:  # noqa: BLE001 - evidence must preserve external-source failures.
        return {"frame": pd.DataFrame(), "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def verify_mootdx_daily_gaps(
    *,
    items: list[Any],
    client: Any | None = None,
    baostock_source: Any | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    clickhouse = client or ClickHouseStockDataSource()._client_instance()
    ensure_mootdx_tables(clickhouse)
    run_id = uuid4().hex
    counts = {"available": 0, "no_data": 0, "error": 0}
    rows = []
    for index, item in enumerate(items, start=1):
        symbol = str(item.symbol)
        start_date, end_date = item.start_date, item.end_date
        trade_dates = getattr(item, "trade_dates", None) or _date_range(start_date, end_date)
        verification = _verify_baostock_daily(baostock_source, symbol=symbol, start_date=start_date, end_date=end_date)
        bars = _stock_kline_rows_from_frame(_tradable_baostock_daily_frame(verification["frame"]), frequency="daily", source="baostock")
        verdicts = _baostock_verdicts(symbol=symbol, trade_dates=trade_dates, verified_rows=bars, error=verification["error"])
        for trade_date, verdict in verdicts.items():
            counts[verdict] += 1
            rows.append(_daily_gap_verification_row(run_id=run_id, symbol=symbol, trade_date=trade_date, verdict=verdict, details={"error": verification["error"], "trigger": "manual_quality_verify"}))
        _progress(progress, int(index / len(items) * 100), "verifying", f"核验 {symbol} {start_date} 至 {end_date}")
    if rows:
        clickhouse.execute("insert into mootdx_daily_gap_verifications values", rows)
    return {"run_id": run_id, "requested_items": len(items), **counts}


def _tradable_baostock_daily_frame(frame: Any) -> pd.DataFrame:
    candidate = _safe_frame(frame)
    if candidate.empty or "tradestatus" not in candidate.columns:
        return pd.DataFrame(columns=candidate.columns)
    statuses = pd.to_numeric(candidate["tradestatus"], errors="coerce")
    return candidate.loc[statuses == 1].copy()


def _baostock_verdicts(
    *,
    symbol: str,
    verified_rows: list[tuple],
    error: str,
    start_date: date | None = None,
    end_date: date | None = None,
    trade_dates: list[date] | None = None,
) -> dict[date, str]:
    if trade_dates is None:
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required when trade_dates is omitted")
        dates = _date_range(start_date, end_date)
    else:
        dates = trade_dates
    if error:
        return {value: "error" for value in dates}
    found_dates = {row[1] for row in verified_rows if row[3] == symbol}
    return {value: "available" if value in found_dates else "no_data" for value in dates}


def _date_range(start_date: date, end_date: date) -> list[date]:
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]


def _daily_gap_verification_row(
    *,
    run_id: str,
    symbol: str,
    trade_date: date,
    verdict: str,
    details: dict[str, Any],
) -> tuple:
    return (_now(), run_id, symbol, "daily", trade_date, verdict, "baostock", _json(details))


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


def _xdxr_rows(source: Any, symbols: list[str], *, run_id: str = "") -> tuple[list[tuple], list[tuple], dict[str, Any]]:
    ingested_at = _now()
    rows: list[tuple] = []
    audit_rows: list[tuple] = []
    empty_symbols: list[str] = []
    success_symbols: list[str] = []
    failed_symbols: list[dict[str, str]] = []
    invalid_event_rows = 0
    request_seconds = 0.0
    parse_seconds = 0.0
    consecutive_errors = 0
    circuit_breaker_triggered = False
    for symbol in symbols:
        requested_at = _now()
        request_started = perf_counter()
        try:
            frame = source.fetch_xdxr(symbol)
        except Exception as exc:  # noqa: BLE001 - xdxr diagnostics should keep the batch auditable.
            request_ms = (perf_counter() - request_started) * 1000
            request_seconds += request_ms / 1000
            error = f"{type(exc).__name__}: {str(exc)}"[:240]
            failed_symbols.append({"symbol": symbol, "error": error})
            audit_rows.append((run_id, symbol, requested_at, "error", 0, request_ms, None, error, []))
            consecutive_errors += 1
            if consecutive_errors >= 3:
                circuit_breaker_triggered = True
                break
            continue
        request_ms = (perf_counter() - request_started) * 1000
        request_seconds += request_ms / 1000
        parse_started = perf_counter()
        frame = _safe_frame(frame)
        if frame.empty:
            empty_symbols.append(symbol)
            parse_ms = (perf_counter() - parse_started) * 1000
            parse_seconds += parse_ms / 1000
            audit_rows.append((run_id, symbol, requested_at, "empty", 0, request_ms, parse_ms, "", list(frame.columns)))
            consecutive_errors = 0
            continue
        symbol_event_rows = 0
        for _, row in _safe_frame(frame).iterrows():
            event_date = _ymd_date(row)
            if event_date is None:
                invalid_event_rows += 1
                continue
            rows.append((
                symbol,
                event_date,
                int(_float(row.get("category"))),
                str(row.get("name") or ""),
                _nullable_float(row.get("fenhong")),
                _nullable_float(row.get("peigujia")),
                _nullable_float(row.get("songzhuangu")),
                _nullable_float(row.get("peigu")),
                _nullable_float(row.get("suogu")),
                _nullable_float(row.get("panqianliutong")),
                _nullable_float(row.get("panhouliutong")),
                _nullable_float(row.get("qianzongguben")),
                _nullable_float(row.get("houzongguben")),
                ingested_at,
                _json(row.to_dict()),
            ))
            symbol_event_rows += 1
        parse_ms = (perf_counter() - parse_started) * 1000
        parse_seconds += parse_ms / 1000
        success_symbols.append(symbol)
        audit_rows.append((
            run_id,
            symbol,
            requested_at,
            "success",
            symbol_event_rows,
            request_ms,
            parse_ms,
            "",
            list(frame.columns),
        ))
        consecutive_errors = 0
    diagnostics = {
        "target_symbols": len(symbols),
        "requested_symbols": len(audit_rows),
        "success_symbols": len(success_symbols),
        "event_rows": len(rows),
        "empty_symbols_count": len(empty_symbols),
        "invalid_event_rows": invalid_event_rows,
        "failed_symbols_count": len(failed_symbols),
        "failed_symbols_sample": failed_symbols[:20],
        "request_seconds": round(request_seconds, 6),
        "parse_seconds": round(parse_seconds, 6),
        "circuit_breaker_triggered": circuit_breaker_triggered,
    }
    return rows, audit_rows, diagnostics


def _xdxr_version_rows(
    client: Any | None,
    event_rows: list[tuple],
    audit_rows: list[tuple],
    *,
    ingest_seq: int,
) -> tuple[list[tuple], list[tuple]]:
    """Return changed event versions and one immutable observation per attempted symbol."""
    hashes_by_key = {_xdxr_event_key(row): _xdxr_content_hash(row) for row in event_rows}
    latest_hashes = _latest_xdxr_content_hashes(
        client,
        sorted({str(row[1]) for row in audit_rows}),
    )
    observed_at = _now()
    versions = []
    for row in event_rows:
        event_key = _xdxr_event_key(row)
        content_hash = hashes_by_key[event_key]
        if latest_hashes.get(event_key) == content_hash:
            continue
        versions.append((
            ingest_seq,
            *row[:13],
            content_hash,
            row[14],
            observed_at,
            0,
        ))
    hashes_by_symbol: dict[str, list[str]] = {}
    for (symbol, _, _), content_hash in hashes_by_key.items():
        hashes_by_symbol.setdefault(symbol, []).append(content_hash)
    observations = []
    for _, symbol, _, status, event_count, request_ms, parse_ms, error, _ in audit_rows:
        succeeded = status in {"success", "empty"}
        event_set_hash = _event_set_hash(hashes_by_symbol.get(symbol, [])) if succeeded else ""
        observations.append((
            ingest_seq,
            symbol,
            observed_at,
            "succeeded" if succeeded else "failed",
            event_count,
            event_set_hash,
            request_ms,
            parse_ms,
            error,
        ))
    return versions, observations


def _latest_xdxr_content_hashes(client: Any | None, symbols: list[str]) -> dict[tuple[str, date, int], str]:
    if client is None or not symbols:
        return {}
    escaped_symbols = ", ".join(f"'{symbol.replace("'", "''")}'" for symbol in symbols)
    rows = client.execute(
        "select version.symbol, version.event_date, version.category, "
        "argMax(version.content_hash, version.ingest_seq) "
        "from mootdx_xdxr_event_versions as version "
        "inner join (select ingest_seq from mootdx_ingestion_runs final where status = 'succeeded') as run "
        "on version.ingest_seq = run.ingest_seq "
        f"where version.symbol in ({escaped_symbols}) "
        "group by version.symbol, version.event_date, version.category"
    )
    return {
        (str(row[0]), row[1], int(row[2])): str(row[3])
        for row in rows
    }


def _xdxr_content_hash(row: tuple) -> str:
    business_values = [value.isoformat() if isinstance(value, date) else value for value in row[:13]]
    payload = json.dumps(business_values, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _xdxr_event_key(row: tuple) -> tuple[str, date, int]:
    return str(row[0]), row[1], int(row[2])


def _event_set_hash(content_hashes: list[str]) -> str:
    payload = json.dumps(sorted(content_hashes), separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


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
    if table == "mootdx_stock_catalog":
        client.execute(
            "insert into mootdx_stock_catalog "
            "(captured_at, market, symbol, code, name, is_st, is_active, missing_catalog_runs, "
            "last_seen_at, deactivated_at, reactivated_at, source, raw_json) values",
            rows,
        )
        return
    if table == "mootdx_stock_kline":
        batches: dict[tuple[Any, Any], list[tuple]] = {}
        for row in rows:
            batches.setdefault((row[1], row[2]), []).append(row)
        for batch in batches.values():
            client.execute(
                "insert into mootdx_stock_kline "
                "(datetime, trade_date, frequency, symbol, open, high, low, close, volume, amount, "
                "source, ingested_at, raw_json, ingest_seq) values",
                batch,
            )
        return
    if table == "mootdx_index_kline":
        batches: dict[tuple[Any, Any], list[tuple]] = {}
        for row in rows:
            batches.setdefault((row[1], row[2]), []).append(row)
        for batch in batches.values():
            client.execute(f"insert into {table} values", batch)
        return
    if table == "mootdx_xdxr":
        batches: dict[tuple[int, int], list[tuple]] = {}
        for row in rows:
            event_date = row[1]
            batches.setdefault((event_date.year, event_date.month), []).append(row)
        for batch in batches.values():
            client.execute(
                "insert into mootdx_xdxr "
                "(symbol, event_date, category, name, fenhong, peigujia, songzhuangu, peigu, suogu, "
                "panqianliutong, panhouliutong, qianzongguben, houzongguben, ingested_at, raw_json, ingest_seq) values",
                batch,
            )
        return
    if table == "mootdx_xdxr_event_versions":
        batches: dict[tuple[int, int], list[tuple]] = {}
        for row in rows:
            event_date = row[2]
            batches.setdefault((event_date.year, event_date.month), []).append(row)
        for batch in batches.values():
            client.execute(
                "insert into mootdx_xdxr_event_versions "
                "(ingest_seq, symbol, event_date, category, name, fenhong, peigujia, songzhuangu, peigu, suogu, "
                "panqianliutong, panhouliutong, qianzongguben, houzongguben, content_hash, raw_json, observed_at, migration_baseline) values",
                batch,
            )
        return
    if table == "mootdx_xdxr_symbol_observations":
        client.execute(
            "insert into mootdx_xdxr_symbol_observations "
            "(ingest_seq, symbol, observed_at, status, event_count, event_set_hash, request_ms, parse_ms, error) values",
            rows,
        )
        return
    if table == "mootdx_xdxr_symbol_runs":
        client.execute(
            "insert into mootdx_xdxr_symbol_runs "
            "(run_id, symbol, requested_at, status, event_rows, request_ms, parse_ms, error, raw_columns) values",
            rows,
        )
        return
    client.execute(f"insert into {table} values", rows)


def _ensure_mootdx_xdxr_nullable_columns(client: Any) -> None:
    for column in MOOTDX_XDXR_NULLABLE_FLOAT_COLUMNS:
        client.execute(f"alter table mootdx_xdxr modify column {column} Nullable(Float64)")


def _ensure_mootdx_ingest_sequence_columns(client: Any) -> None:
    """Backfill the sequence marker without rewriting existing Mootdx raw rows."""
    for table in ("mootdx_stock_kline", "mootdx_xdxr"):
        client.execute(f"alter table {table} add column if not exists ingest_seq UInt64 default 0")


def _ensure_mootdx_ingestion_runs_retention(client: Any) -> None:
    # The settled boundary is defined from sequence 1, so this compact audit
    # history must not age out while the raw tables remain consumable.
    rows = client.execute(
        """
        select create_table_query
        from system.tables
        where database = currentDatabase() and name = 'mootdx_ingestion_runs'
        """
    )
    create_table_query = str(rows[0][0]) if rows else ""
    if " TTL " in create_table_query.upper():
        client.execute("alter table mootdx_ingestion_runs remove ttl")


def _with_ingest_seq(rows: list[tuple], ingest_seq: int) -> list[tuple]:
    return [(*row, ingest_seq) for row in rows]


def _allocate_ingest_seq(client: Any, *, run_id: str, task_key: str, started_at: datetime) -> int:
    """Allocate once per sync run.

    The advisory file lock makes ``max + 1`` safe for the current single-host
    scheduler. Multiple scheduler hosts require a shared coordinator/sequence
    service before they can write these tables concurrently.
    """
    _INGESTION_SEQUENCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with _INGESTION_SEQUENCE_LOCK.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            rows = client.execute("select max(ingest_seq) from mootdx_ingestion_runs")
            latest = _first_clickhouse_value(rows)
            try:
                latest_seq = int(latest or 0)
            except (TypeError, ValueError):
                # Test doubles and unavailable audit tables may return unrelated
                # result rows; a real ClickHouse aggregate is numeric.
                latest_seq = 0
            ingest_seq = latest_seq + 1
            _write_ingestion_run_row(
                client,
                ingest_seq=ingest_seq,
                run_id=run_id,
                task_key=task_key,
                started_at=started_at,
                finished_at=None,
                status="running",
                row_count=0,
                error="",
                version=1,
            )
            return ingest_seq
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _latest_settled_ingest_seq(client: Any) -> int:
    """Return the contiguous terminal-run watermark, never skipping a running run.

    Failed runs are terminal and therefore advance the watermark, but consumers
    must still join ``mootdx_ingestion_runs`` on ``status = 'succeeded'`` when
    selecting input rows. This makes the watermark a safe progress boundary,
    not an assertion that every sequence below it supplied usable input.
    """
    rows = client.execute(
        "select ingest_seq, status from mootdx_ingestion_runs final order by ingest_seq"
    )
    expected = 1
    for row in rows:
        try:
            ingest_seq = int(row[0])
            status = str(row[1])
        except (IndexError, TypeError, ValueError):
            return expected - 1
        if ingest_seq != expected or status not in {"succeeded", "failed"}:
            return expected - 1
        expected += 1
    return expected - 1


def _write_ingestion_run_row(
    client: Any,
    *,
    ingest_seq: int,
    run_id: str,
    task_key: str,
    started_at: datetime,
    finished_at: datetime | None,
    status: str,
    row_count: int,
    error: str,
    version: int,
) -> None:
    client.execute(
        "insert into mootdx_ingestion_runs "
        "(ingest_seq, run_id, task_key, started_at, finished_at, status, row_count, error, version) values",
        [(ingest_seq, run_id, task_key, started_at, finished_at, status, row_count, error, version)],
    )


def _mark_ingestion_run_failed(
    client: Any,
    *,
    ingest_seq: int,
    run_id: str,
    task_key: str,
    started_at: datetime,
    exc: Exception,
) -> None:
    _write_ingestion_run_row(
        client,
        ingest_seq=ingest_seq,
        run_id=run_id,
        task_key=task_key,
        started_at=started_at,
        finished_at=_now(),
        status="failed",
        row_count=0,
        error=f"{type(exc).__name__}: {str(exc)[:240]}",
        version=2,
    )


def _ensure_mootdx_xdxr_symbol_runs_columns(client: Any) -> None:
    columns = client.execute(
        "select type from system.columns "
        "where database = currentDatabase() and table = 'mootdx_xdxr_symbol_runs' and name = 'raw_columns'"
    )
    column_type = _first_clickhouse_value(columns)
    if column_type == "String":
        # ClickHouse cannot safely MODIFY String to Array(String) in place. Retain legacy
        # JSON text under a distinct name and add the typed column used by new runs.
        client.execute("alter table mootdx_xdxr_symbol_runs rename column raw_columns to raw_columns_json")
    client.execute("alter table mootdx_xdxr_symbol_runs add column if not exists raw_columns Array(String) default []")
    client.execute("alter table mootdx_xdxr_symbol_runs modify ttl requested_at + interval 365 day delete")


def _first_clickhouse_value(rows: Any) -> str | None:
    if not rows:
        return None
    first = rows[0]
    if isinstance(first, dict):
        return str(first.get("type") or "") or None
    if isinstance(first, (tuple, list)) and first:
        return str(first[0])
    return str(first)


def _ensure_mootdx_catalog_lifecycle_columns(client: Any) -> None:
    for column_sql in (
        "is_active UInt8 default 1",
        "missing_catalog_runs UInt8 default 0",
        "last_seen_at Nullable(DateTime)",
        "deactivated_at Nullable(DateTime)",
        "reactivated_at Nullable(DateTime)",
    ):
        client.execute(f"alter table mootdx_stock_catalog add column if not exists {column_sql}")


def _optimize_stock_kline_partitions(client: Any, rows: list[tuple]) -> None:
    partitions = sorted({(row[1], row[2]) for row in rows})
    for trade_date, frequency in partitions:
        client.execute(f"optimize table mootdx_stock_kline partition ('{trade_date.isoformat()}','{frequency}') final")


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


def _progress(progress: ProgressCallback | None, percent: int, stage: str, message: str, **extra: Any) -> None:
    if progress is not None:
        progress(percent, stage, message, **extra)


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


def _nullable_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
    create table if not exists mootdx_ingestion_runs (
        ingest_seq UInt64,
        run_id String,
        task_key LowCardinality(String),
        started_at DateTime,
        finished_at Nullable(DateTime),
        status LowCardinality(String),
        row_count UInt64,
        error String,
        version UInt8
    )
    engine = ReplacingMergeTree(version)
    order by ingest_seq
    """,
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
        is_active UInt8 default 1,
        missing_catalog_runs UInt8 default 0,
        last_seen_at Nullable(DateTime),
        deactivated_at Nullable(DateTime),
        reactivated_at Nullable(DateTime),
        source LowCardinality(String),
        raw_json String
    )
    engine = ReplacingMergeTree(captured_at)
    partition by tuple()
    order by (symbol)
    ttl captured_at + interval 365 day delete
    """,
    """
    create table if not exists mootdx_catalog_change_events (
        event_at DateTime,
        symbol String,
        event_type LowCardinality(String),
        previous_json String,
        current_json String,
        run_id String,
        source LowCardinality(String)
    )
    engine = MergeTree
    partition by toYYYYMM(event_at)
    order by (event_at, symbol, event_type, run_id)
    ttl event_at + interval 1095 day delete
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
        raw_json String,
        ingest_seq UInt64 default 0
    )
    engine = ReplacingMergeTree(ingested_at)
    partition by (trade_date, frequency)
    order by (frequency, symbol, datetime)
    ttl trade_date + interval 1095 day delete
    """,
    """
    create table if not exists mootdx_symbol_data_status (
        symbol String,
        data_kind LowCardinality(String),
        status LowCardinality(String),
        reason LowCardinality(String),
        first_seen_at DateTime,
        last_checked_at DateTime,
        consecutive_failures UInt16,
        last_success_at Nullable(DateTime),
        source LowCardinality(String),
        raw_json String
    )
    engine = ReplacingMergeTree(last_checked_at)
    partition by data_kind
    order by (data_kind, symbol)
    ttl last_checked_at + interval 365 day delete
    """,
    """
    create table if not exists mootdx_daily_gap_verifications (
        verified_at DateTime,
        run_id String,
        symbol String,
        frequency LowCardinality(String),
        trade_date Date,
        verdict LowCardinality(String),
        source LowCardinality(String),
        details_json String
    )
    engine = ReplacingMergeTree(verified_at)
    partition by toYYYYMM(trade_date)
    order by (frequency, symbol, trade_date)
    ttl verified_at + interval 1095 day delete
    """,
    """
    create table if not exists stock_universe_profiles (
        symbol String,
        as_of_date Date,
        computed_at DateTime,
        rule_version UInt32,
        market LowCardinality(String),
        is_st UInt8,
        list_date Nullable(Date),
        listing_age_days UInt32,
        catalog_valid UInt8,
        latest_daily_valid UInt8,
        recent_20d_bar_count UInt16,
        recent_20d_trading_days UInt16,
        recent_20d_avg_amount Float64,
        recent_20d_median_amount Float64,
        recent_20d_zero_volume_days UInt16,
        liquidity_qualified UInt8,
        liquidity_level LowCardinality(String),
        universe_eligible UInt8,
        exclusion_reasons Array(LowCardinality(String))
    )
    engine = ReplacingMergeTree(computed_at)
    order by symbol
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
        fenhong Nullable(Float64),
        peigujia Nullable(Float64),
        songzhuangu Nullable(Float64),
        peigu Nullable(Float64),
        suogu Nullable(Float64),
        panqianliutong Nullable(Float64),
        panhouliutong Nullable(Float64),
        qianzongguben Nullable(Float64),
        houzongguben Nullable(Float64),
        ingested_at DateTime,
        raw_json String,
        ingest_seq UInt64 default 0
    )
    engine = ReplacingMergeTree(ingested_at)
    partition by toYYYYMM(event_date)
    order by (symbol, event_date, category)
    """,
    """
    create table if not exists mootdx_xdxr_event_versions (
        ingest_seq UInt64,
        symbol String,
        event_date Date,
        category Int16,
        name String,
        fenhong Nullable(Float64),
        peigujia Nullable(Float64),
        songzhuangu Nullable(Float64),
        peigu Nullable(Float64),
        suogu Nullable(Float64),
        panqianliutong Nullable(Float64),
        panhouliutong Nullable(Float64),
        qianzongguben Nullable(Float64),
        houzongguben Nullable(Float64),
        content_hash String,
        raw_json String,
        observed_at DateTime,
        migration_baseline UInt8 default 0
    )
    engine = MergeTree
    partition by toYYYYMM(event_date)
    order by (symbol, event_date, category, ingest_seq)
    """,
    """
    create table if not exists mootdx_xdxr_symbol_observations (
        ingest_seq UInt64,
        symbol String,
        observed_at DateTime,
        status LowCardinality(String),
        event_count UInt32,
        event_set_hash String,
        request_ms Nullable(Float64),
        parse_ms Nullable(Float64),
        error String
    )
    engine = MergeTree
    partition by toYYYYMM(observed_at)
    order by (symbol, ingest_seq)
    """,
    """
    create table if not exists mootdx_xdxr_symbol_runs (
        run_id String,
        symbol String,
        requested_at DateTime,
        status LowCardinality(String),
        event_rows UInt32,
        request_ms Nullable(Float64),
        parse_ms Nullable(Float64),
        error String,
        raw_columns Array(String)
    )
    engine = ReplacingMergeTree(requested_at)
    order by (run_id, symbol)
    ttl requested_at + interval 365 day delete
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


MOOTDX_XDXR_CURRENT_VIEW_SQL = """
create view if not exists mootdx_xdxr_current as
select
    symbol,
    event_date,
    category,
    tupleElement(event_version, 6) as name,
    tupleElement(event_version, 1) as fenhong,
    tupleElement(event_version, 2) as peigujia,
    tupleElement(event_version, 3) as songzhuangu,
    tupleElement(event_version, 4) as peigu,
    tupleElement(event_version, 5) as suogu,
    tupleElement(event_version, 7) as panqianliutong,
    tupleElement(event_version, 8) as panhouliutong,
    tupleElement(event_version, 9) as qianzongguben,
    tupleElement(event_version, 10) as houzongguben,
    tupleElement(event_version, 11) as content_hash,
    tupleElement(event_version, 12) as raw_json,
    tupleElement(event_version, 13) as observed_at,
    tupleElement(event_version, 14) as ingest_seq
from (
    select
        version.symbol as symbol,
        version.event_date as event_date,
        version.category as category,
        argMax(
            tuple(
                version.fenhong, version.peigujia, version.songzhuangu, version.peigu, version.suogu,
                version.name, version.panqianliutong, version.panhouliutong,
                version.qianzongguben, version.houzongguben, version.content_hash,
                version.raw_json, version.observed_at, version.ingest_seq
            ),
            version.ingest_seq
        ) as event_version
    from mootdx_xdxr_event_versions as version
    inner join (
        select ingest_seq from mootdx_ingestion_runs final where status = 'succeeded'
    ) as ingestion on version.ingest_seq = ingestion.ingest_seq
    group by version.symbol, version.event_date, version.category
)
"""

MOOTDX_XDXR_NULLABLE_FLOAT_COLUMNS = (
    "fenhong",
    "peigujia",
    "songzhuangu",
    "peigu",
    "suogu",
    "panqianliutong",
    "panhouliutong",
    "qianzongguben",
    "houzongguben",
)

MOOTDX_DAILY_XDXR_EVENTS_VIEW_SQL = """
create view if not exists mootdx_daily_xdxr_events_view as
select
    k.datetime,
    k.trade_date,
    k.frequency,
    k.symbol,
    k.open,
    k.high,
    k.low,
    k.close,
    k.volume,
    k.amount,
    k.source,
    k.ingested_at,
    if(ifNull(e.event_count, 0) > 0, 1, 0) as has_xdxr_event,
    ifNull(e.event_count, 0) as xdxr_event_count,
    ifNull(e.price_adjustment_event_count, 0) as price_adjustment_event_count,
    if(ifNull(e.price_adjustment_event_count, 0) > 0, 1, 0) as has_price_adjustment_event,
    ifNull(e.event_categories, []) as event_categories,
    ifNull(e.event_names, []) as event_names,
    ifNull(e.fenhong_sum, 0.0) as fenhong_sum,
    ifNull(e.songzhuangu_sum, 0.0) as songzhuangu_sum,
    ifNull(e.peigu_sum, 0.0) as peigu_sum
from
    (select * from mootdx_stock_kline final where frequency = 'daily') as k
left join
    (
        select
            symbol,
            event_date,
            count() as event_count,
            countIf(category = 1) as price_adjustment_event_count,
            groupUniqArray(category) as event_categories,
            groupUniqArray(name) as event_names,
            sum(ifNull(fenhong, 0.0)) as fenhong_sum,
            sum(ifNull(songzhuangu, 0.0)) as songzhuangu_sum,
            sum(ifNull(peigu, 0.0)) as peigu_sum
        from mootdx_xdxr final
        group by symbol, event_date
    ) as e
on k.symbol = e.symbol and k.trade_date = e.event_date
"""
