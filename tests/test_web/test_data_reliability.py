from __future__ import annotations

from src.web.backend.data_reliability import build_data_reliability_report


def test_build_data_reliability_report_summarizes_automation_and_warnings() -> None:
    status = {
        "health": {"daily_latest_date": "2026-06-18"},
        "quality": {
            "status": "warning",
            "issues": ["daily_kline_missing_10_symbols"],
            "daily": {
                "status": "warning",
                "latest_date": "2026-06-18",
                "covered_symbols": 4967,
                "expected_symbols": 4977,
                "coverage_ratio": 0.997991,
            },
            "minute5": {
                "status": "ok",
                "latest_datetime": "2026-06-22 15:00:00",
                "covered_symbols": 4977,
                "expected_symbols": 4977,
                "coverage_ratio": 1.0,
            },
            "quote_snapshots": {
                "status": "warning",
                "expected_symbols": 4977,
                "raw": {
                    "latest_datetime": "2026-06-22 14:59:57",
                    "latest_symbol_count": 4976,
                    "coverage_ratio": 0.999799,
                },
            },
        },
    }
    repair_plan = {
        "summary": {"auto_repair_count": 3, "manual_count": 1},
        "actions": [
            {"key": "daily_from_minute5", "reason": "最新日线缺 10 只标的"},
            {"key": "quote_snapshot_sync", "reason": "快照缺 1 只标的"},
        ],
    }

    report = build_data_reliability_report(
        status=status,
        minute5_monitor={"running": True},
        quote_monitor={"running": True},
        scheduler={"running": True, "tasks": {"post_close_maintenance": {"enabled": True}}},
        repair_plan=repair_plan,
    )

    rows = {row["key"]: row for row in report["rows"]}
    assert report["status"] == "warning"
    assert report["summary"] == {
        "rows": 4,
        "warning_rows": 3,
        "automation_gaps": 0,
        "auto_repair_count": 3,
        "manual_count": 1,
    }
    assert rows["daily"]["automation"] == "scheduled"
    assert rows["daily"]["coverage"] == "4967 / 4977（99.80%）"
    assert rows["minute5"]["source"].startswith("Tencent 5m 优先")
    assert rows["quote_snapshots"]["coverage"] == "4976 / 4977（99.98%）"
    assert rows["quote_snapshots"]["issues"] == ["快照缺 1 只标的"]
