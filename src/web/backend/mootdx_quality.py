"""Detailed quality snapshots for mootdx catalog and daily kline data."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from src.data.clickhouse_source import ClickHouseStockDataSource


class MootdxQualityService:
    def __init__(self, *, client: Any | None = None, job_store: Any | None = None) -> None:
        self._client = client
        self._job_store = job_store

    def catalog_quality(self, *, event_limit: int = 200) -> dict[str, Any]:
        summary_rows = self._query(
            "select count(), countIf(market = 0), countIf(market = 1), countIf(market = 2), "
            "countIf(is_st = 1), max(captured_at) from mootdx_stock_catalog final where is_active = 1"
        )
        daily_rows = self._query(
            "select toDate(event_at), event_type, count() from mootdx_catalog_change_events "
            "group by toDate(event_at), event_type order by toDate(event_at) desc, event_type"
        )
        return {
            "summary": _catalog_summary(summary_rows),
            "daily_changes": _daily_change_rows(daily_rows),
            "events": self.catalog_change_events(limit=event_limit),
            "universe_profile": self.universe_profile_quality(),
        }

    def catalog_change_events(
        self,
        *,
        event_date: date | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        if event_date is not None:
            clauses.append("toDate(event_at) = %(event_date)s")
            params["event_date"] = event_date
        if event_type:
            clauses.append("event_type = %(event_type)s")
            params["event_type"] = event_type
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = self._query(
            "select event_at, symbol, event_type, previous_json, current_json, run_id "
            f"from mootdx_catalog_change_events {where} order by event_at desc, symbol asc limit %(limit)s",
            params,
        )
        return [_catalog_event(row) for row in rows]

    def universe_profile_quality(self, *, filters: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        where, params = _profile_filter_sql(filters or [])
        summary_rows = self._query(
            "select max(as_of_date), max(computed_at), max(rule_version), count(), countIf(catalog_valid = 1), "
            "countIf(latest_daily_valid = 1), countIf(liquidity_qualified = 1), countIf(universe_eligible = 1) "
            f"from stock_universe_profiles final {where}",
            params,
        )
        distributions = {
            "markets": self._profile_distribution("market", where, params),
            "liquidity_levels": self._profile_distribution("liquidity_level", where, params),
            "exclusion_reasons": self._exclusion_distribution(where, params),
            "exclusion_reason_markets": self._exclusion_reason_market_distribution(where, params),
        }
        if not summary_rows:
            return {"status": "unavailable", "summary": _empty_profile_summary(), "distributions": distributions}
        row = summary_rows[0]
        return {
            "status": "healthy" if int(row[3] or 0) else "unavailable",
            "summary": {
                "as_of_date": _iso(row[0]),
                "computed_at": _iso(row[1]),
                "rule_version": int(row[2] or 0),
                "symbols": int(row[3] or 0),
                "catalog_valid": int(row[4] or 0),
                "latest_daily_valid": int(row[5] or 0),
                "liquidity_qualified": int(row[6] or 0),
                "universe_eligible": int(row[7] or 0),
            },
            "distributions": distributions,
        }

    def universe_profiles(self, *, filters: list[dict[str, Any]] | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        where, params = _profile_filter_sql(filters or [])
        total_rows = self._query(f"select count() from stock_universe_profiles final {where}", params)
        params.update({"limit": max(1, min(limit, 500)), "offset": max(0, offset)})
        rows = self._query(
            "select p.symbol, c.name, p.market, p.is_st, p.list_date, p.listing_age_days, p.latest_daily_valid, p.recent_20d_trading_days, "
            "p.recent_20d_avg_amount, p.liquidity_level, p.universe_eligible, p.exclusion_reasons, p.as_of_date, p.computed_at, p.rule_version "
            f"from (select * from stock_universe_profiles final {where}) as p left join "
            "(select symbol, argMax(name, captured_at) as name from mootdx_stock_catalog group by symbol) as c on c.symbol = p.symbol "
            "order by p.universe_eligible desc, p.recent_20d_avg_amount desc, p.symbol asc limit %(limit)s offset %(offset)s",
            params,
        )
        return {
            "profile": self.universe_profile_quality(filters=filters),
            "total": int(total_rows[0][0] or 0) if total_rows else 0,
            "items": [
                {
                    "symbol": str(row[0]), "name": str(row[1] or ""), "market": str(row[2]), "is_st": bool(row[3]), "list_date": _iso(row[4]),
                    "listing_age_days": int(row[5]), "latest_daily_valid": bool(row[6]), "recent_20d_trading_days": int(row[7]),
                    "recent_20d_avg_amount": float(row[8]), "liquidity_level": str(row[9]), "universe_eligible": bool(row[10]),
                    "exclusion_reasons": list(row[11] or []), "as_of_date": _iso(row[12]), "computed_at": _iso(row[13]),
                    "rule_version": int(row[14]),
                }
                for row in rows
            ]
        }

    def _profile_distribution(self, field: str, where: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._query(
            f"select {field}, count() from stock_universe_profiles final {where} group by {field} order by count() desc, {field}",
            params,
        )
        return [{"key": str(row[0]), "count": int(row[1])} for row in rows]

    def _exclusion_distribution(self, where: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._query(
            "select reason, count() from stock_universe_profiles final array join exclusion_reasons as reason "
            f"{where} group by reason order by count() desc, reason",
            params,
        )
        return [{"key": str(row[0]), "count": int(row[1])} for row in rows]

    def _exclusion_reason_market_distribution(self, where: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._query(
            "select reason, market, count() from stock_universe_profiles final array join exclusion_reasons as reason "
            f"{where} group by reason, market order by count() desc, reason, market",
            params,
        )
        return [{"reason": str(row[0]), "market": str(row[1]), "count": int(row[2])} for row in rows]

    def daily_quality(self, *, lookback_days: int = 30, missing_limit: int = 200) -> dict[str, Any]:
        calendar_rows = self._query(
            "select date from trade_calendar where date <= (select max(trade_date) from mootdx_stock_kline where frequency = 'daily') "
            "order by date desc limit %(limit)s",
            {"limit": max(1, min(lookback_days, 180))},
        )
        trade_dates = sorted({_to_date(row[0]) for row in calendar_rows if _to_date(row[0]) is not None})
        if not trade_dates:
            return _empty_daily_quality()
        catalog_rows = self._query(
            "select c.symbol, toDateOrNull(nullIf(s.list_date, '')) from (select * from mootdx_stock_catalog final) AS c "
            "left join stocks s on s.symbol = splitByChar('.', c.symbol)[1] "
            "where c.market in (0, 1) and c.is_st = 0 and c.is_active = 1"
        )
        daily_rows = self._query(
            "select trade_date, groupUniqArray(symbol) from mootdx_stock_kline "
            "where frequency = 'daily' and trade_date in %(trade_dates)s group by trade_date",
            {"trade_dates": tuple(trade_dates)},
        )
        first_rows = self._query(
            "select symbol, min(trade_date) from mootdx_stock_kline "
            "where frequency = 'daily' group by symbol"
        )
        status_rows = self._query(
            "select symbol, argMax(status, last_checked_at), argMax(reason, last_checked_at), "
            "argMax(consecutive_failures, last_checked_at), argMax(last_checked_at, last_checked_at) "
            "from mootdx_symbol_data_status where data_kind = 'stock_kline_daily' group by symbol"
        )
        verification_rows = self._query(
            "select symbol, trade_date, argMax(verdict, verified_at) "
            "from mootdx_daily_gap_verifications where frequency = 'daily' group by symbol, trade_date"
        )
        first_seen = {str(row[0]): _to_date(row[1]) for row in first_rows if _to_date(row[1]) is not None}
        listing_dates = {
            str(row[0]): _to_date(row[1]) or first_seen.get(str(row[0]))
            for row in catalog_rows
        }
        actual_by_date: dict[date, set[str]] = {trade_date: set() for trade_date in trade_dates}
        for row in daily_rows:
            trade_date = _to_date(row[0])
            if trade_date in actual_by_date:
                actual_by_date[trade_date].update(str(symbol) for symbol in (row[1] or []))
        status_by_symbol = {
            str(row[0]): {
                "status": str(row[1]),
                "reason": str(row[2]),
                "consecutive_failures": int(row[3]),
            }
            for row in status_rows
        }
        verification_by_symbol = {
            (str(row[0]), _to_date(row[1])): str(row[2])
            for row in verification_rows
            if _to_date(row[1]) is not None
        }
        coverage = []
        coverage_by_date: dict[date, dict[str, Any]] = {}
        missing_by_symbol: dict[str, list[date]] = {}
        for trade_date in trade_dates:
            expected = {symbol for symbol, list_date in listing_dates.items() if list_date is not None and list_date <= trade_date}
            actual = actual_by_date[trade_date] & expected
            missing = expected - actual
            for symbol in missing:
                missing_by_symbol.setdefault(symbol, []).append(trade_date)
            row = {
                "trade_date": trade_date.isoformat(),
                "expected_symbols": len(expected),
                "actual_symbols": len(actual),
                "missing_symbols": len(missing),
                "completeness_rate": round(len(actual) / len(expected), 4) if expected else 1.0,
                "gap_counts": {},
            }
            coverage.append(row)
            coverage_by_date[trade_date] = row
        latest = coverage[-1]
        status_counts: dict[str, int] = {}
        for values in status_by_symbol.values():
            status_counts[values["status"]] = status_counts.get(values["status"], 0) + 1
        missing_details = []
        gap_counts: dict[str, int] = {}
        reviewed_no_repair = _reviewed_no_repair_gaps(self._job_store)
        date_positions = {trade_date: index for index, trade_date in enumerate(trade_dates)}
        for symbol, missing_dates in missing_by_symbol.items():
            values = status_by_symbol.get(symbol) or {}
            for block in _missing_date_blocks(missing_dates, date_positions):
                classification, recommendation, evidence = _classify_missing_block(
                    symbol=symbol,
                    block=block,
                    actual_by_date=actual_by_date,
                    trade_dates=trade_dates,
                    date_positions=date_positions,
                    status=values.get("status", "unknown"),
                    verification_by_date={
                        trade_date: verification_by_symbol.get((symbol, trade_date), "")
                        for trade_date in block
                    },
                )
                review_reason = reviewed_no_repair.get(_gap_key(symbol, block))
                if review_reason:
                    classification, recommendation, evidence = "reviewed_no_repair", "无需回补", f"人工核验：{review_reason}"
                gap_counts[classification] = gap_counts.get(classification, 0) + 1
                for trade_date in block:
                    counts = coverage_by_date[trade_date]["gap_counts"]
                    counts[classification] = counts.get(classification, 0) + 1
                missing_details.append({
                    "symbol": symbol,
                    "missing_dates": [value.isoformat() for value in block],
                    "list_date": listing_dates[symbol].isoformat() if listing_dates[symbol] else None,
                    "status": values.get("status", "unknown"),
                    "reason": values.get("reason", ""),
                    "consecutive_failures": values.get("consecutive_failures", 0),
                    "classification": classification,
                    "recommendation": recommendation,
                    "evidence": evidence,
                })
        missing_details.sort(key=lambda row: (_gap_priority(row["classification"]), row["symbol"], row["missing_dates"][0]))
        return {
            "summary": {
                "status": _daily_health_status(latest["completeness_rate"]),
                "latest_trade_date": latest["trade_date"],
                "expected_symbols": latest["expected_symbols"],
                "actual_symbols": latest["actual_symbols"],
                "completeness_rate": latest["completeness_rate"],
                "missing_symbols": latest["missing_symbols"],
                "status_counts": status_counts,
                "gap_counts": gap_counts,
            },
            "daily_coverage": coverage,
            "missing_details": missing_details[:max(1, min(missing_limit, 1000))],
        }

    def _query(self, query: str, params: dict[str, Any] | None = None) -> list[tuple]:
        try:
            return self._clickhouse().execute(query, params)
        except Exception:  # noqa: BLE001 - individual quality sections are represented as unavailable.
            return []

    def _clickhouse(self) -> Any:
        if self._client is None:
            self._client = ClickHouseStockDataSource()._client_instance()
        return self._client


def _catalog_summary(rows: list[tuple]) -> dict[str, Any]:
    if not rows:
        return {"status": "unavailable", "symbols": 0, "markets": {}, "st_symbols": 0, "captured_at": None}
    row = rows[0]
    symbols = int(row[0])
    return {
        "status": "healthy" if symbols else "failed",
        "symbols": symbols,
        "markets": {"SZ": int(row[1]), "SH": int(row[2]), "BJ": int(row[3])},
        "st_symbols": int(row[4]),
        "captured_at": _iso(row[5]),
    }


def _catalog_event(row: tuple) -> dict[str, Any]:
    return {
        "event_at": _iso(row[0]),
        "symbol": str(row[1]),
        "event_type": str(row[2]),
        "previous": _json_object(row[3]),
        "current": _json_object(row[4]),
        "run_id": str(row[5]),
    }


def _empty_daily_quality() -> dict[str, Any]:
    return {
        "summary": {
            "status": "unavailable",
            "latest_trade_date": None,
            "expected_symbols": 0,
            "actual_symbols": 0,
            "completeness_rate": 0.0,
            "missing_symbols": 0,
            "status_counts": {},
            "gap_counts": {},
        },
        "daily_coverage": [],
        "missing_details": [],
    }


def _empty_profile_summary() -> dict[str, Any]:
    return {
        "as_of_date": None,
        "computed_at": None,
        "rule_version": 0,
        "symbols": 0,
        "catalog_valid": 0,
        "latest_daily_valid": 0,
        "liquidity_qualified": 0,
        "universe_eligible": 0,
    }


def _profile_filter_sql(filters: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    allowed = {
        "market": "market",
        "is_st": "is_st",
        "latest_daily_valid": "latest_daily_valid",
        "liquidity_level": "liquidity_level",
        "universe_eligible": "universe_eligible",
        "listing_age": "multiIf(listing_age_days < 365, 'lt_1y', listing_age_days < 1095, '1_3y', 'gte_3y')",
        "trading_days": "multiIf(recent_20d_trading_days < 15, 'lt_15', 'gte_15')",
        "average_amount": "multiIf(recent_20d_avg_amount < 10000000, 'lt_10m', recent_20d_avg_amount < 50000000, '10_50m', 'gte_50m')",
    }
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for index, item in enumerate(filters):
        field = str(item.get("field") or "")
        values = item.get("values")
        if not isinstance(values, list) or not values:
            continue
        if field == "exclusion_reason":
            key = f"filter_{index}"
            clauses.append(f"hasAny(exclusion_reasons, %({key})s)")
            params[key] = [str(value) for value in values]
            continue
        if field == "reason_market":
            key = f"filter_{index}"
            clauses.append(f"hasAny(arrayMap(reason -> concat(reason, '::', market), exclusion_reasons), %({key})s)")
            params[key] = [str(value) for value in values]
            continue
        if field not in allowed:
            continue
        key = f"filter_{index}"
        clauses.append(f"{allowed[field]} in %({key})s")
        params[key] = tuple(int(value) if field in {"is_st", "latest_daily_valid", "universe_eligible"} else value for value in values)
    return ("where " + " and ".join(clauses)) if clauses else "", params


def _daily_health_status(completeness_rate: float) -> str:
    if completeness_rate < 0.98:
        return "failed"
    if completeness_rate < 0.995:
        return "degraded"
    return "healthy"


def _missing_date_blocks(missing_dates: list[date], date_positions: dict[date, int]) -> list[list[date]]:
    blocks: list[list[date]] = []
    for trade_date in sorted(missing_dates, key=date_positions.__getitem__):
        if not blocks or date_positions[trade_date] != date_positions[blocks[-1][-1]] + 1:
            blocks.append([trade_date])
        else:
            blocks[-1].append(trade_date)
    return blocks


def _classify_missing_block(
    *,
    symbol: str,
    block: list[date],
    actual_by_date: dict[date, set[str]],
    trade_dates: list[date],
    date_positions: dict[date, int],
    status: str,
    verification_by_date: dict[date, str] | None = None,
) -> tuple[str, str, str]:
    verdicts = set((verification_by_date or {}).values()) - {""}
    if block and all((verification_by_date or {}).get(value) == "no_data" for value in block):
        return "known_no_data", "无需回补", "Baostock 已确认该缺口区间无交易记录"
    if "error" in verdicts:
        return "needs_review", "待核验", "Baostock 核验请求失败，不能判定为无数据"
    if "available" in verdicts:
        return "repair_candidate", "建议回补", "Baostock 已确认缺口日期存在日线数据"
    if status == "no_data":
        return "known_no_data", "无需回补", "数据源已确认无日线数据"
    start = date_positions[block[0]]
    end = date_positions[block[-1]]
    if start == 0 or end == len(trade_dates) - 1:
        return "needs_review", "待核验", "缺口位于窗口边界，无法验证前后日线"
    previous_date = trade_dates[start - 1]
    next_date = trade_dates[end + 1]
    if symbol in actual_by_date[previous_date] and symbol in actual_by_date[next_date]:
        return "repair_candidate", "建议回补", "缺口前后交易日均有日线记录"
    return "needs_review", "待核验", "现有数据不足以区分停牌与同步缺失"


def _gap_priority(classification: str) -> int:
    return {"repair_candidate": 0, "needs_review": 1, "known_no_data": 2, "reviewed_no_repair": 3}.get(classification, 4)


def _gap_key(symbol: str, block: list[date]) -> str:
    return f"{symbol}|{block[0].isoformat()}|{block[-1].isoformat()}"


def _reviewed_no_repair_gaps(job_store: Any | None) -> dict[str, str]:
    if job_store is None:
        return {}
    try:
        jobs = job_store.list_jobs(limit=1000)
    except Exception:  # noqa: BLE001 - quality inspection must not fail when job history is unavailable.
        return {}
    decisions = {}
    for job in jobs:
        if job.kind != "mootdx_daily_gap_review" or job.status != "success":
            continue
        params = job.params
        start = _to_date(params.get("start_date"))
        end = _to_date(params.get("end_date"))
        symbol = str(params.get("symbol") or "")
        if symbol and start and end:
            decisions[_gap_key(symbol, [start, end])] = str(params.get("reason") or "人工确认无需回补")
    return decisions


def _daily_change_rows(rows: list[tuple]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for value, event_type, count in rows:
        day = _date_iso(value)
        by_date.setdefault(day, {"date": day})[str(event_type)] = int(count)
    return list(by_date.values())


def _date_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
