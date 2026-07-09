#!/usr/bin/env python3
"""Run the dashboard daily maintenance workflow from cron/launchd."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_daily_sync import sync_clickhouse_daily_from_minute5, sync_clickhouse_index_daily
from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline
from src.data.tail_signal_repository import ClickHouseTailSignalRepository
from src.web.backend.app import DailyMaintenanceRequest, _run_daily_maintenance_job
from src.web.backend.data_status import inspect_clickhouse_database, persist_clickhouse_quality_snapshot
from src.web.backend.jobs import JobStore
from src.web.backend.tail_live import run_tail_live_selection


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ClickHouse daily data maintenance.")
    parser.add_argument("--trade-date", help="Trade date, YYYY-MM-DD. Defaults to latest ClickHouse daily date.")
    parser.add_argument("--jobs-db", default="data/web/jobs.json", help="Dashboard job store path")
    parser.add_argument("--no-retry", action="store_true", help="Disable retry for no-data symbols")
    parser.add_argument("--no-strategy-review", action="store_true", help="Disable tail-session strategy review")
    parser.add_argument("--strategy-limit", type=int, default=500, help="Symbols to scan during strategy review")
    parser.add_argument("--strategy-top-n", type=int, default=10, help="Top selections to keep")
    args = parser.parse_args()

    request = DailyMaintenanceRequest(
        trade_date=datetime.strptime(args.trade_date, "%Y-%m-%d").date() if args.trade_date else None,
        retry_no_data=not args.no_retry,
        run_strategy_review=not args.no_strategy_review,
        strategy_limit=args.strategy_limit,
        strategy_top_n=args.strategy_top_n,
    )
    store = JobStore(args.jobs_db)
    job = store.create_job("daily_maintenance", request.model_dump(mode="json"))
    _run_daily_maintenance_job(
        store,
        sync_clickhouse_minute5_kline,
        inspect_clickhouse_database,
        run_tail_live_selection,
        ClickHouseTailSignalRepository(),
        job.id,
        request,
        daily_repair_runner=sync_clickhouse_daily_from_minute5,
        index_daily_sync_runner=sync_clickhouse_index_daily,
        quality_snapshot_writer=persist_clickhouse_quality_snapshot,
    )
    completed = store.get_job(job.id)
    if completed is None:
        raise SystemExit("job missing after run")
    print(f"{completed.status}: {completed.id}")
    if completed.error:
        print(completed.error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
