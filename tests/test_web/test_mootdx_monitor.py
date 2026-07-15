from __future__ import annotations

import json
from datetime import date, datetime

from src.data_ops.models import DataOpsTaskStatus
from src.web.backend.mootdx_monitor import MootdxMonitorService


class FakeRepository:
    def list_task_statuses(self):
        return [
            DataOpsTaskStatus(
                task_key="mootdx_daily_kline_sync",
                enabled=True,
                status="success",
                schedule_kind="daily_time",
                schedule_config={"time": "15:35", "limit": 0},
                max_runtime_seconds=3600,
                stale_after_seconds=600,
            )
        ]


class FakeClickHouse:
    def execute(self, query, params=None):
        if "from mootdx_sync_runs" in query:
            return [(
                "run-1",
                "mootdx_offline_sync",
                datetime(2026, 7, 10, 15, 35),
                datetime(2026, 7, 10, 15, 36),
                "success",
                json.dumps({"daily_reconcile": True, "tasks": ["stock_kline_daily"]}),
                json.dumps({
                    "duration_seconds": 60.0,
                    "inserted": {"mootdx_stock_kline": 4},
                    "diagnostics": {"stock_kline_daily": {"coverage_rate": 0.9996, "failed_symbols_count": 0, "dropped_rows": 0}},
                }),
                "",
            )]
        if "mootdx_stock_catalog" in query:
            return [(4996, datetime(2026, 7, 10, 8, 30))]
        if "mootdx_stock_kline" in query:
            return [(date(2026, 7, 10), 4994)]
        if "mootdx_symbol_data_status" in query:
            return [("active", 4994), ("no_data", 2)]
        raise AssertionError(query)


def test_mootdx_monitor_aggregates_dynamic_config_audits_and_health() -> None:
    snapshot = MootdxMonitorService(repository=FakeRepository(), client=FakeClickHouse()).snapshot()

    daily = next(item for item in snapshot["tasks"] if item["task_key"] == "mootdx_daily_kline_sync")
    assert daily["schedule_config"] == {"time": "15:35", "limit": 0}
    assert daily["max_runtime_seconds"] == 3600
    assert snapshot["audits"][0]["task_label"] == "日线缺口核对"
    assert snapshot["audits"][0]["audit"]["status"] == "healthy"
    assert snapshot["health"]["catalog"] == {"status": "healthy", "symbols": 4996, "captured_at": "2026-07-10 08:30:00"}
    assert snapshot["health"]["daily"] == {"status": "healthy", "trade_date": "2026-07-10", "symbols": 4994}
    assert snapshot["health"]["symbol_status"] == {"status": "healthy", "active": 4994, "no_data": 2}


def test_mootdx_monitor_normalizes_legacy_known_no_data_reconciliation_audit() -> None:
    class LegacyAuditClickHouse(FakeClickHouse):
        def execute(self, query, params=None):
            if "from mootdx_sync_runs" in query:
                return [(
                    "run-legacy",
                    "stock_kline_daily",
                    datetime(2026, 7, 13, 16, 5),
                    datetime(2026, 7, 13, 16, 5, 3),
                    "success",
                    json.dumps({"daily_reconcile": True, "tasks": ["stock_kline_daily"]}),
                    json.dumps({
                        "diagnostics": {"stock_kline_daily": {
                            "target_symbols": 65,
                            "requested_symbols": 0,
                            "skipped_no_data_symbols_count": 65,
                            "failed_symbols_count": 0,
                            "dropped_rows": 0,
                            "audit": {"status": "failed", "reasons": ["coverage_below_target"]},
                        }},
                    }),
                    "",
                )]
            return super().execute(query, params)

    snapshot = MootdxMonitorService(repository=FakeRepository(), client=LegacyAuditClickHouse()).snapshot()

    assert snapshot["audits"][0]["audit"] == {"status": "healthy", "reasons": []}


def test_mootdx_monitor_labels_xdxr_audits_as_xdxr_sync() -> None:
    class XdxrAuditClickHouse(FakeClickHouse):
        def execute(self, query, params=None):
            if "from mootdx_sync_runs" in query:
                return [(
                    "run-xdxr",
                    "xdxr",
                    datetime(2026, 7, 15, 17, 10),
                    datetime(2026, 7, 15, 17, 10, 5),
                    "success",
                    json.dumps({}),
                    json.dumps({"diagnostics": {"xdxr": {"audit": {"status": "healthy", "reasons": []}}}}),
                    "",
                )]
            return super().execute(query, params)

    snapshot = MootdxMonitorService(repository=FakeRepository(), client=XdxrAuditClickHouse()).snapshot()

    assert snapshot["audits"][0]["task_label"] == "除权除息同步"


def test_mootdx_monitor_keeps_task_definitions_when_task_store_is_unavailable() -> None:
    class BrokenRepository:
        def list_task_statuses(self):
            raise OSError("ClickHouse unavailable")

    snapshot = MootdxMonitorService(repository=BrokenRepository(), client=FakeClickHouse()).snapshot()

    assert [item["status"] for item in snapshot["tasks"]] == ["unavailable", "unavailable", "unavailable", "unavailable", "unavailable"]
    assert snapshot["tasks"][0]["last_error"] == "OSError: ClickHouse unavailable"
    assert snapshot["health"]["daily"]["symbols"] == 4994


def test_mootdx_monitor_loads_audit_diagnostics_only_on_detail_request() -> None:
    service = MootdxMonitorService(repository=FakeRepository(), client=FakeClickHouse())

    summary = service.snapshot()["audits"][0]
    detail = service.audit_detail("run-1")

    assert "diagnostics" not in summary
    assert detail is not None
    assert detail["diagnostics"]["coverage_rate"] == 0.9996
