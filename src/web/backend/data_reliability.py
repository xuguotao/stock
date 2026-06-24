"""Data reliability dashboard model."""

from __future__ import annotations

from typing import Any


def build_data_reliability_report(
    *,
    status: dict[str, Any],
    minute5_monitor: dict[str, Any],
    quote_monitor: dict[str, Any],
    scheduler: dict[str, Any],
    repair_plan: dict[str, Any],
) -> dict[str, Any]:
    """Summarize data stability, completeness, freshness, and automation."""
    quality = status.get("quality") or {}
    quote_quality = quality.get("quote_snapshots") or {}
    quote_raw = quote_quality.get("raw") or {}
    rows = [
        _row(
            key="daily",
            name="日线行情",
            source="ClickHouse daily_kline；最新日线缺口可由 5m 聚合修复",
            update="日终维护执行 5m 同步后聚合补日线",
            automation=_automation_status(scheduler),
            health=str((quality.get("daily") or {}).get("status") or "unknown"),
            latest=(quality.get("daily") or {}).get("latest_date"),
            coverage=_coverage_text(quality.get("daily")),
            repair="自动：daily_from_minute5；历史缺口：待日线历史回填器",
            issues=_issues_for(repair_plan, "daily"),
        ),
        _row(
            key="minute5",
            name="5m 分钟线",
            source="Tencent 5m 优先；Sina 长窗口；AKShare 兜底；写入 ClickHouse minute5_kline",
            update="交易时段持续更新；日终维护全市场补齐；选股前可自动补齐",
            automation="running" if minute5_monitor.get("running") else "stopped",
            health=str((quality.get("minute5") or {}).get("status") or "unknown"),
            latest=(quality.get("minute5") or {}).get("latest_datetime"),
            coverage=_coverage_text(quality.get("minute5")),
            repair="自动：minute5_sync",
            issues=_issues_for(repair_plan, "minute5"),
        ),
        _row(
            key="quote_snapshots",
            name="行情快照",
            source="Tencent 实时行情；写入 stock_quote_snapshots 并刷新 1m/5m rollup",
            update="交易时段 10s 级持续采集；支持动态 chunk 降载",
            automation="running" if quote_monitor.get("running") else "stopped",
            health=str(quote_quality.get("status") or "unknown"),
            latest=quote_raw.get("latest_datetime"),
            coverage=_coverage_text(quote_raw, expected_fallback=quote_quality.get("expected_symbols")),
            repair="自动：quote_snapshot_sync",
            issues=_issues_for(repair_plan, "quote"),
        ),
        _row(
            key="health_checks",
            name="健康检查与快照",
            source="ClickHouse system tables + 质量 SQL 检查",
            update="页面按需检查；日终维护写入 data_source_health 快照",
            automation=_automation_status(scheduler),
            health=str(quality.get("status") or "unknown"),
            latest=(status.get("health") or {}).get("daily_latest_date"),
            coverage=f"{len(quality.get('issues') or [])} 个阻塞告警，{len(quality.get('ignored_issues') or [])} 个已忽略",
            repair="自动：health-repair-plan；质量快照由日常维护记录",
            issues=list(quality.get("issues") or []),
        ),
    ]
    statuses = {row["health"] for row in rows}
    automation_gaps = [row for row in rows if row["automation"] not in {"running", "scheduled"}]
    return {
        "status": "warning" if "warning" in statuses or automation_gaps else "ok",
        "summary": {
            "rows": len(rows),
            "warning_rows": sum(1 for row in rows if row["health"] == "warning"),
            "automation_gaps": len(automation_gaps),
            "auto_repair_count": (repair_plan.get("summary") or {}).get("auto_repair_count", 0),
            "manual_count": (repair_plan.get("summary") or {}).get("manual_count", 0),
        },
        "rows": rows,
    }


def _row(
    *,
    key: str,
    name: str,
    source: str,
    update: str,
    automation: str,
    health: str,
    latest: Any,
    coverage: str,
    repair: str,
    issues: list[Any],
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "source": source,
        "update_mechanism": update,
        "automation": automation,
        "health": health,
        "latest": latest,
        "coverage": coverage,
        "repair": repair,
        "issues": [str(issue) for issue in issues],
    }


def _automation_status(scheduler: dict[str, Any]) -> str:
    if scheduler.get("running") and ((scheduler.get("tasks") or {}).get("post_close_maintenance") or {}).get("enabled"):
        return "scheduled"
    return "stopped"


def _coverage_text(row: dict[str, Any] | None, *, expected_fallback: Any = None) -> str:
    if not row:
        return "-"
    covered = row.get("covered_symbols") or row.get("latest_symbol_count")
    expected = row.get("expected_symbols") or expected_fallback
    ratio = row.get("coverage_ratio")
    if covered is None and expected is None and ratio is None:
        return "-"
    pct = f"{float(ratio) * 100:.2f}%" if ratio is not None else "-"
    covered_text = "-" if covered is None else str(covered)
    expected_text = "-" if expected is None else str(expected)
    return f"{covered_text} / {expected_text}（{pct}）"


def _issues_for(repair_plan: dict[str, Any], group: str) -> list[Any]:
    keys = {
        "daily": ("daily_from_minute5", "daily_history_backfill"),
        "minute5": ("minute5_sync",),
        "quote": ("quote_snapshot_sync",),
    }.get(group, ())
    issues = []
    for action in repair_plan.get("actions") or []:
        if action.get("key") in keys and action.get("reason"):
            issues.extend(_split_issue_reason(str(action["reason"])))
    return issues


def _split_issue_reason(reason: str) -> list[str]:
    parts = reason.replace("；", ";").split(";")
    return [part.strip() for part in parts if part.strip()]
