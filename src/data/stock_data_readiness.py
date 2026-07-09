"""Stock data readiness computation and persistence helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable

READINESS_DIMENSIONS = {"daily", "minute5", "snapshot", "xdxr"}
AUTO_REPAIR_DIMENSIONS = {"daily", "minute5"}


def run_readiness_snapshot(params: dict[str, Any]) -> dict[str, Any]:
    """Compute and persist readiness snapshot for the configured lookback window."""
    client = params.get("client") or _default_client()
    progress = params.get("progress")
    explicit_start = params.get("start")
    explicit_end = params.get("end")
    as_of = _parse_date(explicit_end or params.get("as_of") or params.get("trade_date") or date.today())
    lookback_days = int(params.get("lookback_days") or 260)
    dimensions = [dimension for dimension in params.get("dimensions", ["daily", "minute5", "snapshot", "xdxr"]) if dimension in READINESS_DIMENSIONS]
    start = _parse_date(explicit_start) if explicit_start else as_of - timedelta(days=lookback_days * 2)

    if callable(progress):
        progress(10, "table", "创建策略数据就绪度表")
    ensure_readiness_table(client)

    if callable(progress):
        progress(20, "pool", "计算策略股票池")
    pool = compute_initial_pool(client, as_of=as_of)
    requested_symbols = _normalize_repair_symbols(params.get("symbols") or [])
    if requested_symbols:
        requested_set = set(requested_symbols)
        pool = [stock for stock in pool if stock["symbol"] in requested_set]
    limit = int(params.get("limit") or 0)
    if limit > 0:
        pool = pool[:limit]
    trade_dates = _fetch_trade_dates(client, start=start, end=as_of)
    if not explicit_start:
        trade_dates = trade_dates[-lookback_days:]
    if trade_dates:
        window_start = trade_dates[0]
        window_end = trade_dates[-1]
    else:
        window_start = start
        window_end = as_of

    rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    computed_at = datetime.now().replace(microsecond=0)
    total = len(pool)
    for index, dimension in enumerate(dimensions, start=1):
        dimension_rows, dimension_gaps = compute_dimension_snapshots(
            client,
            stocks=pool,
            dimension=dimension,
            trade_dates=trade_dates,
            computed_at=computed_at,
            window_start=window_start,
            window_end=window_end,
        )
        rows.extend(dimension_rows)
        gap_rows.extend(dimension_gaps)
        if callable(progress):
            progress(20 + int(index / max(1, len(dimensions)) * 70), "computing", f"已计算 {dimension} {total} 只")

    if callable(progress):
        progress(95, "persisting", f"写入 {len(rows)} 条摘要和 {len(gap_rows)} 条缺口")
    persist_readiness_snapshot(client, rows, gap_rows)
    if callable(progress):
        progress(100, "completed", "策略数据就绪度快照完成")
    return {
        "status": "success",
        "total": total,
        "rows": len(rows),
        "gaps": len(gap_rows),
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "as_of": as_of.isoformat(),
    }


def run_readiness_repair(params: dict[str, Any]) -> dict[str, Any]:
    """Run bounded readiness repair task."""
    client = params.get("client") or _default_client()
    progress = params.get("progress")
    start = _parse_date(params.get("start") or params.get("trade_date") or date.today())
    end = _parse_date(params.get("end") or params.get("trade_date") or start)
    if end < start:
        raise ValueError("end must be greater than or equal to start")

    dimensions = [
        dimension
        for dimension in params.get("dimensions", ["daily", "minute5"])
        if dimension in READINESS_DIMENSIONS
    ]
    repair_dimensions = [dimension for dimension in dimensions if dimension in AUTO_REPAIR_DIMENSIONS]
    unsupported_dimensions = [dimension for dimension in dimensions if dimension not in AUTO_REPAIR_DIMENSIONS]
    if not repair_dimensions:
        return {
            "status": "skipped",
            "reason": "no_supported_dimensions",
            "unsupported_dimensions": unsupported_dimensions,
            "attempted_gaps": 0,
        }

    symbols = _normalize_repair_symbols(params.get("symbols") or [])
    gaps = _fetch_repair_gaps(
        client,
        symbols=symbols,
        dimensions=repair_dimensions,
        start=start,
        end=end,
        max_attempts=int(params.get("max_attempts") or 3),
    )
    if not gaps:
        return {
            "status": "success",
            "symbols": len(symbols),
            "dimensions": repair_dimensions,
            "unsupported_dimensions": unsupported_dimensions,
            "attempted_gaps": 0,
            "daily": [],
            "minute5": None,
            "snapshot": None,
        }

    if callable(progress):
        progress(5, "repairing", f"准备回补 {len(gaps)} 个策略数据缺口")

    _record_repair_attempts(client, gaps)
    daily_results: list[dict[str, Any]] = []
    minute5_result: dict[str, Any] | None = None
    errors: list[dict[str, str]] = []
    daily_runner = params.get("daily_repair_runner") or _default_daily_repair_runner()
    minute5_runner = params.get("minute5_history_runner") or _default_minute5_history_runner()

    grouped: dict[str, dict[date, set[str]]] = defaultdict(lambda: defaultdict(set))
    for gap in gaps:
        grouped[gap["dimension"]][gap["trade_date"]].add(gap["symbol"])

    if "daily" in grouped:
        for trade_date in sorted(grouped["daily"]):
            try:
                daily_results.append(daily_runner(trade_date=trade_date, client=client))
            except Exception as exc:  # noqa: BLE001 - keep other dimensions repairable.
                errors.append({"dimension": "daily", "trade_date": trade_date.isoformat(), "error": str(exc)})

    if "minute5" in grouped:
        minute5_symbols = sorted({symbol for symbols_for_date in grouped["minute5"].values() for symbol in symbols_for_date})
        try:
            minute5_result = minute5_runner(
                start=min(grouped["minute5"]),
                end=max(grouped["minute5"]),
                symbols=minute5_symbols,
                limit=0,
                include_st=False,
                client=client,
                progress=progress if callable(progress) else None,
            )
        except Exception as exc:  # noqa: BLE001 - report failure without hiding daily results.
            errors.append({"dimension": "minute5", "trade_date": f"{start.isoformat()}..{end.isoformat()}", "error": str(exc)})

    snapshot_result = None
    if bool(params.get("refresh_snapshot", True)) and not errors:
        snapshot_runner = params.get("snapshot_runner") or run_readiness_snapshot
        refresh_symbols = sorted({gap["symbol"] for gap in gaps})
        snapshot_result = snapshot_runner({
            "client": client,
            "as_of": end,
            "lookback_days": max(1, (end - start).days + 1),
            "dimensions": repair_dimensions,
            "symbols": refresh_symbols,
            "progress": progress if callable(progress) else None,
        })

    if callable(progress):
        progress(100, "completed", "策略数据就绪度回补完成")
    return {
        "status": "failed" if errors else "success",
        "symbols": len(symbols) if symbols else len({gap["symbol"] for gap in gaps}),
        "dimensions": repair_dimensions,
        "unsupported_dimensions": unsupported_dimensions,
        "attempted_gaps": len(gaps),
        "daily": daily_results,
        "minute5": minute5_result,
        "snapshot": snapshot_result,
        "errors": errors,
    }


def compute_dimension_snapshot(
    client: Any,
    *,
    stock: dict[str, Any],
    dimension: str,
    trade_dates: list[date],
    computed_at: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute summary and gap rows for one stock/dimension."""
    symbol = stock["symbol"]
    if dimension == "xdxr":
        data_dates = set(trade_dates)
        first_date = trade_dates[0] if trade_dates else None
        latest_date = _latest_dimension_date(client, symbol=symbol, dimension=dimension)
    else:
        data_dates = _fetch_dimension_dates(client, symbol=symbol, dimension=dimension, trade_dates=trade_dates)
        first_date = min(data_dates) if data_dates else None
        latest_date = max(data_dates) if data_dates else None

    coverage = evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates=data_dates,
        repair_attempts=_repair_attempts(client, symbol=symbol, dimension=dimension),
        repair_supported=dimension in AUTO_REPAIR_DIMENSIONS,
    )
    row = {
        "symbol": symbol,
        "name": stock["name"],
        "market": stock["market"],
        "board": stock["board"],
        "dimension": dimension,
        "window_start": trade_dates[0] if trade_dates else None,
        "window_end": trade_dates[-1] if trade_dates else None,
        "query_trade_days": coverage["expected_days"],
        "first_date": first_date,
        "latest_date": latest_date,
        "covered_days": coverage["covered_days"],
        "missing_days": coverage["missing_days"],
        "checked_days": coverage["expected_days"],
        "status": coverage["status"],
        "repair_supported": dimension in AUTO_REPAIR_DIMENSIONS,
        "repair_attempts": _repair_attempts(client, symbol=symbol, dimension=dimension),
        "last_repair_error": "",
        "computed_at": computed_at,
    }
    gap_rows = [
        {
            "symbol": symbol,
            "dimension": dimension,
            "trade_date": missing_date,
            "reason": f"missing_{dimension}",
            "repair_attempts": row["repair_attempts"],
            "last_repair_error": "",
            "computed_at": computed_at,
        }
        for missing_date in trade_dates
        if missing_date not in data_dates
    ]
    return row, gap_rows


def compute_dimension_snapshots(
    client: Any,
    *,
    stocks: list[dict[str, Any]],
    dimension: str,
    trade_dates: list[date],
    computed_at: datetime | str,
    window_start: date | None = None,
    window_end: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute summary and gap rows for one dimension across a stock batch."""
    if not stocks:
        return [], []
    symbols = [stock["symbol"] for stock in stocks]
    data_by_symbol = _fetch_dimension_dates_by_symbol(
        client,
        symbols=symbols,
        dimension=dimension,
        trade_dates=trade_dates,
    )
    attempts_by_symbol = _repair_attempts_by_symbol(client, symbols=symbols, dimension=dimension)

    rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    for stock in stocks:
        symbol = stock["symbol"]
        data_dates = data_by_symbol.get(symbol, set())
        first_date = min(data_dates) if data_dates else None
        latest_date = max(data_dates) if data_dates else None
        attempts = attempts_by_symbol.get(symbol, 0)
        coverage = evaluate_window_coverage(
            trade_dates=trade_dates,
            data_dates=data_dates,
            repair_attempts=attempts,
            repair_supported=dimension in AUTO_REPAIR_DIMENSIONS,
        )
        row = {
            "symbol": symbol,
            "name": stock["name"],
            "market": stock["market"],
            "board": stock["board"],
            "dimension": dimension,
            "window_start": window_start or (trade_dates[0] if trade_dates else None),
            "window_end": window_end or (trade_dates[-1] if trade_dates else None),
            "query_trade_days": coverage["expected_days"],
            "first_date": first_date,
            "latest_date": latest_date,
            "covered_days": coverage["covered_days"],
            "missing_days": coverage["missing_days"],
            "checked_days": coverage["expected_days"],
            "status": coverage["status"],
            "repair_supported": dimension in AUTO_REPAIR_DIMENSIONS,
            "repair_attempts": attempts,
            "last_repair_error": "",
            "computed_at": computed_at,
        }
        rows.append(row)
        gap_rows.extend(
            {
                "symbol": symbol,
                "dimension": dimension,
                "trade_date": missing_date,
                "reason": f"missing_{dimension}",
                "repair_attempts": attempts,
                "last_repair_error": "",
                "computed_at": computed_at,
            }
            for missing_date in trade_dates
            if missing_date not in data_dates
        )
    return rows, gap_rows


def compute_initial_pool(client: Any, *, as_of: date) -> list[dict[str, Any]]:
    """Return SH/SZ non-ST stocks listed for at least 60 days."""
    rows = client.execute(
        """
        SELECT symbol, name, market, list_date
        FROM stocks FINAL
        WHERE market IN ('SH', 'SZ')
          AND name != ''
          AND list_date != ''
        ORDER BY symbol
        """
    )
    pool: list[dict[str, Any]] = []
    for symbol_value, name_value, market_value, list_date_value in rows:
        symbol = str(symbol_value).zfill(6)
        name = str(name_value)
        market = str(market_value).upper()
        if market not in {"SH", "SZ"}:
            continue
        if _is_excluded_name(name):
            continue
        try:
            list_date = _parse_date(list_date_value)
        except (TypeError, ValueError):
            continue
        if (as_of - list_date).days < 60:
            continue
        pool.append({
            "symbol": symbol,
            "name": name,
            "market": market,
            "board": board_from_symbol(symbol, market),
            "list_date": list_date,
        })
    return pool


def evaluate_window_coverage(
    *,
    trade_dates: list[date],
    data_dates: set[date],
    repair_attempts: int,
    repair_supported: bool = True,
) -> dict[str, Any]:
    """Evaluate one dimension's coverage in a query window."""
    expected_days = len(trade_dates)
    covered_days = sum(1 for trade_date in trade_dates if trade_date in data_dates)
    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in data_dates]
    missing_days = expected_days - covered_days
    coverage_ratio = covered_days / expected_days if expected_days else 0

    if missing_days == 0 and expected_days > 0:
        status = "ready"
    elif covered_days == 0:
        status = "no_data"
    elif repair_attempts >= 3:
        status = "unrepairable"
    elif repair_supported:
        status = "repairable"
    else:
        status = "partial"

    return {
        "status": status,
        "coverage_ratio": coverage_ratio,
        "covered_days": covered_days,
        "expected_days": expected_days,
        "missing_days": missing_days,
        "missing_samples": [value.isoformat() for value in missing_dates[:5]],
        "repairable": status == "repairable",
    }


def ensure_readiness_table(client: Any) -> None:
    """Create stock readiness summary and gap tables."""
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_data_readiness
        (
            symbol String,
            name String,
            market LowCardinality(String),
            board LowCardinality(String),
            dimension LowCardinality(String),
            window_start Nullable(Date),
            window_end Nullable(Date),
            query_trade_days UInt32,
            first_date Nullable(Date),
            latest_date Nullable(Date),
            covered_days UInt32,
            missing_days UInt32,
            checked_days UInt32,
            status LowCardinality(String),
            repair_supported UInt8,
            repair_attempts UInt8,
            last_repair_error String,
            computed_at DateTime
        )
        ENGINE = ReplacingMergeTree(computed_at)
        ORDER BY (symbol, dimension)
        """
    )
    client.execute("ALTER TABLE stock_data_readiness ADD COLUMN IF NOT EXISTS window_start Nullable(Date) AFTER dimension")
    client.execute("ALTER TABLE stock_data_readiness ADD COLUMN IF NOT EXISTS window_end Nullable(Date) AFTER window_start")
    client.execute("ALTER TABLE stock_data_readiness ADD COLUMN IF NOT EXISTS query_trade_days UInt32 AFTER window_end")
    client.execute("ALTER TABLE stock_data_readiness ADD COLUMN IF NOT EXISTS status LowCardinality(String) AFTER checked_days")
    client.execute("ALTER TABLE stock_data_readiness ADD COLUMN IF NOT EXISTS repair_supported UInt8 AFTER status")
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_data_readiness_gaps
        (
            symbol String,
            dimension LowCardinality(String),
            trade_date Date,
            reason LowCardinality(String),
            repair_attempts UInt8,
            last_repair_error String,
            computed_at DateTime
        )
        ENGINE = ReplacingMergeTree(computed_at)
        ORDER BY (dimension, trade_date, symbol)
        """
    )


def persist_readiness_snapshot(
    client: Any,
    rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
) -> None:
    """Persist summary and gap rows with batch inserts."""
    dimensions = tuple(sorted({str(row["dimension"]) for row in rows}))
    symbols = tuple(sorted({str(row["symbol"]) for row in rows}))
    if dimensions and symbols:
        client.execute(
            "ALTER TABLE stock_data_readiness_gaps DELETE WHERE dimension IN %(dimensions)s AND symbol IN %(symbols)s",
            {"dimensions": dimensions, "symbols": symbols},
        )
    if rows:
        client.execute(
            """
            INSERT INTO stock_data_readiness
            (symbol, name, market, board, dimension,
             window_start, window_end, query_trade_days,
             first_date, latest_date, covered_days, missing_days, checked_days,
             status, repair_supported, repair_attempts,
             last_repair_error, computed_at)
            VALUES
            """,
            [
                (
                    row["symbol"],
                    row["name"],
                    row["market"],
                    row["board"],
                    row["dimension"],
                    row.get("window_start"),
                    row.get("window_end"),
                    int(row.get("query_trade_days", row.get("checked_days", 0))),
                    row.get("first_date"),
                    row.get("latest_date"),
                    int(row.get("covered_days", 0)),
                    int(row.get("missing_days", 0)),
                    int(row.get("checked_days", 0)),
                    str(row.get("status", "")),
                    int(bool(row.get("repair_supported", False))),
                    int(row.get("repair_attempts", 0)),
                    str(row.get("last_repair_error", "")),
                    row["computed_at"],
                )
                for row in rows
            ],
        )
    if gap_rows:
        client.execute(
            """
            INSERT INTO stock_data_readiness_gaps
            (symbol, dimension, trade_date, reason, repair_attempts,
             last_repair_error, computed_at)
            VALUES
            """,
            [
                (
                    row["symbol"],
                    row["dimension"],
                    row["trade_date"],
                    row["reason"],
                    int(row.get("repair_attempts", 0)),
                    str(row.get("last_repair_error", "")),
                    row["computed_at"],
                )
                for row in gap_rows
            ],
        )


def board_from_symbol(symbol: str, market: str) -> str:
    if market == "SH" and symbol.startswith("688"):
        return "STAR"
    if market == "SZ" and symbol.startswith("300"):
        return "CHINEXT"
    return "MAIN"


def _default_client() -> Any:
    from src.data.clickhouse_source import ClickHouseStockDataSource

    return ClickHouseStockDataSource()._client_instance()


def _default_daily_repair_runner() -> Callable[..., dict[str, Any]]:
    from src.data.clickhouse_daily_sync import sync_clickhouse_daily_from_minute5

    return sync_clickhouse_daily_from_minute5


def _default_minute5_history_runner() -> Callable[..., dict[str, Any]]:
    from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_history_window

    return sync_clickhouse_minute5_history_window


def _fetch_trade_dates(client: Any, *, start: date, end: date) -> list[date]:
    rows = client.execute(
        """
        SELECT date FROM trade_calendar
        WHERE date >= %(start)s AND date <= %(end)s
        ORDER BY date
        """,
        {"start": start, "end": end},
    )
    return [_parse_date(row[0]) for row in rows]


def _fetch_dimension_dates(client: Any, *, symbol: str, dimension: str, trade_dates: list[date]) -> set[date]:
    if not trade_dates:
        return set()
    date_expr = _dimension_date_expr(dimension)
    table = _dimension_table(dimension)
    rows = client.execute(
        f"""
        SELECT DISTINCT {date_expr} AS data_date
        FROM {table}
        WHERE symbol = %(symbol)s
          AND {date_expr} >= %(start)s
          AND {date_expr} <= %(end)s
        ORDER BY data_date
        """,
        {"symbol": symbol, "start": trade_dates[0], "end": trade_dates[-1]},
    )
    return {_parse_date(row[0]) for row in rows if row and row[0]}


def _fetch_dimension_dates_by_symbol(
    client: Any,
    *,
    symbols: list[str],
    dimension: str,
    trade_dates: list[date],
) -> dict[str, set[date]]:
    if not symbols or not trade_dates:
        return {}
    date_expr = _dimension_date_expr(dimension)
    table = _dimension_table(dimension)
    rows = client.execute(
        f"""
        SELECT symbol,
               groupUniqArray({date_expr}) AS data_dates,
               min({date_expr}) AS first_date,
               max({date_expr}) AS latest_date
        FROM {table}
        WHERE symbol IN %(symbols)s
          AND {date_expr} >= %(start)s
          AND {date_expr} <= %(end)s
        GROUP BY symbol
        ORDER BY symbol
        """,
        {"symbols": tuple(symbols), "start": trade_dates[0], "end": trade_dates[-1]},
    )
    result: dict[str, set[date]] = {}
    for symbol, data_dates, _first_date, _latest_date in rows:
        result[str(symbol).zfill(6)] = {_parse_date(value) for value in data_dates if value}
    return result


def _latest_dimension_date(client: Any, *, symbol: str, dimension: str) -> date | None:
    date_expr = _dimension_date_expr(dimension)
    table = _dimension_table(dimension)
    rows = client.execute(
        f"SELECT max({date_expr}) FROM {table} WHERE symbol = %(symbol)s",
        {"symbol": symbol},
    )
    if not rows or not rows[0][0]:
        return None
    return _parse_date(rows[0][0])


def _repair_attempts(client: Any, *, symbol: str, dimension: str) -> int:
    try:
        rows = client.execute(
            """
            SELECT max(repair_attempts)
            FROM stock_data_readiness_gaps FINAL
            WHERE symbol = %(symbol)s AND dimension = %(dimension)s
            """,
            {"symbol": symbol, "dimension": dimension},
        )
    except Exception:  # noqa: BLE001 - table may not exist before first snapshot.
        return 0
    if not rows or rows[0][0] is None:
        return 0
    return int(rows[0][0])


def _repair_attempts_by_symbol(client: Any, *, symbols: list[str], dimension: str) -> dict[str, int]:
    if not symbols:
        return {}
    try:
        rows = client.execute(
            """
            SELECT symbol, max(repair_attempts)
            FROM stock_data_readiness_gaps FINAL
            WHERE symbol IN %(symbols)s AND dimension = %(dimension)s
            GROUP BY symbol
            """,
            {"symbols": tuple(symbols), "dimension": dimension},
        )
    except Exception:  # noqa: BLE001 - table may not exist before first snapshot.
        return {}
    return {str(symbol).zfill(6): int(attempts or 0) for symbol, attempts in rows}


def _fetch_repair_gaps(
    client: Any,
    *,
    symbols: list[str],
    dimensions: list[str],
    start: date,
    end: date,
    max_attempts: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "dimensions": tuple(dimensions),
        "start": start,
        "end": end,
        "max_attempts": max_attempts,
    }
    symbol_filter = ""
    if symbols:
        params["symbols"] = tuple(symbols)
        symbol_filter = "AND symbol IN %(symbols)s"
    rows = client.execute(
        f"""
        SELECT symbol, dimension, trade_date, repair_attempts
        FROM (
            SELECT symbol, dimension, trade_date, max(repair_attempts) AS repair_attempts
            FROM stock_data_readiness_gaps FINAL
            WHERE dimension IN %(dimensions)s
              AND trade_date >= %(start)s
              AND trade_date <= %(end)s
              {symbol_filter}
            GROUP BY symbol, dimension, trade_date
        )
        WHERE repair_attempts < %(max_attempts)s
        ORDER BY dimension, trade_date, symbol
        """,
        params,
    )
    return [
        {
            "symbol": str(symbol).zfill(6),
            "dimension": str(dimension),
            "trade_date": _parse_date(trade_date),
            "repair_attempts": int(repair_attempts or 0),
        }
        for symbol, dimension, trade_date, repair_attempts in rows
    ]


def _record_repair_attempts(client: Any, gaps: list[dict[str, Any]]) -> None:
    if not gaps:
        return
    computed_at = datetime.now().replace(microsecond=0)
    client.execute(
        """
        INSERT INTO stock_data_readiness_gaps
        (symbol, dimension, trade_date, reason, repair_attempts,
         last_repair_error, computed_at)
        VALUES
        """,
        [
            (
                gap["symbol"],
                gap["dimension"],
                gap["trade_date"],
                f"missing_{gap['dimension']}",
                int(gap.get("repair_attempts", 0)) + 1,
                "",
                computed_at,
            )
            for gap in gaps
        ],
    )


def _normalize_repair_symbols(symbols: list[Any]) -> list[str]:
    normalized = []
    for symbol in symbols:
        code = str(symbol).split(".")[0]
        if code:
            normalized.append(code.zfill(6))
    return sorted(set(normalized))


def _dimension_table(dimension: str) -> str:
    if dimension == "daily":
        return "daily_kline"
    if dimension == "minute5":
        return "minute5_kline"
    if dimension == "snapshot":
        return "stock_quote_snapshots"
    if dimension == "xdxr":
        return "xdxr_info"
    raise ValueError(f"unknown readiness dimension: {dimension}")


def _dimension_date_expr(dimension: str) -> str:
    if dimension == "daily":
        return "date"
    if dimension == "minute5":
        return "toDate(datetime)"
    if dimension == "snapshot":
        return "toDate(snapshot_at)"
    if dimension == "xdxr":
        return "toDate(ex_date)"
    raise ValueError(f"unknown readiness dimension: {dimension}")


def _is_excluded_name(name: str) -> bool:
    upper = name.upper()
    return "ST" in upper or name.startswith("退市") or name.endswith("退") or name.endswith("退市")


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
