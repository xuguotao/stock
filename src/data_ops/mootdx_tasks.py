"""Definitions shared by mootdx scheduling, monitoring, and management UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MOOTDX_CONNECTION_DEFAULTS = {
    "rate_limit": 0.02,
    "timeout": 15,
    "bestip": False,
}


@dataclass(frozen=True)
class MootdxTaskDefinition:
    task_key: str
    label: str
    description: str
    sync_task: str
    schedule_kind: str
    schedule_config: dict[str, Any]
    max_runtime_seconds: int
    stale_after_seconds: int
    daily_reconcile: bool = False
    enabled: bool = True


MOOTDX_TASK_DEFINITIONS = (
    MootdxTaskDefinition(
        task_key="mootdx_stock_catalog_sync",
        label="股票目录同步",
        description="从 mootdx 全量股票目录建立权威快照，并审计新增、移除和 ST 变化。",
        sync_task="stock_catalog",
        schedule_kind="daily_time",
        schedule_config={"time": "08:30", **MOOTDX_CONNECTION_DEFAULTS},
        max_runtime_seconds=900,
        stale_after_seconds=300,
    ),
    MootdxTaskDefinition(
        task_key="mootdx_daily_kline_sync",
        label="日线主同步",
        description="按最新有效股票池同步收盘日线，并记录单标的降级与质量审计。",
        sync_task="stock_kline_daily",
        schedule_kind="daily_time",
        schedule_config={"time": "15:35", **MOOTDX_CONNECTION_DEFAULTS},
        max_runtime_seconds=3600,
        stale_after_seconds=600,
    ),
    MootdxTaskDefinition(
        task_key="mootdx_daily_kline_reconcile",
        label="日线缺口核对",
        description="仅请求当日缺失的日线标的，避免全量重复同步。",
        sync_task="stock_kline_daily",
        schedule_kind="daily_time",
        schedule_config={"time": "16:05", **MOOTDX_CONNECTION_DEFAULTS},
        max_runtime_seconds=1800,
        stale_after_seconds=600,
        daily_reconcile=True,
    ),
    MootdxTaskDefinition(
        task_key="mootdx_xdxr_sync",
        label="除权除息同步",
        description="同步 Mootdx 历史除权除息（XDXR）信息，并保留逐标的同步审计。",
        sync_task="xdxr",
        schedule_kind="daily_time",
        schedule_config={"time": "17:10", "rate_limit": 0.02, "timeout": 10, "bestip": False},
        max_runtime_seconds=900,
        stale_after_seconds=300,
    ),
    MootdxTaskDefinition(
        task_key="stock_universe_profile_refresh",
        label="可用股票池标签刷新",
        description="按目录与日线事实重算全项目统一的可用股票池与流动性标签。",
        sync_task="stock_universe_profile",
        schedule_kind="daily_time",
        schedule_config={
            "time": "16:15",
            "lookback_days": 20,
            "min_trading_days": 15,
            "min_average_amount": 10_000_000,
            "min_listing_age_days": 0,
            "include_beijing": False,
        },
        max_runtime_seconds=900,
        stale_after_seconds=300,
    ),
)

MOOTDX_TASK_BY_KEY = {definition.task_key: definition for definition in MOOTDX_TASK_DEFINITIONS}
MOOTDX_TASK_KEYS = tuple(MOOTDX_TASK_BY_KEY)
