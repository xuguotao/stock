"""Service layer for stock data readiness APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.data.stock_data_readiness import AUTO_REPAIR_DIMENSIONS, evaluate_window_coverage

VALID_DIMENSIONS = ("daily", "minute5", "snapshot", "xdxr")
VALID_STATUSES = {"all", "ready", "partial", "repairable", "unrepairable", "no_data", "snapshot_insufficient"}
STATUS_BUCKETS = ("ready", "partial", "repairable", "unrepairable", "no_data", "snapshot_insufficient")


def build_readiness_summary(
    client: Any,
    *,
    start: date,
    end: date,
    dimensions: list[str],
) -> dict[str, Any]:
    selected_dimensions = _normalize_dimensions(dimensions)
    items = _build_readiness_items(
        client,
        start=start,
        end=end,
        dimensions=selected_dimensions,
    )
    summary = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_symbols": len(items),
        "dimensions": {
            dimension: {status: 0 for status in STATUS_BUCKETS}
            for dimension in selected_dimensions
        },
        "query_trade_days": _trade_day_count(client, start=start, end=end),
    }
    for item in items:
        for dimension in selected_dimensions:
            status = item["dimensions"].get(dimension, {}).get("status", "no_data")
            summary["dimensions"][dimension][status] = summary["dimensions"][dimension].get(status, 0) + 1
    return summary


def query_readiness(
    client: Any,
    *,
    start: date,
    end: date,
    dimensions: list[str],
    status: str = "all",
    market: str = "all",
    board: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    selected_dimensions = _normalize_dimensions(dimensions)
    selected_status = status if status in VALID_STATUSES else "all"
    items = _build_readiness_items(
        client,
        start=start,
        end=end,
        dimensions=selected_dimensions,
        status=selected_status,
        market=market,
        board=board,
        q=q,
    )

    page = max(1, int(page))
    page_size = max(1, min(500, int(page_size)))
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dimensions": selected_dimensions,
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "items": items[start_index:end_index],
    }


def _build_readiness_items(
    client: Any,
    *,
    start: date,
    end: date,
    dimensions: list[str],
    status: str = "all",
    market: str = "all",
    board: str = "all",
    q: str = "",
) -> list[dict[str, Any]]:
    selected_status = status if status in VALID_STATUSES else "all"
    trade_dates = _fetch_trade_dates(client, start=start, end=end)
    summary_rows = _fetch_summary_rows(client, dimensions=dimensions)
    gap_rows = _fetch_gap_rows(client, start=start, end=end, dimensions=dimensions)
    gaps_by_symbol_dimension = _group_gaps(gap_rows)

    items: list[dict[str, Any]] = []
    for symbol, stock_rows in _group_summary_rows(summary_rows).items():
        base = stock_rows[0]
        item = {
            "symbol": symbol,
            "name": base["name"],
            "market": base["market"],
            "board": base["board"],
            "dimensions": {},
        }
        if market != "all" and item["market"] != market:
            continue
        if board != "all" and item["board"] != board:
            continue
        if q and q not in item["symbol"] and q not in item["name"]:
            continue

        dimension_statuses: list[str] = []
        for dimension in dimensions:
            row = next((candidate for candidate in stock_rows if candidate["dimension"] == dimension), None)
            gap_dates = gaps_by_symbol_dimension.get((symbol, dimension), [])
            data_dates = set(trade_dates) - {gap["trade_date"] for gap in gap_dates}
            attempts = max([gap["repair_attempts"] for gap in gap_dates] + [int(row["repair_attempts"]) if row else 0])
            coverage = _evaluate_row_coverage(row, trade_dates=trade_dates, data_dates=data_dates, attempts=attempts, dimension=dimension)
            coverage.update({
                "first_date": _iso_or_none(row["first_date"] if row else None),
                "latest_date": _iso_or_none(row["latest_date"] if row else None),
                "repair_attempts": attempts,
                "checked_days": int(row["checked_days"]) if row else 0,
                "query_trade_days": len(trade_dates),
            })
            item["dimensions"][dimension] = coverage
            dimension_statuses.append(str(coverage["status"]))
        include = selected_status == "all" or all(value == selected_status for value in dimension_statuses)
        if include:
            items.append(item)
    return items


def _evaluate_row_coverage(
    row: dict[str, Any] | None,
    *,
    trade_dates: list[date],
    data_dates: set[date],
    attempts: int,
    dimension: str,
) -> dict[str, Any]:
    if row and int(row["checked_days"]) < len(trade_dates):
        checked_days = int(row["checked_days"])
        covered_days = min(int(row["covered_days"]), checked_days)
        expected_days = len(trade_dates)
        missing_days = max(0, expected_days - covered_days)
        return {
            "status": "snapshot_insufficient",
            "coverage_ratio": covered_days / expected_days if expected_days else 0,
            "covered_days": covered_days,
            "expected_days": expected_days,
            "missing_days": missing_days,
            "missing_samples": [],
            "repairable": False,
        }
    return evaluate_window_coverage(
        trade_dates=trade_dates,
        data_dates=data_dates if row else set(),
        repair_attempts=attempts,
        repair_supported=dimension in AUTO_REPAIR_DIMENSIONS,
    )


def parse_dimensions(value: str | None) -> list[str]:
    if not value:
        return ["daily", "minute5"]
    return _normalize_dimensions([item.strip() for item in value.split(",") if item.strip()])


def _normalize_dimensions(dimensions: list[str]) -> list[str]:
    selected = [dimension for dimension in dimensions if dimension in VALID_DIMENSIONS]
    return selected or ["daily", "minute5"]


def _fetch_trade_dates(client: Any, *, start: date, end: date) -> list[date]:
    rows = client.execute(
        """
        SELECT date FROM trade_calendar
        WHERE date >= %(start)s AND date <= %(end)s
        ORDER BY date
        """,
        {"start": start, "end": end},
    )
    return [_as_date(row[0]) for row in rows]


def _trade_day_count(client: Any, *, start: date, end: date) -> int:
    return len(_fetch_trade_dates(client, start=start, end=end))


def _fetch_summary_rows(client: Any, *, dimensions: list[str]) -> list[dict[str, Any]]:
    rows = client.execute(
        """
        SELECT symbol, name, market, board, dimension,
               window_start, window_end, query_trade_days,
               first_date, latest_date, covered_days, missing_days, checked_days,
               status, repair_supported, repair_attempts,
               last_repair_error
        FROM stock_data_readiness FINAL
        WHERE dimension IN %(dimensions)s
        ORDER BY symbol, dimension
        """,
        {"dimensions": tuple(dimensions)},
    )
    return [
        {
            "symbol": str(row[0]),
            "name": str(row[1]),
            "market": str(row[2]),
            "board": str(row[3]),
            "dimension": str(row[4]),
            "window_start": row[5],
            "window_end": row[6],
            "query_trade_days": int(row[7] or 0),
            "first_date": row[8],
            "latest_date": row[9],
            "covered_days": int(row[10] or 0),
            "missing_days": int(row[11] or 0),
            "checked_days": int(row[12] or 0),
            "status": str(row[13] or ""),
            "repair_supported": bool(row[14]),
            "repair_attempts": int(row[15] or 0),
            "last_repair_error": str(row[16] or ""),
        }
        for row in rows
    ]


def _fetch_gap_rows(client: Any, *, start: date, end: date, dimensions: list[str]) -> list[dict[str, Any]]:
    rows = client.execute(
        """
        SELECT symbol, dimension, trade_date, reason, repair_attempts,
               last_repair_error
        FROM stock_data_readiness_gaps FINAL
        WHERE trade_date >= %(start)s
          AND trade_date <= %(end)s
          AND dimension IN %(dimensions)s
        ORDER BY symbol, dimension, trade_date
        """,
        {"start": start, "end": end, "dimensions": tuple(dimensions)},
    )
    return [
        {
            "symbol": str(row[0]),
            "dimension": str(row[1]),
            "trade_date": _as_date(row[2]),
            "reason": str(row[3]),
            "repair_attempts": int(row[4] or 0),
            "last_repair_error": str(row[5] or ""),
        }
        for row in rows
    ]


def _group_summary_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["symbol"], []).append(row)
    return grouped


def _group_gaps(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["symbol"], row["dimension"]), []).append(row)
    return grouped


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _iso_or_none(value: Any) -> str | None:
    return _as_date(value).isoformat() if value else None
