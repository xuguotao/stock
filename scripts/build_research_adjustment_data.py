#!/usr/bin/env python3
"""Build versioned, fail-closed research adjustment candidates from Mootdx.

The default calculator reads isolated Mootdx daily bars and XDXR records.  It
is also injectable for deterministic formula tests without accessing ClickHouse.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.research_adjustment_events import daily_ratio  # noqa: E402
from src.data.research_adjustment_store import ResearchAdjustmentStore  # noqa: E402
from src.data.research_adjustment_validation import build_daily_factors, validate_event  # noqa: E402


CandidateBuilder = Callable[..., Mapping[str, Sequence[Mapping[str, Any]]]]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build versioned, research-only adjustment candidates.")
    parser.add_argument("--symbols", type=_csv_list, default=None, help="Comma-separated explicit symbols.")
    parser.add_argument("--formula-version", default="v1", help="Published adjustment formula version.")
    parser.add_argument("--full", action="store_true", help="Rebuild all symbols; default builds only changed symbols.")
    return parser.parse_args(argv)


def build_research_adjustment_data(
    *,
    symbols: Sequence[str] | None = None,
    formula_version: str = "v1",
    full: bool = False,
    store: ResearchAdjustmentStore | Any | None = None,
    client: Any | None = None,
    candidate_builder: CandidateBuilder | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Write a complete candidate and only then publish it.

    The default builder reads Mootdx's isolated raw daily and XDXR tables.
    An injected builder remains available for deterministic formula tests.
    """
    active_store = store or ResearchAdjustmentStore(client=client)
    builder = candidate_builder or _build_candidates_from_mootdx
    input_client = client if client is not None else getattr(active_store, "client", None)
    if candidate_builder is None and input_client is None:
        raise RuntimeError("Mootdx raw-data client is required to build adjustment candidates")
    current = active_store.current_run(formula_version)
    input_watermark = None
    if candidate_builder is None:
        if current is not None and not full and current.get("input_watermark") is None:
            raise ValueError("incremental build requires a published input watermark; rerun with --full")
        input_watermark = _capture_input_watermark(input_client)
    candidate = builder(
        symbols=list(symbols) if symbols else None,
        formula_version=formula_version,
        full=full,
        client=input_client,
        store=active_store,
        current=current,
        input_watermark=input_watermark,
    )
    events = list(candidate.get("events", []))
    factors = list(candidate.get("factors", []))
    if not factors:
        return {"run_id": None, "event_count": 0, "factor_count": 0, "published": False}
    run_id = (run_id_factory or (lambda: str(uuid.uuid4())))()
    active_store.ensure_tables()
    written_events = active_store.write_candidate_events(run_id, formula_version, events)
    written_factors = active_store.write_candidate_factors(run_id, formula_version, factors)
    active_store.publish_run(
        run_id=run_id,
        formula_version=formula_version,
        completed=True,
        expected_event_count=written_events,
        expected_factor_count=written_factors,
        input_watermark=input_watermark,
        base_run_id=current["run_id"] if current is not None else None,
    )
    return {"run_id": run_id, "event_count": written_events, "factor_count": written_factors}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_research_adjustment_data(
            symbols=args.symbols, formula_version=args.formula_version, full=args.full
        )
    except (RuntimeError, ValueError, OSError, ConnectionError) as exc:
        print(f"research adjustment build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_candidates_from_mootdx(
    *,
    symbols: list[str] | None,
    formula_version: str,
    full: bool,
    client: Any,
    store: Any,
    current: Mapping[str, Any] | None = None,
    input_watermark: datetime | None = None,
) -> Mapping[str, Sequence[Mapping[str, Any]]]:
    """Build a complete factor snapshot from raw Mootdx inputs.

    Default incremental scope is the union of symbols with XDXR or daily-bar
    ``ingested_at`` updates after the prior publication.  Their complete
    histories are rebuilt, while unchanged symbols' prior factor rows are
    copied into the candidate.  Before a first publication, and with ``--full``,
    all available daily symbols are built.  An empty incremental scope is a
    successful no-op and is deliberately not published.
    """
    current = current if current is not None else store.current_run(formula_version)
    if current is None and symbols and not full:
        raise ValueError("initial research adjustment publication requires --full to create a complete snapshot")
    target_symbols = _default_symbols(client, current, True, input_watermark) if full else (
        symbols or _default_symbols(client, current, False, input_watermark)
    )
    if not target_symbols:
        return {"events": [], "factors": []}
    # Event audit rows describe only this run's recomputed symbols.  Factor rows
    # are a complete snapshot because unchanged symbols are copied below.
    daily_bars = _daily_bars(client, target_symbols, input_watermark)
    built = _validate_and_factor(daily_bars, _xdxr_events(client, target_symbols, input_watermark))
    _assert_target_factor_coverage(target_symbols, daily_bars, built["factors"])
    if current is None or full:
        return built
    targets = set(target_symbols)
    retained = [
        row for row in _prior_factor_rows(client, current["run_id"], formula_version)
        if str(row["symbol"]) not in targets
    ]
    retained_events = [
        row for row in _prior_event_rows(client, current["run_id"], formula_version)
        if str(row["symbol"]) not in targets
    ]
    return {"events": [*retained_events, *built["events"]], "factors": [*retained, *built["factors"]]}


def _capture_input_watermark(client: Any) -> datetime | None:
    """Capture one upper bound for the union of daily and XDXR ingestions.

    Every incremental source query uses the persisted prior bound exclusively
    below this value and this captured bound inclusively above it.  A row that
    arrives after the capture is therefore deferred to the next run rather
    than being half-included in this candidate snapshot.
    """
    rows = client.execute(
        """
        select max(ingested_at)
        from (
            select ingested_at from mootdx_stock_kline final where frequency = 'daily'
            union all
            select ingested_at from mootdx_xdxr final
        )
        """
    )
    return _as_datetime(rows[0][0]) if rows and rows[0][0] is not None else None


def _default_symbols(
    client: Any, current: Mapping[str, Any] | None, full: bool, input_watermark: datetime | None
) -> list[str]:
    if full or current is None:
        if input_watermark is None:
            return []
        rows = client.execute(
            """select distinct symbol from mootdx_stock_kline final
            where frequency = 'daily' and ingested_at <= %(captured_input_watermark)s
            order by symbol""",
            {"captured_input_watermark": input_watermark},
        )
        return [str(row[0]) for row in rows]
    if input_watermark is None:
        return []
    params = {
        "previous_input_watermark": current["input_watermark"],
        "captured_input_watermark": input_watermark,
    }
    xdxr_rows = client.execute(
        """select distinct symbol from mootdx_xdxr final
        where ingested_at > %(previous_input_watermark)s
          and ingested_at <= %(captured_input_watermark)s order by symbol""", params
    )
    daily_rows = client.execute(
        """
        select distinct symbol from mootdx_stock_kline final
        where frequency = 'daily' and ingested_at > %(previous_input_watermark)s
          and ingested_at <= %(captured_input_watermark)s
        order by symbol
        """,
        params,
    )
    return sorted({str(row[0]) for row in [*xdxr_rows, *daily_rows]})


def _prior_factor_rows(client: Any, run_id: str, formula_version: str) -> list[dict[str, Any]]:
    rows = client.execute(
        """
        select symbol, trade_date, forward_factor, backward_factor,
               eligible_event_count, excluded_event_count, quality_status
        from research_daily_adjustment_factors final
        where run_id = %(run_id)s and formula_version = %(formula_version)s
        """,
        {"run_id": run_id, "formula_version": formula_version},
    )
    fields = (
        "symbol", "trade_date", "forward_factor", "backward_factor",
        "eligible_event_count", "excluded_event_count", "quality_status",
    )
    return [{field: value for field, value in zip(fields, row)} for row in rows]


def _prior_event_rows(client: Any, run_id: str, formula_version: str) -> list[dict[str, Any]]:
    rows = client.execute(
        """
        select symbol, event_date, category, event_name, validation_status, ratio,
               theoretical_price, pre_close, ex_close, validation_error, event_payload
        from research_adjustment_events final
        where run_id = %(run_id)s and formula_version = %(formula_version)s
        """,
        {"run_id": run_id, "formula_version": formula_version},
    )
    fields = (
        "symbol", "event_date", "category", "event_name", "validation_status", "ratio",
        "theoretical_price", "pre_close", "ex_close", "validation_error", "event_payload",
    )
    return [
        {
            **{field: value for field, value in zip(fields, row)},
            "status": row[4],
            "name": row[3],
            "error": row[9],
        }
        for row in rows
    ]


def _daily_bars(
    client: Any, symbols: Sequence[str], input_watermark: datetime | None
) -> dict[str, list[tuple[date, float]]]:
    rows = client.execute(
        """
        select symbol, trade_date, close
        from mootdx_stock_kline final
        where frequency = 'daily' and symbol in %(symbols)s
          and ingested_at <= %(captured_input_watermark)s
        order by symbol, trade_date
        """,
        {"symbols": tuple(symbols), "captured_input_watermark": input_watermark},
    )
    result: dict[str, list[tuple[date, float]]] = {}
    for symbol, trade_date, close in rows:
        try:
            close_value = float(close)
        except (TypeError, ValueError):
            continue
        result.setdefault(str(symbol), []).append((_as_date(trade_date), close_value))
    return result


def _xdxr_events(client: Any, symbols: Sequence[str], input_watermark: datetime | None) -> list[dict[str, Any]]:
    rows = client.execute(
        """
        select symbol, event_date, category, name, fenhong, peigujia,
               songzhuangu, peigu, suogu
        from mootdx_xdxr final
        where symbol in %(symbols)s
          and ingested_at <= %(captured_input_watermark)s
        order by symbol, event_date, category, name
        """,
        {"symbols": tuple(symbols), "captured_input_watermark": input_watermark},
    )
    fields = ("symbol", "event_date", "category", "name", "fenhong", "peigujia", "songzhuangu", "peigu", "suogu")
    return [{field: value for field, value in zip(fields, row)} for row in rows]


def _validate_and_factor(
    bars_by_symbol: Mapping[str, Sequence[tuple[date, float]]], raw_events: Sequence[Mapping[str, Any]]
) -> Mapping[str, Sequence[Mapping[str, Any]]]:
    events_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for raw_event in raw_events:
        event = dict(raw_event)
        event["event_date"] = _as_date(event["event_date"])
        events_by_symbol.setdefault(str(event["symbol"]), []).append(event)

    validated_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    for symbol, bars in bars_by_symbol.items():
        ordered_bars = sorted(bars)
        closes = {trade_date: close for trade_date, close in ordered_bars}
        symbol_events = events_by_symbol.get(symbol, [])
        for event in symbol_events:
            event_date = event["event_date"]
            prior_closes = [close for trade_date, close in ordered_bars if trade_date < event_date]
            outcome = validate_event(event, prior_closes[-1] if prior_closes else None, closes.get(event_date))
            event.update(
                status=outcome.status,
                ratio=outcome.ratio,
                theoretical_price=outcome.theoretical_price,
                pre_close=prior_closes[-1] if prior_closes else None,
                ex_close=closes.get(event_date),
                error=outcome.error,
            )
            validated_rows.append(event)
        by_date: dict[date, list[dict[str, Any]]] = {}
        for event in symbol_events:
            by_date.setdefault(event["event_date"], []).append(event)
        ratios = {event_date: daily_ratio(events) for event_date, events in by_date.items()}
        for trade_date, factors in build_daily_factors((day for day, _ in ordered_bars), ratios).items():
            day_events = by_date.get(trade_date, [])
            approved = sum(event["status"] == "approved" and event.get("category") == 1 for event in day_events)
            factor_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "forward_factor": factors.forward_factor,
                    "backward_factor": factors.backward_factor,
                    "eligible_event_count": approved,
                    "excluded_event_count": len(day_events) - approved,
                    "quality_status": "approved" if len(day_events) == approved else "unverified",
                }
            )
    return {"events": validated_rows, "factors": factor_rows}


def _assert_target_factor_coverage(
    target_symbols: Sequence[str], bars_by_symbol: Mapping[str, Sequence[tuple[date, float]]], factors: Sequence[Mapping[str, Any]]
) -> None:
    factor_dates: dict[str, set[date]] = {}
    for factor in factors:
        factor_dates.setdefault(str(factor["symbol"]), set()).add(_as_date(factor["trade_date"]))
    incomplete = []
    for symbol in target_symbols:
        expected_dates = {trade_date for trade_date, _ in bars_by_symbol.get(symbol, [])}
        if not expected_dates or factor_dates.get(symbol, set()) != expected_dates:
            incomplete.append(symbol)
    if incomplete:
        raise ValueError(f"factor coverage is incomplete for selected targets: {','.join(sorted(incomplete))}")


def _as_date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _as_datetime(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


if __name__ == "__main__":
    raise SystemExit(main())
