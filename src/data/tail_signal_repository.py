"""Persist tail-session signals and next-session outcomes in ClickHouse."""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite
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
            row = self._minute_outcome_row(signal_date=signal_date, symbol=symbol)
            if row is None:
                row = self._daily_outcome_row(signal_date=signal_date, symbol=symbol)
            if row is None:
                missing.append(symbol)
                continue
            rows.append(row)
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

    def compute_selected_outcomes(self, *, signal_date: date) -> dict[str, Any]:
        rows = self.client.execute(
            """
            select symbol
            from tail_selection_signals
            where trade_date = %(signal_date)s and status = 'selected'
            group by symbol
            order by min(rank), symbol
            """,
            {"signal_date": signal_date},
        )
        return self.compute_and_save_outcomes(
            signal_date=signal_date,
            symbols=[str(row[0]) for row in rows],
        )

    def _minute_outcome_row(self, *, signal_date: date, symbol: str) -> tuple[Any, ...] | None:
        code = _code(symbol)
        signal_rows = self.client.execute(
            """
            select symbol, date, close
            from daily_kline
            where symbol = %(symbol)s and date = %(signal_date)s
            order by date
            limit 1
            """,
            {"symbol": code, "signal_date": signal_date},
        )
        if not signal_rows:
            return None
        signal_symbol, signal_bar_date, signal_close = signal_rows[0]
        minute_rows = self.client.execute(
            """
            select
                symbol,
                toDate(datetime) as outcome_date,
                argMin(open, datetime) as next_open,
                max(high) as next_high,
                min(low) as next_low,
                argMax(close, datetime) as next_close
            from minute5_kline
            where symbol = %(symbol)s and toDate(datetime) > %(signal_date)s
            group by symbol, outcome_date
            order by outcome_date
            limit 1
            """,
            {"symbol": code, "signal_date": signal_date},
        )
        if not minute_rows:
            return None
        _minute_symbol, outcome_date, next_open, next_high, next_low, next_close = minute_rows[0]
        return _outcome_values(
            signal_date=signal_bar_date,
            outcome_date=outcome_date,
            symbol=str(signal_symbol),
            signal_close=float(signal_close),
            next_open=float(next_open),
            next_high=float(next_high),
            next_low=float(next_low),
            next_close=float(next_close),
        )

    def _daily_outcome_row(self, *, signal_date: date, symbol: str) -> tuple[Any, ...] | None:
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
            return None
        return _outcome_row(bars[0], bars[1])

    def signal_stats(self, *, start: date | None = None, end: date | None = None) -> dict[str, Any]:
        self.ensure_tables()
        params = {"start": start or date(1970, 1, 1), "end": end or date(2999, 12, 31)}
        overall_rows = self._overall_rows(params)
        selected_rows = self._overall_rows(params, status="selected")
        recent = self._daily_stats(params, limit=20)
        selected_recent = self._daily_stats(params, limit=20, status="selected")
        selected_overall = _overall_stats(selected_rows[0] if selected_rows else None)
        details = self._detail_rows(params, status="selected", limit=200)
        return {
            "range": {
                "start": params["start"].isoformat(),
                "end": params["end"].isoformat(),
            },
            "overall": _overall_stats(overall_rows[0] if overall_rows else None),
            "selected_overall": selected_overall,
            "execution_summary": _execution_summary(selected_overall),
            "tracking_summary": _tracking_summary(details),
            "by_status": self._group_stats("s.status", params),
            "by_mode": self._group_stats("s.mode", params),
            "by_layer": self._group_stats("s.v2_layer", params),
            "by_filter_reason": self._group_stats("s.filter_reason", params),
            "by_signal_date": self._daily_stats(params),
            "recent": recent,
            "selected_recent": selected_recent,
            "details": details,
        }

    def _overall_rows(self, params: dict[str, date], status: str | None = None) -> list[tuple[Any, ...]]:
        status_filter = f"and s.status = '{status}'" if status else ""
        return self.client.execute(
            f"""
            select
                count(),
                countIf(o.close_return > 0),
                countIf(o.open_return > 0),
                countIf(o.max_return > 0),
                avg(o.open_return),
                avg(o.close_return),
                avg(o.max_return),
                avg(o.min_return),
                avgIf(o.close_return, o.close_return > 0),
                avgIf(abs(o.close_return), o.close_return < 0)
            from {_deduped_signal_source()} s
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
                countIf(o.open_return > 0),
                countIf(o.max_return > 0),
                avg(o.open_return),
                avg(o.close_return),
                avg(o.max_return),
                avg(o.min_return)
            from {_deduped_signal_source()} s
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
                countIf(o.open_return > 0),
                countIf(o.max_return > 0),
                avg(o.open_return),
                avg(o.close_return),
                avg(o.max_return),
                avg(o.min_return)
            from {_deduped_signal_source()} s
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

    def _detail_rows(
        self,
        params: dict[str, date],
        *,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        status_filter = f"and s.status = '{status}'" if status else ""
        rows = self.client.execute(
            f"""
            select
                s.trade_date,
                o.outcome_date,
                s.symbol,
                s.mode,
                s.rank,
                s.status,
                s.filter_reason,
                s.v2_layer,
                s.v2_action,
                s.strength,
                s.v2_score,
                s.volume_ratio,
                s.tail_return,
                o.signal_close,
                d.close as daily_signal_close,
                o.next_open,
                o.next_high,
                o.next_low,
                o.next_close,
                o.open_return,
                o.close_return,
                o.max_return,
                o.min_return,
                q.latest_price,
                q.latest_snapshot_at
            from {_deduped_signal_source()} s
            left join tail_signal_outcomes o
                on s.trade_date = o.signal_date and s.symbol = o.symbol
            left join (
                select symbol, date, any(close) as close
                from daily_kline
                group by symbol, date
            ) d on d.symbol = s.symbol and d.date = s.trade_date
            left join (
                select
                    substring(symbol, 1, 6) as code,
                    argMax(price, snapshot_at) as latest_price,
                    max(snapshot_at) as latest_snapshot_at
                from stock_quote_snapshots
                group by code
            ) q on q.code = s.symbol
            where {_stats_date_filter()}
                {status_filter}
            order by s.trade_date desc, s.rank asc
            limit %(limit)s
            """,
            {**params, "limit": limit},
        )
        return [_detail_row(row) for row in rows]


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
    return _outcome_values(
        signal_date=signal_date,
        outcome_date=outcome_date,
        symbol=str(symbol),
        signal_close=float(signal_close),
        next_open=float(next_open),
        next_high=float(next_high),
        next_low=float(next_low),
        next_close=float(next_close),
    )


def _outcome_values(
    *,
    signal_date: date,
    outcome_date: date,
    symbol: str,
    signal_close: float,
    next_open: float,
    next_high: float,
    next_low: float,
    next_close: float,
) -> tuple[Any, ...]:
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


def _deduped_signal_source() -> str:
    return """
    (
        select
            trade_date,
            symbol,
            mode,
            status,
            min_rank as rank,
            job_id,
            filter_reason,
            strength,
            last_price,
            volume_ratio,
            tail_return,
            v2_score,
            v2_layer,
            v2_action,
            updated_at
        from (
            select
                trade_date,
                symbol,
                mode,
                status,
                min(rank) as min_rank,
                argMin(job_id, rank) as job_id,
                argMin(filter_reason, rank) as filter_reason,
                argMin(strength, rank) as strength,
                argMin(last_price, rank) as last_price,
                argMin(volume_ratio, rank) as volume_ratio,
                argMin(tail_return, rank) as tail_return,
                argMin(v2_score, rank) as v2_score,
                argMin(v2_layer, rank) as v2_layer,
                argMin(v2_action, rank) as v2_action,
                max(updated_at) as updated_at
            from tail_selection_signals
            group by trade_date, symbol, mode, status
        )
    )
    """


def _overall_stats(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return _stats_row(0, 0, 0, 0, 0, 0, 0, 0)
    if len(row) == 6:
        count, win_count, avg_open_return, avg_close_return, avg_max_return, avg_min_return = row
        return _stats_row(count, win_count, 0, 0, avg_open_return, avg_close_return, avg_max_return, avg_min_return)
    return _stats_row(*row)


def _stats_row(
    count: Any,
    win_count: Any,
    open_win_count: Any = 0,
    max_win_count: Any = 0,
    avg_open_return: Any = 0,
    avg_close_return: Any = 0,
    avg_max_return: Any = 0,
    avg_min_return: Any = 0,
    avg_gain: Any = 0,
    avg_loss: Any = 0,
) -> dict[str, Any]:
    count_value = int(count or 0)
    win_value = int(win_count or 0)
    open_win_value = int(open_win_count or 0)
    max_win_value = int(max_win_count or 0)
    avg_gain_value = _safe_float(avg_gain)
    avg_loss_value = _safe_float(avg_loss)
    return {
        "count": count_value,
        "win_count": win_value,
        "win_rate": (win_value / count_value) if count_value else 0.0,
        "open_win_count": open_win_value,
        "open_win_rate": (open_win_value / count_value) if count_value else 0.0,
        "max_win_count": max_win_value,
        "max_win_rate": (max_win_value / count_value) if count_value else 0.0,
        "avg_open_return": _safe_float(avg_open_return),
        "avg_close_return": _safe_float(avg_close_return),
        "avg_max_return": _safe_float(avg_max_return),
        "avg_min_return": _safe_float(avg_min_return),
        "payoff_ratio": (avg_gain_value / avg_loss_value) if avg_loss_value else 0.0,
    }


def _group_row(row: tuple[Any, ...]) -> dict[str, Any]:
    group, count, win_count, open_win_count, max_win_count, avg_open_return, avg_close_return, avg_max_return, avg_min_return = row
    count_value = int(count or 0)
    win_value = int(win_count or 0)
    open_win_value = int(open_win_count or 0)
    max_win_value = int(max_win_count or 0)
    return {
        "group": str(group or "未分组"),
        "count": count_value,
        "win_count": win_value,
        "win_rate": (win_value / count_value) if count_value else 0.0,
        "open_win_count": open_win_value,
        "open_win_rate": (open_win_value / count_value) if count_value else 0.0,
        "max_win_count": max_win_value,
        "max_win_rate": (max_win_value / count_value) if count_value else 0.0,
        "avg_open_return": _safe_float(avg_open_return),
        "avg_close_return": _safe_float(avg_close_return),
        "avg_max_return": _safe_float(avg_max_return),
        "avg_min_return": _safe_float(avg_min_return),
    }


def _daily_row(row: tuple[Any, ...]) -> dict[str, Any]:
    signal_date, count, win_count, open_win_count, max_win_count, avg_open_return, avg_close_return, avg_max_return, avg_min_return = row
    count_value = int(count or 0)
    win_value = int(win_count or 0)
    open_win_value = int(open_win_count or 0)
    max_win_value = int(max_win_count or 0)
    return {
        "date": _date_string(signal_date),
        "count": count_value,
        "win_count": win_value,
        "win_rate": (win_value / count_value) if count_value else 0.0,
        "open_win_count": open_win_value,
        "open_win_rate": (open_win_value / count_value) if count_value else 0.0,
        "max_win_count": max_win_value,
        "max_win_rate": (max_win_value / count_value) if count_value else 0.0,
        "avg_open_return": _safe_float(avg_open_return),
        "avg_close_return": _safe_float(avg_close_return),
        "avg_max_return": _safe_float(avg_max_return),
        "avg_min_return": _safe_float(avg_min_return),
    }


def _execution_summary(selected: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_count": int(selected.get("count") or 0),
        "open_win_rate": float(selected.get("open_win_rate") or 0),
        "close_win_rate": float(selected.get("win_rate") or 0),
        "max_win_rate": float(selected.get("max_win_rate") or 0),
        "avg_open_return": float(selected.get("avg_open_return") or 0),
        "avg_close_return": float(selected.get("avg_close_return") or 0),
        "avg_max_return": float(selected.get("avg_max_return") or 0),
        "avg_min_return": float(selected.get("avg_min_return") or 0),
        "payoff_ratio": float(selected.get("payoff_ratio") or 0),
    }


def _tracking_summary(details: list[dict[str, Any]]) -> dict[str, int]:
    completed = sum(1 for row in details if row.get("review_status") == "completed")
    live_tracking = sum(1 for row in details if row.get("review_status") == "live_tracking")
    pending = sum(1 for row in details if row.get("review_status") == "pending_outcome")
    return {
        "total": len(details),
        "completed": completed,
        "live_tracking": live_tracking,
        "pending_outcome": pending,
    }


def _detail_row(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        trade_date,
        outcome_date,
        symbol,
        mode,
        rank,
        status,
        filter_reason,
        v2_layer,
        v2_action,
        strength,
        v2_score,
        volume_ratio,
        tail_return,
        signal_close,
        daily_signal_close,
        next_open,
        next_high,
        next_low,
        next_close,
        open_return,
        close_return,
        max_return,
        min_return,
        current_price,
        latest_snapshot_at,
    ) = row
    signal_close_value = _first_positive(signal_close, daily_signal_close)
    current_price_value = float(current_price or 0)
    has_outcome = _valid_date(outcome_date) and float(next_close or 0) > 0
    review_status = "completed" if has_outcome else "live_tracking" if current_price_value > 0 else "pending_outcome"
    return {
        "trade_date": _date_string(trade_date),
        "outcome_date": _date_string(outcome_date) if has_outcome else None,
        "symbol": _format_symbol(str(symbol)),
        "mode": str(mode or ""),
        "rank": int(rank or 0),
        "status": str(status or ""),
        "review_status": review_status,
        "filter_reason": str(filter_reason or ""),
        "v2_layer": str(v2_layer or ""),
        "v2_action": str(v2_action or ""),
        "strength": _float_or_none(strength),
        "v2_score": _float_or_none(v2_score),
        "volume_ratio": _float_or_none(volume_ratio),
        "tail_return": _float_or_none(tail_return),
        "signal_close": signal_close_value,
        "next_open": _safe_float(next_open),
        "next_high": _safe_float(next_high),
        "next_low": _safe_float(next_low),
        "next_close": _safe_float(next_close),
        "open_return": _safe_float(open_return),
        "close_return": _safe_float(close_return),
        "max_return": _safe_float(max_return),
        "min_return": _safe_float(min_return),
        "current_price": current_price_value,
        "current_return": _return(current_price_value, signal_close_value) if current_price_value > 0 else 0.0,
        "latest_snapshot_at": _datetime_string(latest_snapshot_at) if current_price_value > 0 else None,
    }


def _format_symbol(symbol: str) -> str:
    code = symbol.split(".")[0].zfill(6)
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return code


def _date_string(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _datetime_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def _valid_date(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, date):
        return value.year > 1970
    text = str(value)
    return bool(text and not text.startswith("1970-01-01"))


def _first_positive(*values: Any) -> float:
    for value in values:
        number = _safe_float(value)
        if number > 0:
            return number
    return 0.0


def _safe_float(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if isfinite(number) else 0.0
