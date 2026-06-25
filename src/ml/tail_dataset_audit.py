"""Audit ClickHouse readiness for tail-session ML training."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.core.constants import is_st
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.strategy_universe import StrategyUniverseOptions, resolve_strategy_universe


MIN_MINUTE5_USABLE_DAYS = 180
MIN_JOINABLE_LABEL_DAYS = 120
MIN_SIGNAL_OUTCOME_ROWS = 500


def audit_tail_ml_data(*, client: Any | None = None, as_of: date | None = None) -> dict[str, Any]:
    """Return a read-only readiness report for tail-session ML work."""
    clickhouse = client or ClickHouseStockDataSource()._client_instance()
    as_of_date = as_of or date.today()
    stocks = _stock_summary(clickhouse)
    daily = _daily_summary(clickhouse)
    minute5 = _minute5_summary(clickhouse)
    snapshots = _snapshot_summary(clickhouse)
    strategy_signals = _tail_signal_summary(clickhouse)
    labels = _tail_outcome_summary(clickhouse)
    tradable_pool = len(
        resolve_strategy_universe(
            clickhouse,
            StrategyUniverseOptions(
                trade_date=as_of_date,
                min_daily_bars=120,
                require_latest_daily=False,
                require_minute5=False,
                include_st=False,
                min_amount=0,
                markets=("SH", "SZ"),
            ),
            symbols_only=True,
        )
    )

    issues: list[str] = []
    if daily["row_count"] <= 0:
        issues.append("daily_kline_missing")
    if daily["invalid_ohlc_rows"] > 0:
        issues.append(f"daily_kline_invalid_ohlc_{daily['invalid_ohlc_rows']}_rows")
    if minute5["usable_days"] < MIN_MINUTE5_USABLE_DAYS:
        issues.append(f"minute5_history_limited_{minute5['usable_days']}_days")
    label_status = _label_status(labels)
    if label_status == "limited":
        issues.append(f"joinable_label_days_limited_{labels['joinable_days']}")
    elif label_status == "pending_history":
        issues.append(f"label_history_pending_{labels['history_span_days']}_days")
    if labels["outcome_rows"] < MIN_SIGNAL_OUTCOME_ROWS:
        issues.append(f"tail_signal_outcomes_too_sparse_{labels['outcome_rows']}_rows")
    if tradable_pool <= 0:
        issues.append("strategy_tradable_pool_empty")

    daily["status"] = "blocked" if daily["row_count"] <= 0 else "limited" if daily["invalid_ohlc_rows"] > 0 else "ready"
    minute5["status"] = "ready" if minute5["usable_days"] >= MIN_MINUTE5_USABLE_DAYS else "limited"
    labels["status"] = label_status
    snapshots["status"] = "limited"
    strategy_signals["status"] = "ready" if strategy_signals["outcome_rows"] >= MIN_SIGNAL_OUTCOME_ROWS else "limited"
    tradable = {"status": "ready" if tradable_pool > 0 else "blocked", "symbol_count": tradable_pool}
    status = _overall_status([
        daily["status"],
        minute5["status"],
        labels["status"],
        snapshots["status"],
        strategy_signals["status"],
        tradable["status"],
    ])
    return {
        "status": status,
        "as_of": as_of_date.isoformat(),
        "summary": {
            "daily_rows": daily["row_count"],
            "daily_symbols": daily["symbol_count"],
            "minute5_rows": minute5["row_count"],
            "minute5_symbols": minute5["symbol_count"],
            "minute5_usable_days": minute5["usable_days"],
            "joinable_label_days": labels["joinable_days"],
            "tradable_pool": tradable_pool,
        },
        "stocks": stocks,
        "daily": daily,
        "minute5": minute5,
        "snapshots": snapshots,
        "strategy_signals": strategy_signals,
        "labels": labels,
        "tradable_pool": tradable,
        "issues": issues,
    }


def _stock_summary(client: Any) -> dict[str, Any]:
    rows = client.execute("select symbol, name from stocks")
    stock_count = len(rows)
    st_count = sum(1 for row in rows if is_st(str(_value(tuple(row), 1) or "")))
    return {"stock_count": stock_count, "st_count": st_count, "non_st_count": stock_count - st_count}


def _daily_summary(client: Any) -> dict[str, Any]:
    row = _first_row(
        client,
        """
        select min(date), max(date), uniqExact(symbol), count(),
               countIf(open <= 0 or high <= 0 or low <= 0 or close <= 0 or volume <= 0)
        from daily_kline
        """,
    )
    return {
        "start": _date_string(_value(row, 0)),
        "end": _date_string(_value(row, 1)),
        "symbol_count": _int(row, 2),
        "row_count": _int(row, 3),
        "invalid_ohlc_rows": _int(row, 4),
    }


def _minute5_summary(client: Any) -> dict[str, Any]:
    row = _first_row(
        client,
        """
        select min(datetime), max(datetime), uniqExact(symbol), count()
        from minute5_kline
        """,
    )
    usable_days = _single_int(
        client,
        """
        -- minute5_usable_days
        select count()
        from (
            select toDate(datetime) d, uniqExact(symbol) symbols, count() rows
            from minute5_kline
            group by d
            having symbols >= 4500 and rows >= symbols * 40
        )
        """,
    )
    return {
        "start": _datetime_string(_value(row, 0)),
        "end": _datetime_string(_value(row, 1)),
        "symbol_count": _int(row, 2),
        "row_count": _int(row, 3),
        "usable_days": usable_days,
        "minimum_usable_days": MIN_MINUTE5_USABLE_DAYS,
    }


def _snapshot_summary(client: Any) -> dict[str, Any]:
    row = _first_row(
        client,
        """
        select min(snapshot_at), max(snapshot_at), uniqExact(symbol), count()
        from stock_quote_snapshots
        """,
    )
    return {
        "start": _datetime_string(_value(row, 0)),
        "latest_datetime": _datetime_string(_value(row, 1)),
        "symbol_count": _int(row, 2),
        "row_count": _int(row, 3),
        "training_role": "real_time_inference_only",
    }


def _tail_signal_summary(client: Any) -> dict[str, Any]:
    row = _first_row(
        client,
        """
        select min(trade_date), max(trade_date), count(), uniqExact(trade_date), countIf(status='selected'), uniqExact(symbol)
        from tail_selection_signals
        """,
    )
    outcome_rows = _single_int(client, "select count() from tail_signal_outcomes")
    return {
        "start": _date_string(_value(row, 0)),
        "end": _date_string(_value(row, 1)),
        "row_count": _int(row, 2),
        "signal_days": _int(row, 3),
        "selected_rows": _int(row, 4),
        "symbol_count": _int(row, 5),
        "outcome_rows": outcome_rows,
        "training_role": "baseline_only",
    }


def _tail_outcome_summary(client: Any) -> dict[str, Any]:
    row = _first_row(
        client,
        """
        select min(signal_date), max(signal_date), count(), uniqExact(signal_date), uniqExact(symbol)
        from tail_signal_outcomes
        """,
    )
    joinable_days = _single_int(
        client,
        """
        -- joinable_label_days
        select count()
        from (
            select signal_date, countIf(next_date is not null) c
            from (
                select
                    symbol,
                    date as signal_date,
                    leadInFrame(date) over (
                        partition by symbol
                        order by date
                        rows between current row and 1 following
                    ) as next_date
                from daily_kline
                where date >= (select toDate(min(datetime)) from minute5_kline)
                  and date <= today() - 1
                  and open > 0 and high > 0 and low > 0 and close > 0 and volume > 0
            )
            group by signal_date
            having c >= 4500
        )
        """,
    )
    history_span_days = _single_int(
        client,
        """
        -- label_history_span
        select count()
        from (
            select toDate(datetime) d, uniqExact(symbol) symbols, count() rows
            from minute5_kline
            where toDate(datetime) <= today() - 1
            group by d
            having symbols >= 4500 and rows >= symbols * 6
        )
        """,
    )
    return {
        "start": _date_string(_value(row, 0)),
        "end": _date_string(_value(row, 1)),
        "outcome_rows": _int(row, 2),
        "outcome_days": _int(row, 3),
        "symbol_count": _int(row, 4),
        "joinable_days": joinable_days,
        "history_span_days": history_span_days,
        "minimum_joinable_days": MIN_JOINABLE_LABEL_DAYS,
    }


def _label_status(labels: dict[str, Any]) -> str:
    if labels["joinable_days"] >= MIN_JOINABLE_LABEL_DAYS:
        return "ready"
    if labels["joinable_days"] >= labels.get("history_span_days", 0):
        return "pending_history"
    return "limited"


def _first_row(client: Any, query: str) -> tuple[Any, ...]:
    rows = client.execute(query)
    return tuple(rows[0]) if rows else tuple()


def _single_int(client: Any, query: str) -> int:
    row = _first_row(client, query)
    return _int(row, 0)


def _int(row: tuple[Any, ...], index: int) -> int:
    return int(_value(row, index) or 0)


def _value(row: tuple[Any, ...], index: int) -> Any:
    if index >= len(row):
        return None
    return row[index]


def _date_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _datetime_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def _overall_status(statuses: list[str]) -> str:
    if "blocked" in statuses:
        return "blocked"
    if "limited" in statuses:
        return "limited"
    return "ready"
