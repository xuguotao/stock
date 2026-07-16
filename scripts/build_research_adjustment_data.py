#!/usr/bin/env python3
"""Explicit fail-closed entry point for research adjustment candidates.

The event and factor calculator is deliberately injectable.  It is not provided
until the dedicated raw daily/XDXR construction task exists, which prevents this
command from claiming a successful adjustment build with guessed input data.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.research_adjustment_store import ResearchAdjustmentStore  # noqa: E402


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
    candidate_builder: CandidateBuilder | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Write a complete candidate and only then publish it.

    Without a supplied raw daily/XDXR candidate builder this intentionally raises
    before even creating tables.  That makes the public CLI safe while the raw
    factor-construction implementation is still absent.
    """
    if candidate_builder is None:
        raise RuntimeError("research adjustment candidate builder is not configured; refusing to publish")
    active_store = store or ResearchAdjustmentStore()
    candidate = candidate_builder(symbols=list(symbols) if symbols else None, formula_version=formula_version, full=full)
    events = list(candidate.get("events", []))
    factors = list(candidate.get("factors", []))
    if not factors:
        raise RuntimeError("candidate builder returned no daily factors; refusing to publish")
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
    )
    return {"run_id": run_id, "event_count": written_events, "factor_count": written_factors}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_research_adjustment_data(
            symbols=args.symbols, formula_version=args.formula_version, full=args.full
        )
    except RuntimeError as exc:
        print(f"research adjustment build blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
