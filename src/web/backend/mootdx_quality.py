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

    def xdxr_quality(
        self,
        *,
        limit: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Return Mootdx XDXR run health separately from fact-table coverage."""
        clauses = ["task_key = 'xdxr'"]
        params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if start_date is not None:
            clauses.append("started_at >= %(start_date)s")
            params["start_date"] = start_date
        if end_date is not None:
            clauses.append("started_at < %(end_date)s + interval 1 day")
            params["end_date"] = end_date
        if status:
            clauses.append("status = %(status)s")
            params["status"] = status
        runs = self._query(
            "select run_id, started_at, finished_at, status, result_json, error "
            "from mootdx_sync_runs where " + " and ".join(clauses) + " "
            "order by started_at desc limit %(limit)s",
            params,
        )
        run_records = [_xdxr_run_record(row) for row in runs]
        fact_rows = self._query(
            "select uniqExact(symbol), count(), max(observed_at), countIf(isNull(suogu)) "
            "from mootdx_xdxr_current"
        )
        return {
            "latest_run": run_records[0] if run_records else None,
            "runs": run_records,
            "data_summary": _xdxr_data_summary(fact_rows),
        }

    def xdxr_run_detail(
        self,
        run_id: str,
        *,
        status: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any] | None:
        """Return one XDXR run and its per-symbol Mootdx audit records."""
        run_rows = self._query(
            "select run_id, started_at, finished_at, status, result_json, error "
            "from mootdx_sync_runs where run_id = %(run_id)s and task_key = 'xdxr' "
            "order by started_at desc limit 1",
            {"run_id": run_id},
        )
        if not run_rows:
            return None
        run = _xdxr_run_record(run_rows[0])
        clauses = ["run_id = %(run_id)s"]
        params: dict[str, Any] = {"run_id": run_id, "limit": max(1, min(limit, 1000))}
        if status:
            clauses.append("status = %(status)s")
            params["status"] = status
        rows = self._query(
            "select symbol, status, event_rows, request_ms, parse_ms, error, raw_columns "
            "from mootdx_xdxr_symbol_runs final where " + " and ".join(clauses) + " "
            "order by symbol asc limit %(limit)s",
            params,
        )
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "duration_seconds": run["duration_seconds"],
            "request_seconds": run["request_seconds"],
            "parse_seconds": run["parse_seconds"],
            # XDXR synchronization currently does not persist this timing.  Keep the
            # explicit null contract so clients never mistake an inferred value for it.
            "write_seconds": run["write_seconds"],
            "error": run["error"],
            "summary": _xdxr_run_summary(run),
            "items": [_xdxr_symbol_run(row) for row in rows],
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
                verification_by_date = {
                    trade_date: verification_by_symbol.get((symbol, trade_date), "")
                    for trade_date in block
                }
                classification, recommendation, evidence = _classify_missing_block(
                    symbol=symbol,
                    block=block,
                    actual_by_date=actual_by_date,
                    trade_dates=trade_dates,
                    date_positions=date_positions,
                    status=values.get("status", "unknown"),
                    verification_by_date=verification_by_date,
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
                    "verification_by_date": {
                        trade_date.isoformat(): verdict
                        for trade_date, verdict in verification_by_date.items()
                    },
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


def _xdxr_run_record(row: tuple) -> dict[str, Any]:
    result = _json_object(row[4] if len(row) > 4 else {})
    diagnostics = _xdxr_diagnostics(result)
    return {
        "run_id": str(row[0]),
        "started_at": _iso(row[1]),
        "finished_at": _iso(row[2]),
        "duration_seconds": _xdxr_duration_seconds(result, row[1], row[2]),
        "status": str(row[3]),
        "error": str(row[5] or "") if len(row) > 5 else "",
        "target_symbols": _xdxr_int(diagnostics, "target_symbols"),
        "requested_symbols": _xdxr_int(diagnostics, "requested_symbols"),
        "success_symbols": _xdxr_int(diagnostics, "success_symbols"),
        "empty_symbols": _xdxr_int(diagnostics, "empty_symbols_count"),
        "error_symbols": _xdxr_int(diagnostics, "failed_symbols_count"),
        "event_rows": _xdxr_int(diagnostics, "event_rows"),
        "request_seconds": _xdxr_float(diagnostics, "request_seconds"),
        "parse_seconds": _xdxr_float(diagnostics, "parse_seconds"),
        "write_seconds": None,
        "circuit_breaker_triggered": bool(diagnostics.get("circuit_breaker_triggered", False)),
        "failed_symbols_sample": _xdxr_failed_symbols_sample(diagnostics.get("failed_symbols_sample")),
    }


def _xdxr_duration_seconds(result: dict[str, Any], started_at: Any, finished_at: Any) -> float | None:
    value = result.get("duration_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return _duration_seconds(started_at, finished_at)


def _duration_seconds(started_at: Any, finished_at: Any) -> float | None:
    if not isinstance(started_at, datetime) or not isinstance(finished_at, datetime):
        return None
    return max(0.0, round((finished_at - started_at).total_seconds(), 3))


def _xdxr_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    xdxr = diagnostics.get("xdxr")
    return xdxr if isinstance(xdxr, dict) else {}


def _xdxr_int(values: dict[str, Any], key: str) -> int:
    try:
        return int(values.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _xdxr_float(values: dict[str, Any], key: str) -> float:
    try:
        return float(values.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _xdxr_failed_symbols_sample(value: Any) -> list[str]:
    """Normalize persisted audit samples without exposing arbitrary JSON values."""
    if not isinstance(value, list):
        return []
    symbols: list[str] = []
    for item in value:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if not isinstance(symbol, str) or not symbol:
            continue
        symbols.append(symbol)
    return symbols


def _xdxr_data_summary(rows: list[tuple]) -> dict[str, Any]:
    if not rows:
        return {"symbols": 0, "events": 0, "latest_ingested_at": None, "null_suogu": 0}
    row = rows[0]
    return {
        "symbols": int(row[0] or 0),
        "events": int(row[1] or 0),
        "latest_ingested_at": _iso(row[2]),
        "null_suogu": int(row[3] or 0),
    }


def _xdxr_run_summary(run: dict[str, Any]) -> dict[str, int]:
    return {
        "requested_symbols": int(run["requested_symbols"]),
        "success_symbols": int(run["success_symbols"]),
        "empty_symbols": int(run["empty_symbols"]),
        "error_symbols": int(run["error_symbols"]),
        "event_rows": int(run["event_rows"]),
    }


def _xdxr_symbol_run(row: tuple) -> dict[str, Any]:
    return {
        "symbol": str(row[0]),
        "status": str(row[1]),
        "event_rows": int(row[2] or 0),
        "request_ms": float(row[3]) if row[3] is not None else None,
        "parse_ms": float(row[4]) if row[4] is not None else None,
        "error": str(row[5] or ""),
        "raw_columns": list(row[6] or []),
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
