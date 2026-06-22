from __future__ import annotations

from src.web.backend.data_health_repair import build_data_health_repair_plan


def test_build_data_health_repair_plan_maps_warning_sections_to_actions() -> None:
    status = {
        "quality": {
            "status": "warning",
            "issues": [
                "daily_kline_missing_10_symbols",
                "minute5_kline_missing_11_symbols",
                "stock_quote_snapshots_missing_1_symbols",
                "daily_kline_30d_incomplete_2_symbols",
            ],
            "daily": {
                "latest_date": "2026-06-18",
                "missing_symbols": 10,
                "missing_samples": [{"symbol": "603721.SH", "name": "中广天择"}],
            },
            "minute5": {
                "latest_datetime": "2026-06-22 14:55:00",
                "missing_symbols": 11,
                "missing_samples": [{"symbol": "300665.SZ", "name": "飞鹿股份"}],
            },
            "quote_snapshots": {
                "status": "warning",
                "issues": ["stock_quote_snapshots_missing_1_symbols"],
            },
            "scheduled_checks": {
                "completeness_30d": {
                    "affected_symbols": 2,
                    "samples": [{"symbol": "688121.SH", "name": "卓然股份", "data_days": 3}],
                }
            },
        }
    }

    plan = build_data_health_repair_plan(status)

    actions = {action["key"]: action for action in plan["actions"]}
    assert plan["status"] == "ready"
    assert plan["summary"] == {
        "quality_status": "warning",
        "issue_count": 4,
        "auto_repair_count": 4,
        "manual_count": 1,
    }
    assert actions["minute5_sync"]["auto_repair"] is True
    assert actions["minute5_sync"]["trade_date"] == "2026-06-22"
    assert actions["minute5_sync"]["symbols"] == ["300665.SZ"]
    assert actions["daily_from_minute5"]["auto_repair"] is True
    assert actions["daily_from_minute5"]["trade_date"] == "2026-06-18"
    assert actions["quote_snapshot_sync"]["auto_repair"] is True
    assert actions["daily_history_backfill"]["auto_repair"] is False
    assert actions["daily_history_backfill"]["status"] == "manual"
    assert actions["quality_snapshot"]["auto_repair"] is True


def test_build_data_health_repair_plan_returns_ok_without_actions() -> None:
    plan = build_data_health_repair_plan({"quality": {"status": "ok", "issues": []}})

    assert plan["status"] == "ok"
    assert plan["actions"] == []
