#!/usr/bin/env python3
"""Verify and, only when explicitly requested, cut over Mootdx XDXR storage.

The default command is read-only.  A cutover requires a successful full-pool
baseline run whose current projection exactly matches the legacy table.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_source import ClickHouseStockDataSource  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only report migration readiness (default).")
    mode.add_argument("--execute", action="store_true", help="Rename the legacy table and create the compatibility view.")
    parser.add_argument("--baseline-run-id", help="Successful full-pool XDXR sync run_id required for --execute.")
    return parser.parse_args(argv)


def run_migration(
    *,
    client: Any,
    dry_run: bool = True,
    baseline_run_id: str | None = None,
) -> dict[str, Any]:
    """Return an auditable readiness report, optionally performing the cutover."""
    legacy_event_count = _count(client, "select count() from mootdx_xdxr final")
    current_event_count = _count(client, "select count() from mootdx_xdxr_current")
    business_key_difference_count = _count(client, _BUSINESS_KEY_DIFFERENCE_SQL)
    content_difference_count = _count(client, _CONTENT_DIFFERENCE_SQL)
    baseline_event_count = _baseline_event_count(client, baseline_run_id)
    ready_for_cutover = (
        bool(baseline_run_id)
        and baseline_event_count > 0
        and business_key_difference_count == 0
        and content_difference_count == 0
    )
    report: dict[str, Any] = {
        "renamed": False,
        "legacy_event_count": legacy_event_count,
        "current_event_count": current_event_count,
        "business_key_difference_count": business_key_difference_count,
        "content_difference_count": content_difference_count,
        "baseline_run_id": baseline_run_id,
        "baseline_event_count": baseline_event_count,
        "ready_for_cutover": ready_for_cutover,
    }
    if dry_run:
        return report
    if not ready_for_cutover:
        raise ValueError("XDXR cutover refused: baseline is absent or the current projection differs from legacy")
    backup_table = f"mootdx_xdxr_legacy_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    client.execute(f"rename table mootdx_xdxr to {backup_table}")
    client.execute(_compatibility_view_sql())
    report.update({"renamed": True, "legacy_backup_table": backup_table})
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_migration(
        client=ClickHouseStockDataSource()._client_instance(),
        dry_run=not args.execute,
        baseline_run_id=args.baseline_run_id,
    )
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0


def _count(client: Any, sql: str, params: dict[str, Any] | None = None) -> int:
    rows = client.execute(sql, params)
    return int(rows[0][0]) if rows else 0


def _baseline_event_count(client: Any, baseline_run_id: str | None) -> int:
    if not baseline_run_id:
        return 0
    return _count(
        client,
        _BASELINE_EVENT_COUNT_SQL,
        {"baseline_run_id": baseline_run_id},
    )


_BUSINESS_KEY_DIFFERENCE_SQL = """
select count()
from (
    select symbol, event_date, category
    from (
        select symbol, event_date, category from mootdx_xdxr final
        union all
        select symbol, event_date, category from mootdx_xdxr_current
    )
    group by symbol, event_date, category
    having count() = 1
)
"""

_BASELINE_EVENT_COUNT_SQL = """
select count()
from mootdx_xdxr_event_versions as version
inner join (select * from mootdx_ingestion_runs final) as ingestion
  on version.ingest_seq = ingestion.ingest_seq
where ingestion.status = 'succeeded' and ingestion.run_id = %(baseline_run_id)s
"""

_CONTENT_DIFFERENCE_SQL = """
select count()
from (
    select legacy.symbol
    from (select * from mootdx_xdxr final) as legacy
    inner join mootdx_xdxr_current as projection
      on legacy.symbol = projection.symbol
     and legacy.event_date = projection.event_date
     and legacy.category = projection.category
    where toJSONString(tuple(
        legacy.name, legacy.fenhong, legacy.peigujia, legacy.songzhuangu,
        legacy.peigu, legacy.suogu, legacy.panqianliutong, legacy.panhouliutong,
        legacy.qianzongguben, legacy.houzongguben
    )) != toJSONString(tuple(
        projection.name, projection.fenhong, projection.peigujia, projection.songzhuangu,
        projection.peigu, projection.suogu, projection.panqianliutong, projection.panhouliutong,
        projection.qianzongguben, projection.houzongguben
    ))
)
"""


def _compatibility_view_sql() -> str:
    return """
    create view mootdx_xdxr as
    select
        symbol, event_date, category, name, fenhong, peigujia, songzhuangu,
        peigu, suogu, panqianliutong, panhouliutong, qianzongguben,
        houzongguben, observed_at as ingested_at, raw_json, ingest_seq
    from mootdx_xdxr_current
    """


if __name__ == "__main__":
    raise SystemExit(main())
