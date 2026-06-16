"""Persist tail-session signals and next-session outcomes in ClickHouse."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource


class ClickHouseTailSignalRepository:
    """Store tail-session selection signals and computed outcomes."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = ClickHouseStockDataSource()._client_instance()
        return self._client

    def ensure_tables(self) -> None:
        self.client.execute(
            """
            create table if not exists tail_selection_signals (
                job_id String,
                trade_date Date,
                mode String,
                rank UInt32,
                symbol String,
                status String,
                filter_reason String,
                strength Nullable(Float64),
                last_price Nullable(Float64),
                volume_ratio Nullable(Float64),
                tail_return Nullable(Float64),
                v2_score Nullable(Float64),
                v2_layer String,
                v2_action String,
                updated_at DateTime
            )
            engine = ReplacingMergeTree(updated_at)
            partition by toYYYYMM(trade_date)
            order by (trade_date, job_id, symbol, rank)
            """
        )
        self.client.execute(
            """
            create table if not exists tail_signal_outcomes (
                signal_date Date,
                outcome_date Date,
                symbol String,
                signal_close Float64,
                next_open Float64,
                next_close Float64,
                next_high Float64,
                next_low Float64,
                open_return Float64,
                close_return Float64,
                max_return Float64,
                min_return Float64
            )
            engine = ReplacingMergeTree()
            partition by toYYYYMM(signal_date)
            order by (signal_date, symbol)
            """
        )

    def save_selection_result(self, *, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        self.ensure_tables()
        trade_date = date.fromisoformat(str(result["trade_date"]))
        mode = str(result.get("mode") or "")
        updated_at = datetime.combine(trade_date, datetime.min.time())
        rows = [
            _signal_row(job_id=job_id, trade_date=trade_date, mode=mode, updated_at=updated_at, item=item)
            for item in result.get("ranked_signals", []) or []
        ]
        if rows:
            self.client.execute(
                """
                insert into tail_selection_signals
                    (job_id, trade_date, mode, rank, symbol, status, filter_reason,
                     strength, last_price, volume_ratio, tail_return, v2_score, v2_layer, v2_action, updated_at)
                values
                """,
                rows,
            )
        return {
            "trade_date": trade_date.isoformat(),
            "signal_count": len(rows),
            "selected_count": sum(1 for row in rows if row[5] == "selected"),
        }

    def compute_and_save_outcomes(self, *, signal_date: date, symbols: list[str]) -> dict[str, Any]:
        self.ensure_tables()
        rows = []
        missing = []
        for symbol in symbols:
            bars = self.client.execute(
                """
                select symbol, date, open, high, low, close
                from daily_kline
                where symbol = %(symbol)s and date >= %(signal_date)s
                order by date
                limit 2
                """,
                {"symbol": _code(symbol), "signal_date": signal_date},
            )
            if len(bars) < 2:
                missing.append(symbol)
                continue
            rows.append(_outcome_row(bars[0], bars[1]))
        if rows:
            self.client.execute(
                """
                insert into tail_signal_outcomes
                    (signal_date, outcome_date, symbol, signal_close, next_open, next_close,
                     next_high, next_low, open_return, close_return, max_return, min_return)
                values
                """,
                rows,
            )
        return {
            "signal_date": signal_date.isoformat(),
            "outcome_count": len(rows),
            "missing_symbols": missing,
        }

    def signal_stats(self, *, start: date | None = None, end: date | None = None) -> dict[str, Any]:
        self.ensure_tables()
        params = {"start": start or date(1970, 1, 1), "end": end or date(2999, 12, 31)}
        overall_rows = self._overall_rows(params)
        selected_rows = self._overall_rows(params, status="selected")
        recent = self._daily_stats(params, limit=20)
        selected_recent = self._daily_stats(params, limit=20, status="selected")
        return {
            "range": {
                "start": params["start"].isoformat(),
                "end": params["end"].isoformat(),
            },
            "overall": _overall_stats(overall_rows[0] if overall_rows else None),
            "selected_overall": _overall_stats(selected_rows[0] if selected_rows else None),
            "by_status": self._group_stats("s.status", params),
            "by_layer": self._group_stats("s.v2_layer", params),
            "by_filter_reason": self._group_stats("s.filter_reason", params),
            "by_signal_date": self._daily_stats(params),
            "recent": recent,
            "selected_recent": selected_recent,
        }

    def _overall_rows(self, params: dict[str, date], status: str | None = None) -> list[tuple[Any, ...]]:
        status_filter = f"and s.status = '{status}'" if status else ""
        return self.client.execute(
            f"""
            select
                count(),
                countIf(o.close_return > 0),
                avg(o.open_return),
                avg(o.close_return),
                avg(o.max_return),
                avg(o.min_return)
            from tail_selection_signals s
            inner join tail_signal_outcomes o
                on s.trade_date = o.signal_date and s.symbol = o.symbol
            where {_stats_date_filter()}
                {status_filter}
            """,
            params,
        )

    def _group_stats(self, group_expr: str, params: dict[str, date]) -> list[dict[str, Any]]:
        rows = self.client.execute(
            f"""
            select
                {group_expr},
                count(),
                countIf(o.close_return > 0),
                avg(o.open_return),
                avg(o.close_return)
            from tail_selection_signals s
            inner join tail_signal_outcomes o
                on s.trade_date = o.signal_date and s.symbol = o.symbol
            where {_stats_date_filter()}
            group by {group_expr}
            order by count() desc
            """,
            params,
        )
        return [_group_row(row) for row in rows]

    def _daily_stats(
        self,
        params: dict[str, date],
        limit: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        limit_clause = f"limit {int(limit)}" if limit else ""
        status_filter = f"and s.status = '{status}'" if status else ""
        rows = self.client.execute(
            f"""
            select
                s.trade_date,
                count(),
                countIf(o.close_return > 0),
                avg(o.open_return),
                avg(o.close_return)
            from tail_selection_signals s
            inner join tail_signal_outcomes o
                on s.trade_date = o.signal_date and s.symbol = o.symbol
            where {_stats_date_filter()}
                {status_filter}
            group by s.trade_date
            order by s.trade_date desc
            {limit_clause}
            """,
            params,
        )
        return [_daily_row(row) for row in rows]


def _signal_row(
    *,
    job_id: str,
    trade_date: date,
    mode: str,
    updated_at: datetime,
    item: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        job_id,
        trade_date,
        mode,
        int(item.get("rank") or 0),
        _code(str(item.get("symbol") or "")),
        str(item.get("status") or ""),
        str(item.get("filter_reason") or ""),
        _float_or_none(item.get("strength")),
        _float_or_none(item.get("last_price")),
        _float_or_none(item.get("volume_ratio")),
        _float_or_none(item.get("tail_return")),
        _float_or_none(item.get("v2_score")),
        str(item.get("v2_layer") or ""),
        str(item.get("v2_action") or ""),
        updated_at,
    )


def _outcome_row(signal_bar: tuple[Any, ...], next_bar: tuple[Any, ...]) -> tuple[Any, ...]:
    symbol, signal_date, _signal_open, _signal_high, _signal_low, signal_close = signal_bar
    _next_symbol, outcome_date, next_open, next_high, next_low, next_close = next_bar
    signal_close = float(signal_close)
    next_open = float(next_open)
    next_close = float(next_close)
    next_high = float(next_high)
    next_low = float(next_low)
    return (
        signal_date,
        outcome_date,
        str(symbol).zfill(6),
        signal_close,
        next_open,
        next_close,
        next_high,
        next_low,
        _return(next_open, signal_close),
        _return(next_close, signal_close),
        _return(next_high, signal_close),
        _return(next_low, signal_close),
    )


def _return(value: float, base: float) -> float:
    return (value / base - 1.0) if base else 0.0


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _code(symbol: str) -> str:
    return symbol.split(".")[0].zfill(6)


def _stats_date_filter() -> str:
    return "s.trade_date >= %(start)s and s.trade_date <= %(end)s"


def _overall_stats(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return _stats_row(0, 0, 0, 0, 0, 0)
    return _stats_row(*row)


def _stats_row(
    count: Any,
    win_count: Any,
    avg_open_return: Any,
    avg_close_return: Any,
    avg_max_return: Any,
    avg_min_return: Any,
) -> dict[str, Any]:
    count_value = int(count or 0)
    win_value = int(win_count or 0)
    return {
        "count": count_value,
        "win_count": win_value,
        "win_rate": (win_value / count_value) if count_value else 0.0,
        "avg_open_return": float(avg_open_return or 0),
        "avg_close_return": float(avg_close_return or 0),
        "avg_max_return": float(avg_max_return or 0),
        "avg_min_return": float(avg_min_return or 0),
    }


def _group_row(row: tuple[Any, ...]) -> dict[str, Any]:
    group, count, win_count, avg_open_return, avg_close_return = row
    count_value = int(count or 0)
    win_value = int(win_count or 0)
    return {
        "group": str(group or "未分组"),
        "count": count_value,
        "win_count": win_value,
        "win_rate": (win_value / count_value) if count_value else 0.0,
        "avg_open_return": float(avg_open_return or 0),
        "avg_close_return": float(avg_close_return or 0),
    }


def _daily_row(row: tuple[Any, ...]) -> dict[str, Any]:
    signal_date, count, win_count, avg_open_return, avg_close_return = row
    count_value = int(count or 0)
    win_value = int(win_count or 0)
    return {
        "date": _date_string(signal_date),
        "count": count_value,
        "win_count": win_value,
        "win_rate": (win_value / count_value) if count_value else 0.0,
        "avg_open_return": float(avg_open_return or 0),
        "avg_close_return": float(avg_close_return or 0),
    }


def _date_string(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
