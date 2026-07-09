"""Minute-level ClickHouse quality inspection helpers."""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource

EXPECTED_FULL_DAY_BUCKETS = 48
MIN_COMPLETE_BUCKET_COVERAGE = 0.95
NON_ST_STOCK_PREDICATE = "not match(upper(s.name), '^(\\\\*ST|S\\\\*ST|SST|ST)([^A-Z]|$)') and s.name not like '%%退市%%'"


class Minute5QualityService:
    """Read-only diagnostics for the production minute5_kline table."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        self._source = None if client is not None else ClickHouseStockDataSource(host=host, user=user, password=password, database=database)
        self._client = client
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._source._client_instance()
        return self._client

    def _execute(self, query: str, params: Any = None):
        with self._lock:
            return self.client.execute(query, params)

    def summary(self) -> dict[str, Any]:
        rows = self._execute("select count(), uniqExact(symbol), min(datetime), max(datetime) from minute5_kline")
        row = rows[0] if rows else (0, 0, None, None)
        duplicate_groups, extra_rows = self._duplicate_stats()
        invalid = self._invalid_stats()
        non_5m_boundary = self._single_count(
            """
            select count()
            from minute5_kline
            where toSecond(datetime) != 0 or toMinute(datetime) % 5 != 0
            """
        )
        non_market_session = self._single_count(
            """
            select count()
            from minute5_kline
            where not ((toHour(datetime) = 9 and toMinute(datetime) >= 35)
                or (toHour(datetime) = 10)
                or (toHour(datetime) = 11 and toMinute(datetime) <= 30)
                or (toHour(datetime) = 13)
                or (toHour(datetime) = 14)
                or (toHour(datetime) = 15 and toMinute(datetime) = 0))
            """
        )
        latest_date = self._latest_date()
        expected_symbols = self._expected_symbols()
        latest_raw_bucket, latest_raw_symbols = self._latest_raw_bucket(latest_date)
        complete_bucket, complete_symbols = self._latest_complete_bucket(latest_date, expected_symbols)
        invalid_ohlc = sum(invalid.values())
        status = "ok" if duplicate_groups == 0 and invalid_ohlc == 0 and non_5m_boundary == 0 and non_market_session == 0 else "warning"
        return {
            "table": "minute5_kline",
            "rows": int(row[0] or 0),
            "symbols": int(row[1] or 0),
            "range": {"start": _format_datetime(row[2]), "end": _format_datetime(row[3])},
            "expected_symbols": expected_symbols,
            "latest": {
                "trade_date": _format_date(latest_date),
                "raw_bucket": _format_datetime(latest_raw_bucket),
                "raw_symbols": latest_raw_symbols,
                "complete_bucket": _format_datetime(complete_bucket),
                "complete_symbols": complete_symbols,
                "complete_threshold": round(expected_symbols * MIN_COMPLETE_BUCKET_COVERAGE),
            },
            "issues": {
                "duplicate_groups": duplicate_groups,
                "extra_rows": extra_rows,
                "invalid_ohlc": invalid_ohlc,
                **invalid,
                "non_5m_boundary": non_5m_boundary,
                "non_market_session": non_market_session,
            },
            "status": status,
        }

    def days(self, start: date | None = None, end: date | None = None, limit: int = 90) -> dict[str, Any]:
        where = []
        params: dict[str, Any] = {"limit": max(1, min(int(limit or 90), 366))}
        if start is not None:
            where.append("toDate(datetime) >= %(start)s")
            params["start"] = start
        if end is not None:
            where.append("toDate(datetime) <= %(end)s")
            params["end"] = end
        where_sql = f"where {' and '.join(where)}" if where else ""
        rows = self._execute(
            f"""
            select
                toDate(datetime) as trade_date,
                count() as rows,
                uniqExact(symbol) as symbols,
                uniqExact(datetime) as buckets,
                min(datetime) as first_bucket,
                max(datetime) as latest_bucket,
                round(rows / nullIf(symbols, 0), 2) as avg_bars_per_symbol,
                countIf(open <= 0 or high <= 0 or low <= 0 or close <= 0
                    or high < greatest(open, close, low)
                    or low > least(open, close, high)
                    or volume < 0 or amount < 0) as invalid_rows
            from minute5_kline
            {where_sql}
            group by trade_date
            order by trade_date desc
            limit %(limit)s
            """,
            params,
        )
        items = []
        for row in rows:
            buckets = int(row[3] or 0)
            invalid_rows = int(row[7] or 0)
            status = "ok" if buckets >= EXPECTED_FULL_DAY_BUCKETS and invalid_rows == 0 else "warning"
            items.append(
                {
                    "trade_date": _format_date(row[0]),
                    "rows": int(row[1] or 0),
                    "symbols": int(row[2] or 0),
                    "buckets": buckets,
                    "first_bucket": _format_datetime(row[4]),
                    "latest_bucket": _format_datetime(row[5]),
                    "avg_bars_per_symbol": float(row[6] or 0),
                    "invalid_rows": invalid_rows,
                    "status": status,
                }
            )
        return {"items": items}

    def buckets(self, trade_date: date) -> dict[str, Any]:
        expected_symbols = self._expected_symbols()
        rows = self._execute(
            """
            select
                datetime,
                count() as rows,
                uniqExact(symbol) as symbols,
                countIf(open <= 0 or high <= 0 or low <= 0 or close <= 0
                    or high < greatest(open, close, low)
                    or low > least(open, close, high)
                    or volume < 0 or amount < 0) as invalid_rows
            from minute5_kline
            where toDate(datetime) = %(trade_date)s
            group by datetime
            order by datetime
            """,
            {"trade_date": trade_date},
        )
        items = []
        threshold = max(1, round(expected_symbols * MIN_COMPLETE_BUCKET_COVERAGE))
        for row in rows:
            symbols = int(row[2] or 0)
            invalid_rows = int(row[3] or 0)
            if invalid_rows:
                status = "warning"
            elif symbols >= threshold:
                status = "ok"
            else:
                status = "partial"
            items.append(
                {
                    "datetime": _format_datetime(row[0]),
                    "rows": int(row[1] or 0),
                    "symbols": symbols,
                    "coverage_ratio": _ratio(symbols, expected_symbols),
                    "invalid_rows": invalid_rows,
                    "status": status,
                }
            )
        return {"trade_date": trade_date.isoformat(), "expected_symbols": expected_symbols, "items": items}

    def sample(self, trade_date: date | None = None, mode: str = "random", limit: int = 20) -> dict[str, Any]:
        selected_date = trade_date or self._latest_date()
        if selected_date is None:
            return {"trade_date": None, "mode": mode, "items": []}
        sample_mode = mode if mode in {"random", "invalid", "low_coverage"} else "random"
        order_sql = "rand()"
        having_sql = ""
        if sample_mode == "invalid":
            having_sql = "having invalid_rows > 0"
            order_sql = "invalid_rows desc, bars asc"
        elif sample_mode == "low_coverage":
            order_sql = "bars asc, invalid_rows desc, symbol"
        rows = self._execute(
            f"""
            select
                k.symbol,
                anyLast(s.name) as name,
                count() as bars,
                min(k.datetime) as first_bucket,
                max(k.datetime) as latest_bucket,
                countIf(k.open <= 0 or k.high <= 0 or k.low <= 0 or k.close <= 0
                    or k.high < greatest(k.open, k.close, k.low)
                    or k.low > least(k.open, k.close, k.high)
                    or k.volume < 0 or k.amount < 0) as invalid_rows
            from minute5_kline k
            left join stocks s on s.symbol = k.symbol
            where toDate(k.datetime) = %(trade_date)s
            group by k.symbol
            {having_sql}
            order by {order_sql}
            limit %(limit)s
            """,
            {"trade_date": selected_date, "limit": max(1, min(int(limit or 20), 200))},
        )
        return {
            "trade_date": selected_date.isoformat(),
            "mode": sample_mode,
            "items": [
                {
                    "symbol": str(row[0]),
                    "name": str(row[1] or ""),
                    "bars": int(row[2] or 0),
                    "first_bucket": _format_datetime(row[3]),
                    "latest_bucket": _format_datetime(row[4]),
                    "invalid_rows": int(row[5] or 0),
                }
                for row in rows
            ],
        }

    def symbol_bars(self, symbol: str, trade_date: date) -> dict[str, Any]:
        code = _normalize_symbol(symbol)
        name_rows = self._execute("select anyLast(name) from stocks where symbol = %(symbol)s", {"symbol": code})
        rows = self._execute(
            """
            select datetime, open, high, low, close, volume, amount
            from minute5_kline
            where symbol = %(symbol)s and toDate(datetime) = %(trade_date)s
            order by datetime
            """,
            {"symbol": code, "trade_date": trade_date},
        )
        return {
            "symbol": code,
            "name": str(name_rows[0][0] or "") if name_rows else "",
            "trade_date": trade_date.isoformat(),
            "items": [
                {
                    "datetime": _format_datetime(row[0]),
                    "open": float(row[1] or 0),
                    "high": float(row[2] or 0),
                    "low": float(row[3] or 0),
                    "close": float(row[4] or 0),
                    "volume": float(row[5] or 0),
                    "amount": float(row[6] or 0),
                }
                for row in rows
            ],
        }

    def missing_symbols(self, trade_date: date, bucket: str | None = None, limit: int = 200) -> dict[str, Any]:
        expected_buckets = EXPECTED_FULL_DAY_BUCKETS
        params: dict[str, Any] = {
            "trade_date": trade_date,
            "expected_buckets": expected_buckets,
            "limit": max(1, min(int(limit or 200), 10000)),
        }
        bucket_filter = ""
        if bucket:
            bucket_dt = _bucket_datetime(trade_date, bucket)
            params["bucket_dt"] = bucket_dt
            bucket_filter = "and k.datetime = %(bucket_dt)s"
            expected_buckets = 1
            params["expected_buckets"] = expected_buckets
        rows = self._execute(
            f"""
            with latest_daily as (
                select max(date) as latest_daily_date
                from daily_kline
                where date <= %(trade_date)s
            ),
            expected_symbols as (
                select s.symbol as symbol, anyLast(s.name) as name
                from latest_daily ld
                inner join daily_kline AS d
                    on d.date = ld.latest_daily_date
                inner join stocks AS s
                    on s.symbol = d.symbol
                where upper(s.market) in ('SH', 'SZ')
                    and {NON_ST_STOCK_PREDICATE}
                group by s.symbol
            ),
            observed_symbols as (
                select
                    symbol,
                    uniqExact(datetime) as bars,
                    max(datetime) as latest_bucket
                from minute5_kline k
                where toDate(k.datetime) = %(trade_date)s
                    {bucket_filter}
                group by symbol
            )
            select
                e.symbol,
                e.name,
                ifNull(o.bars, 0) as bars,
                if(ifNull(o.bars, 0) = 0, NULL, o.latest_bucket) as latest_bucket,
                greatest(0, %(expected_buckets)s - ifNull(o.bars, 0)) as missing_bars
            from expected_symbols e
            left join observed_symbols o on o.symbol = e.symbol
            where missing_bars > 0
            order by missing_bars desc, e.symbol
            limit %(limit)s
            """,
            params,
        )
        return {
            "trade_date": trade_date.isoformat(),
            "bucket": _format_datetime(params.get("bucket_dt")) if bucket else None,
            "expected_buckets": expected_buckets,
            "items": [
                {
                    "symbol": str(row[0]),
                    "name": str(row[1] or ""),
                    "bars": int(row[2] or 0),
                    "latest_bucket": _format_datetime(row[3]),
                    "missing_bars": int(row[4] or 0),
                }
                for row in rows
            ],
        }

    def invalid_rows(self, trade_date: date, limit: int = 200) -> dict[str, Any]:
        rows = self._execute(
            """
            select
                k.symbol,
                s.name as name,
                k.datetime,
                k.open,
                k.high,
                k.low,
                k.close,
                k.volume,
                k.amount,
                multiIf(
                    k.open <= 0 or k.high <= 0 or k.low <= 0 or k.close <= 0, 'non_positive_ohlc',
                    k.high < greatest(k.open, k.close, k.low), 'high_invalid',
                    k.low > least(k.open, k.close, k.high), 'low_invalid',
                    k.volume < 0, 'negative_volume',
                    k.amount < 0, 'negative_amount',
                    'unknown'
                ) as invalid_reason
            from minute5_kline k
            left join stocks s on s.symbol = k.symbol
            where toDate(k.datetime) = %(trade_date)s
                and (
                    k.open <= 0 or k.high <= 0 or k.low <= 0 or k.close <= 0
                    or k.high < greatest(k.open, k.close, k.low)
                    or k.low > least(k.open, k.close, k.high)
                    or k.volume < 0
                    or k.amount < 0
                )
            order by k.datetime desc, k.symbol
            limit %(limit)s
            """,
            {"trade_date": trade_date, "limit": max(1, min(int(limit or 200), 1000))},
        )
        return {
            "trade_date": trade_date.isoformat(),
            "items": [
                {
                    "symbol": str(row[0]),
                    "name": str(row[1] or ""),
                    "datetime": _format_datetime(row[2]),
                    "open": float(row[3] or 0),
                    "high": float(row[4] or 0),
                    "low": float(row[5] or 0),
                    "close": float(row[6] or 0),
                    "volume": float(row[7] or 0),
                    "amount": float(row[8] or 0),
                    "reason": str(row[9] or "unknown"),
                }
                for row in rows
            ],
        }

    def delete_symbol_day_rows(self, trade_date: date, symbols: list[str]) -> dict[str, Any]:
        codes = sorted({_normalize_symbol(symbol) for symbol in symbols if str(symbol).strip()})
        if not codes:
            return {"trade_date": trade_date.isoformat(), "deleted_symbols": [], "mutation": "skipped"}
        self._execute(
            """
            alter table minute5_kline
            delete where toDate(datetime) = %(trade_date)s
                and symbol in %(symbols)s
            settings mutations_sync = 2
            """,
            {"trade_date": trade_date, "symbols": tuple(codes)},
        )
        return {
            "trade_date": trade_date.isoformat(),
            "deleted_symbols": codes,
            "mutation": "submitted",
        }

    def backfill_plan(self, start: date, end: date, limit: int = 90) -> dict[str, Any]:
        max_days = max(1, min(int(limit or 90), 366))
        rows = self._execute(
            f"""
            with candidate_dates as (
                select distinct toDate(datetime) as trade_date
                from minute5_kline
                where toDate(datetime) >= %(start)s and toDate(datetime) <= %(end)s
                union distinct
                select date as trade_date
                from daily_kline
                where date >= %(start)s and date <= %(end)s
            ),
            latest_daily as (
                select cd.trade_date, max(d.date) as latest_daily_date
                from candidate_dates cd
                inner join (
                    select distinct date
                    from daily_kline
                    where date <= %(end)s
                ) d on d.date <= cd.trade_date
                group by cd.trade_date
            ),
            expected_symbol_rows as (
                select ld.trade_date, s.symbol as symbol
                from latest_daily ld
                inner join daily_kline d on d.date = ld.latest_daily_date
                inner join stocks s on s.symbol = d.symbol
                where upper(s.market) in ('SH', 'SZ')
                    and {NON_ST_STOCK_PREDICATE}
                group by ld.trade_date, s.symbol
            ),
            expected_symbols as (
                select trade_date, count() as expected_symbols
                from expected_symbol_rows
                group by trade_date
            ),
            observed as (
                select
                    toDate(k.datetime) as trade_date,
                    uniqExact(k.datetime) as actual_buckets,
                    countIf(k.open <= 0 or k.high <= 0 or k.low <= 0 or k.close <= 0
                        or k.high < greatest(k.open, k.close, k.low)
                        or k.low > least(k.open, k.close, k.high)
                        or k.volume < 0 or k.amount < 0) as invalid_rows,
                    max(k.datetime) as latest_bucket
                from minute5_kline k
                where toDate(k.datetime) >= %(start)s and toDate(k.datetime) <= %(end)s
                group by trade_date
            ),
            symbol_coverage as (
                select
                    e.trade_date,
                    countIf(ifNull(o.bars, 0) < %(expected_buckets)s) as missing_symbols
                from expected_symbol_rows e
                left join (
                    select toDate(datetime) as trade_date, symbol, uniqExact(datetime) as bars
                    from minute5_kline
                    where toDate(datetime) >= %(start)s and toDate(datetime) <= %(end)s
                    group by trade_date, symbol
                ) o on o.trade_date = e.trade_date and o.symbol = e.symbol
                group by e.trade_date
            )
            select
                e.trade_date,
                e.expected_symbols,
                %(expected_buckets)s as expected_buckets,
                ifNull(o.actual_buckets, 0) as actual_buckets,
                greatest(0, %(expected_buckets)s - ifNull(o.actual_buckets, 0)) as missing_buckets,
                ifNull(c.missing_symbols, e.expected_symbols) as missing_symbols,
                ifNull(o.invalid_rows, 0) as invalid_rows,
                o.latest_bucket
            from expected_symbols e
            left join observed o on o.trade_date = e.trade_date
            left join symbol_coverage c on c.trade_date = e.trade_date
            order by e.trade_date desc
            limit %(limit)s
            """,
            {"start": start, "end": end, "limit": max_days, "expected_buckets": EXPECTED_FULL_DAY_BUCKETS},
        )
        items = []
        for row in rows:
            missing_buckets = int(row[4] or 0)
            missing_symbols = int(row[5] or 0)
            invalid_rows = int(row[6] or 0)
            status = "needs_backfill" if missing_buckets or missing_symbols or invalid_rows else "ok"
            items.append(
                {
                    "trade_date": _format_date(row[0]),
                    "expected_symbols": int(row[1] or 0),
                    "expected_buckets": int(row[2] or 0),
                    "actual_buckets": int(row[3] or 0),
                    "missing_buckets": missing_buckets,
                    "missing_symbols": missing_symbols,
                    "invalid_rows": invalid_rows,
                    "latest_bucket": _format_datetime(row[7]),
                    "status": status,
                }
            )
        needs = [item for item in items if item["status"] != "ok"]
        return {
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "items": items,
            "summary": {
                "days": len(items),
                "needs_backfill_days": len(needs),
                "missing_buckets": sum(int(item["missing_buckets"]) for item in items),
                "missing_symbols": sum(int(item["missing_symbols"]) for item in items),
                "invalid_rows": sum(int(item["invalid_rows"]) for item in items),
            },
        }

    def _single_count(self, query: str, params: Any = None) -> int:
        rows = self._execute(query, params)
        return int(rows[0][0] or 0) if rows else 0

    def _duplicate_stats(self) -> tuple[int, int]:
        rows = self._execute(
            """
            select count(), ifNull(sum(c - 1), 0)
            from (
                select symbol, datetime, count() as c
                from minute5_kline
                group by symbol, datetime
                having count() > 1
            )
            """
        )
        return (int(rows[0][0] or 0), int(rows[0][1] or 0)) if rows else (0, 0)

    def _invalid_stats(self) -> dict[str, int]:
        rows = self._execute(
            """
            select
                countIf(open <= 0 or high <= 0 or low <= 0 or close <= 0) as non_positive_ohlc,
                countIf(high < greatest(open, close, low)) as high_invalid,
                countIf(low > least(open, close, high)) as low_invalid,
                countIf(volume < 0) as negative_volume,
                countIf(amount < 0) as negative_amount
            from minute5_kline
            """
        )
        row = rows[0] if rows else (0, 0, 0, 0, 0)
        return {
            "non_positive_ohlc": int(row[0] or 0),
            "high_invalid": int(row[1] or 0),
            "low_invalid": int(row[2] or 0),
            "negative_volume": int(row[3] or 0),
            "negative_amount": int(row[4] or 0),
        }

    def _latest_date(self) -> date | None:
        rows = self._execute("select max(toDate(datetime)) from minute5_kline")
        return _coerce_date(rows[0][0]) if rows else None

    def _latest_raw_bucket(self, trade_date: date | None) -> tuple[datetime | None, int]:
        if trade_date is None:
            return None, 0
        rows = self._execute(
            """
            select datetime, uniqExact(symbol)
            from minute5_kline
            where toDate(datetime) = %(trade_date)s
            group by datetime
            order by datetime desc
            limit 1
            """,
            {"trade_date": trade_date},
        )
        return (rows[0][0], int(rows[0][1] or 0)) if rows else (None, 0)

    def _latest_complete_bucket(self, trade_date: date | None, expected_symbols: int) -> tuple[datetime | None, int]:
        if trade_date is None or expected_symbols <= 0:
            return None, 0
        rows = self._execute(
            """
            select datetime, covered
            from (
                select datetime, uniqExact(symbol) as covered
                from minute5_kline
                where toDate(datetime) = %(trade_date)s
                group by datetime
            )
            where covered >= greatest(1, %(min_symbols)s)
            order by datetime desc
            limit 1
            """,
            {"trade_date": trade_date, "min_symbols": round(expected_symbols * MIN_COMPLETE_BUCKET_COVERAGE)},
        )
        return (rows[0][0], int(rows[0][1] or 0)) if rows else (None, 0)

    def _expected_symbols(self) -> int:
        rows = self._execute(
            f"""
            select count()
            from (
                select s.symbol
                from stocks AS s
                inner join daily_kline AS d
                    on d.symbol = s.symbol and d.date = (select max(date) from daily_kline)
                where upper(s.market) in ('SH', 'SZ')
                    and {NON_ST_STOCK_PREDICATE}
                group by s.symbol
            )
            """
        )
        return int(rows[0][0] or 0) if rows else 0


def _normalize_symbol(value: str) -> str:
    raw = value.strip().split(".")[0]
    return raw.zfill(6) if raw.isdigit() else raw


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(max(0.0, min(1.0, numerator / denominator)), 4)


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _format_date(value: Any) -> str | None:
    parsed = _coerce_date(value)
    return parsed.isoformat() if parsed is not None else None


def _format_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _bucket_datetime(trade_date: date, bucket: str) -> datetime:
    value = bucket.strip()
    if len(value) == 5 and value[2] == ":":
        return datetime.fromisoformat(f"{trade_date.isoformat()} {value}:00")
    if len(value) == 8 and value[2] == ":":
        return datetime.fromisoformat(f"{trade_date.isoformat()} {value}")
    return datetime.fromisoformat(value)
