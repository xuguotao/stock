from __future__ import annotations


def test_mootdx_task_definitions_are_the_single_source_for_schedule_and_labels() -> None:
    from src.data_ops.mootdx_tasks import MOOTDX_TASK_DEFINITIONS

    assert [definition.task_key for definition in MOOTDX_TASK_DEFINITIONS] == [
        "mootdx_stock_catalog_sync",
        "mootdx_daily_kline_sync",
        "mootdx_daily_kline_reconcile",
        "stock_universe_profile_refresh",
    ]
    assert [definition.schedule_config for definition in MOOTDX_TASK_DEFINITIONS] == [
        {"time": "08:30", "rate_limit": 0.02, "timeout": 15, "bestip": False},
        {"time": "15:35", "rate_limit": 0.02, "timeout": 15, "bestip": False},
        {"time": "16:05", "rate_limit": 0.02, "timeout": 15, "bestip": False},
        {
            "time": "16:15",
            "lookback_days": 20,
            "min_trading_days": 15,
            "min_average_amount": 10_000_000,
            "min_listing_age_days": 0,
            "include_beijing": False,
        },
    ]
    assert all(definition.enabled for definition in MOOTDX_TASK_DEFINITIONS)
    assert all(definition.label and definition.description for definition in MOOTDX_TASK_DEFINITIONS)
