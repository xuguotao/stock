"""ClickHouse-backed data quality calendar by trading day."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource

QUALITY_SOURCE_KEYS = (
    "daily_kline",
    "minute5_kline",
    "stock_quote_snapshots",
    "stock_quote_snapshots_1m",
    "stock_quote_snapshots_5m",
    "data_source_health",
)

TRADING_MINUTES = 240
MINUTE5_BUCKETS = 48
QUOTE_RAW_BUCKETS_10S = TRADING_MINUTES * 6
NON_ST_STOCK_PREDICATE = "not match(upper(s.name), '^(\\\\*ST|S\\\\*ST|SST|ST)([^A-Z]|$)') and s.name not like '%%退市%%'"


@dataclass(frozen=True)
class QualityCalendarSource:
    key: str
    name: str
    table: str
    expected_cadence: str
    repairability: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "table": self.table,
            "expected_cadence": self.expected_cadence,
            "repairability": self.repairability,
        }


QUALITY_SOURCES = {
    "daily_kline": QualityCalendarSource("daily_kline", "股票日线", "daily_kline", "日终 1 次", "可修复"),
    "minute5_kline": QualityCalendarSource("minute5_kline", "5m 分钟线", "minute5_kline", "交易时段 5 分钟桶", "可修复"),
    "stock_quote_snapshots": QualityCalendarSource(
        "stock_quote_snapshots",
        "秒级行情快照",
        "stock_quote_snapshots",
        "交易时段约 10 秒",
        "盘中断档不可完全追回",
    ),
    "stock_quote_snapshots_1m": QualityCalendarSource(
        "stock_quote_snapshots_1m",
        "1m 快照聚合",
        "stock_quote_snapshots_1m",
        "交易时段 1 分钟桶",
        "可由原始快照重建",
    ),
    "stock_quote_snapshots_5m": QualityCalendarSource(
        "stock_quote_snapshots_5m",
        "5m 快照聚合",
        "stock_quote_snapshots_5m",
        "交易时段 5 分钟桶",
        "可由原始快照重建",
    ),
    "data_source_health": QualityCalendarSource("data_source_health", "质量快照", "data_source_health", "质量任务写入", "重新检查可生成"),
}


class DataQualityCalendarService:
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

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._source._client_instance()
        return self._client

    def ensure_table(self) -> None:
        self.client.execute(
            """
            create table if not exists data_quality_calendar (
                trade_date Date,
                source_key LowCardinality(String),
                source_name String,
                status LowCardinality(String),
                latest_time Nullable(DateTime),
                expected_symbols UInt32,
                covered_symbols UInt32,
                coverage_ratio Float64,
                expected_buckets UInt32,
                observed_buckets UInt32,
                missing_buckets UInt32,
                duplicate_rows UInt32,
                max_gap_seconds UInt32,
                repairability String,
                summary String,
                details String,
                checked_at DateTime
            )
            engine = ReplacingMergeTree(checked_at)
            partition by toYYYYMM(trade_date)
            order by (trade_date, source_key)
            """
        )

    def generate(
        self,
        *,
        start: date,
        end: date,
        source_keys: list[str] | None = None,
        checked_at: datetime | None = None,
    ) -> dict[str, int]:
        self.ensure_table()
        selected = _selected_source_keys(source_keys)
        checked_time = checked_at or datetime.now()
        rows = [
            self._build_row(trade_date=trade_date, source_key=source_key, checked_at=checked_time)
            for trade_date in self._trade_dates(start=start, end=end)
            for source_key in selected
        ]
        if rows:
            self.client.execute(
                """
                insert into data_quality_calendar
                    (trade_date, source_key, source_name, status, latest_time, expected_symbols,
                     covered_symbols, coverage_ratio, expected_buckets, observed_buckets,
                     missing_buckets, duplicate_rows, max_gap_seconds, repairability,
                     summary, details, checked_at)
                values
                """,
                rows,
            )
        generated_dates = len({row[0] for row in rows})
        return {"generated_dates": generated_dates, "rows": len(rows)}

    def list(
        self,
        *,
        start: date,
        end: date,
        source_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_table()
        selected = _selected_source_keys(source_keys)
        trade_dates = self._trade_dates(start=start, end=end)
        rows = self.client.execute(
            """
            select trade_date, source_key, source_name, status, latest_time,
                   expected_symbols, covered_symbols, coverage_ratio, expected_buckets,
                   observed_buckets, missing_buckets, duplicate_rows, max_gap_seconds,
                   repairability, summary, details, checked_at
            from data_quality_calendar final
            where trade_date >= %(start)s
                and trade_date <= %(end)s
                and source_key in %(source_keys)s
            order by trade_date desc, source_key
            """,
            {"start": start, "end": end, "source_keys": tuple(selected)},
        )
        by_date: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            cell = _cell_from_row(row)
            trade_date = _format_date(row[0])
            by_date.setdefault(trade_date, {})[cell["source_key"]] = cell

        date_rows = []
        for trade_date in sorted((_format_date(day) for day in trade_dates), reverse=True):
            cells = [
                by_date.get(trade_date, {}).get(source_key) or _unchecked_cell(source_key)
                for source_key in selected
            ]
            date_rows.append(
                {
                    "trade_date": trade_date,
                    "overall_status": _overall_status([str(cell["status"]) for cell in cells]),
                    "checked_at": _latest_checked_at(cells),
                    "sources": cells,
                }
            )
        return {
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "source_keys": selected,
            "sources": [QUALITY_SOURCES[key].to_dict() for key in selected],
            "dates": date_rows,
        }

    def _trade_dates(self, *, start: date, end: date) -> list[date]:
        try:
            rows = self.client.execute(
                """
                select date
                from trade_calendar
                where date >= %(start)s and date <= %(end)s and is_open = 1
                order by date
                """,
                {"start": start, "end": end},
            )
        except Exception:
            rows = self.client.execute(
                """
                select date
                from trade_calendar
                where date >= %(start)s and date <= %(end)s
                order by date
                """,
                {"start": start, "end": end},
            )
        return [_coerce_date(row[0]) for row in rows if _coerce_date(row[0]) is not None]

    def _expected_symbols(self) -> int:
        rows = self.client.execute(
            f"""
            select count()
            from stocks s
            where {NON_ST_STOCK_PREDICATE}
            """
        )
        return int(rows[0][0] or 0) if rows else 0

    def _build_row(self, *, trade_date: date, source_key: str, checked_at: datetime) -> tuple:
        source = QUALITY_SOURCES[source_key]
        expected_symbols = self._expected_symbols() if source_key != "data_source_health" else 0
        if source_key == "daily_kline":
            metrics = self._single_table_metrics(
                table="daily_kline",
                time_col="date",
                trade_date=trade_date,
                expected_symbols=expected_symbols,
                expected_buckets=1,
            )
        elif source_key == "minute5_kline":
            metrics = self._single_table_metrics(
                table="minute5_kline",
                time_col="datetime",
                trade_date=trade_date,
                expected_symbols=expected_symbols,
                expected_buckets=MINUTE5_BUCKETS,
            )
        elif source_key == "stock_quote_snapshots":
            metrics = self._single_table_metrics(
                table="stock_quote_snapshots",
                time_col="snapshot_at",
                trade_date=trade_date,
                expected_symbols=expected_symbols,
                expected_buckets=QUOTE_RAW_BUCKETS_10S,
                include_gap=True,
            )
        elif source_key == "stock_quote_snapshots_1m":
            metrics = self._single_table_metrics(
                table="stock_quote_snapshots_1m",
                time_col="bucket_start",
                trade_date=trade_date,
                expected_symbols=expected_symbols,
                expected_buckets=TRADING_MINUTES,
            )
        elif source_key == "stock_quote_snapshots_5m":
            metrics = self._single_table_metrics(
                table="stock_quote_snapshots_5m",
                time_col="bucket_start",
                trade_date=trade_date,
                expected_symbols=expected_symbols,
                expected_buckets=MINUTE5_BUCKETS,
            )
        else:
            metrics = self._health_snapshot_metrics(trade_date=trade_date)

        status = _status_from_metrics(source_key=source_key, **{key: metrics[key] for key in (
            "expected_symbols",
            "covered_symbols",
            "expected_buckets",
            "observed_buckets",
            "duplicate_rows",
        )})
        missing_buckets = max(0, int(metrics["expected_buckets"]) - int(metrics["observed_buckets"]))
        coverage_ratio = _coverage_ratio(int(metrics["covered_symbols"]), int(metrics["expected_symbols"]))
        summary = _summary(
            covered_symbols=int(metrics["covered_symbols"]),
            expected_symbols=int(metrics["expected_symbols"]),
            missing_buckets=missing_buckets,
            duplicate_rows=int(metrics["duplicate_rows"]),
            max_gap_seconds=int(metrics["max_gap_seconds"]),
        )
        details = {
            "table": source.table,
            "expected_cadence": source.expected_cadence,
            "row_count": int(metrics["row_count"]),
            "missing_buckets": missing_buckets,
            "max_gap_seconds": int(metrics["max_gap_seconds"]),
        }
        if source_key == "data_source_health":
            details["failed_checks"] = int(metrics["duplicate_rows"])
        return (
            trade_date,
            source.key,
            source.name,
            status,
            metrics["latest_time"],
            int(metrics["expected_symbols"]),
            int(metrics["covered_symbols"]),
            coverage_ratio,
            int(metrics["expected_buckets"]),
            int(metrics["observed_buckets"]),
            missing_buckets,
            int(metrics["duplicate_rows"]),
            int(metrics["max_gap_seconds"]),
            source.repairability,
            summary,
            json.dumps(details, ensure_ascii=False, default=str, sort_keys=True),
            checked_at,
        )

    def _single_table_metrics(
        self,
        *,
        table: str,
        time_col: str,
        trade_date: date,
        expected_symbols: int,
        expected_buckets: int,
        include_gap: bool = False,
    ) -> dict[str, Any]:
        rows = self.client.execute(
            f"""
            select
                count() as row_count,
                max(toDateTime({time_col})) as latest_time,
                uniqExact(symbol) as covered_symbols,
                uniqExact({time_col}) as observed_buckets,
                (
                    select ifNull(sum(c - 1), 0)
                    from (
                        select symbol, {time_col}, count() as c
                        from {table}
                        where toDate({time_col}) = %(trade_date)s
                        group by symbol, {time_col}
                        having c > 1
                    )
                ) as duplicate_rows
            from {table}
            where toDate({time_col}) = %(trade_date)s
            """,
            {"trade_date": trade_date},
        )
        row = rows[0] if rows else (0, None, 0, 0, 0)
        max_gap_seconds = self._max_gap_seconds(table=table, time_col=time_col, trade_date=trade_date) if include_gap else 0
        return {
            "row_count": int(row[0] or 0),
            "latest_time": row[1],
            "expected_symbols": expected_symbols,
            "covered_symbols": int(row[2] or 0),
            "expected_buckets": expected_buckets,
            "observed_buckets": int(row[3] or 0),
            "duplicate_rows": int(row[4] or 0),
            "max_gap_seconds": max_gap_seconds,
        }

    def _health_snapshot_metrics(self, *, trade_date: date) -> dict[str, Any]:
        rows = self.client.execute(
            """
            select
                count() as row_count,
                max(checked_at) as latest_time,
                countIf(ok = 1) as ok_checks,
                countIf(ok = 0) as failed_checks
            from data_source_health
            where toDate(checked_at) = %(trade_date)s
            """,
            {"trade_date": trade_date},
        )
        row = rows[0] if rows else (0, None, 0, 0)
        row_count = int(row[0] or 0)
        return {
            "row_count": row_count,
            "latest_time": row[1],
            "expected_symbols": 0,
            "covered_symbols": int(row[2] or 0),
            "expected_buckets": 1,
            "observed_buckets": 1 if row_count > 0 else 0,
            "duplicate_rows": int(row[3] or 0),
            "max_gap_seconds": 0,
        }

    def _max_gap_seconds(self, *, table: str, time_col: str, trade_date: date) -> int:
        try:
            rows = self.client.execute(
                f"""
                select {time_col}
                from {table}
                where toDate({time_col}) = %(trade_date)s
                group by {time_col}
                order by {time_col}
                """,
                {"trade_date": trade_date},
            )
        except Exception:
            return 0
        timestamps = [_coerce_datetime(row[0]) for row in rows]
        session_times = [value for value in timestamps if value is not None and _is_market_session(value.time())]
        if len(session_times) < 2:
            return 0
        gaps = []
        for previous, current in zip(session_times, session_times[1:]):
            if previous.time() <= time(11, 30) and current.time() >= time(13, 0):
                continue
            gaps.append(int((current - previous).total_seconds()))
        return max(gaps) if gaps else 0


def _selected_source_keys(source_keys: list[str] | None) -> list[str]:
    selected = source_keys or list(QUALITY_SOURCE_KEYS)
    return [key for key in selected if key in QUALITY_SOURCES]


def _status_from_metrics(
    *,
    expected_symbols: int,
    covered_symbols: int,
    expected_buckets: int,
    observed_buckets: int,
    duplicate_rows: int,
    source_key: str,
) -> str:
    if observed_buckets == 0 or (expected_symbols > 0 and covered_symbols == 0):
        return "failed"
    missing_buckets = max(0, expected_buckets - observed_buckets)
    coverage = _coverage_ratio(covered_symbols, expected_symbols)
    if duplicate_rows > 0 or missing_buckets > 0 or coverage < 0.98:
        return "warning"
    return "ok"


def _coverage_ratio(covered: int, expected: int) -> float:
    if expected <= 0:
        return 1.0
    return round(max(0.0, min(1.0, covered / expected)), 4)


def _summary(
    *,
    covered_symbols: int,
    expected_symbols: int,
    missing_buckets: int,
    duplicate_rows: int,
    max_gap_seconds: int,
) -> str:
    parts = [f"覆盖 {covered_symbols}/{expected_symbols}" if expected_symbols else f"检查 {covered_symbols} 项"]
    if missing_buckets:
        parts.append(f"缺桶 {missing_buckets}")
    if duplicate_rows:
        parts.append(f"重复/失败 {duplicate_rows}")
    if max_gap_seconds:
        parts.append(f"最大断档 {max_gap_seconds}s")
    return "，".join(parts)


def _cell_from_row(row: Any) -> dict[str, Any]:
    return {
        "source_key": str(row[1]),
        "source_name": str(row[2]),
        "status": str(row[3]),
        "latest_time": _format_datetime(row[4]),
        "expected_symbols": int(row[5] or 0),
        "covered_symbols": int(row[6] or 0),
        "coverage_ratio": float(row[7] or 0),
        "expected_buckets": int(row[8] or 0),
        "observed_buckets": int(row[9] or 0),
        "missing_buckets": int(row[10] or 0),
        "duplicate_rows": int(row[11] or 0),
        "max_gap_seconds": int(row[12] or 0),
        "repairability": str(row[13] or ""),
        "summary": str(row[14] or ""),
        "details": _json_details(row[15]),
        "checked_at": _format_datetime(row[16]),
    }


def _unchecked_cell(source_key: str) -> dict[str, Any]:
    source = QUALITY_SOURCES[source_key]
    return {
        "source_key": source.key,
        "source_name": source.name,
        "status": "unchecked",
        "latest_time": None,
        "expected_symbols": 0,
        "covered_symbols": 0,
        "coverage_ratio": 0.0,
        "expected_buckets": 0,
        "observed_buckets": 0,
        "missing_buckets": 0,
        "duplicate_rows": 0,
        "max_gap_seconds": 0,
        "repairability": source.repairability,
        "summary": "未检查",
        "details": {"table": source.table, "expected_cadence": source.expected_cadence},
        "checked_at": None,
    }


def _overall_status(statuses: list[str]) -> str:
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status in {"warning", "catching_up"} for status in statuses):
        return "warning"
    if statuses and all(status == "unchecked" for status in statuses):
        return "unchecked"
    if any(status == "unchecked" for status in statuses):
        return "warning"
    return "ok"


def _latest_checked_at(cells: list[dict[str, Any]]) -> str | None:
    checked = [str(cell["checked_at"]) for cell in cells if cell.get("checked_at")]
    return max(checked) if checked else None


def _json_details(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time())
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _format_date(value: Any) -> str:
    parsed = _coerce_date(value)
    return parsed.isoformat() if parsed else str(value)


def _format_datetime(value: Any) -> str | None:
    parsed = _coerce_datetime(value)
    return parsed.isoformat(sep=" ", timespec="seconds") if parsed else None


def _is_market_session(value: time) -> bool:
    return time(9, 30) <= value <= time(11, 30) or time(13, 0) <= value <= time(15, 0)
