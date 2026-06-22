"""Repair planning for dashboard data health warnings."""

from __future__ import annotations

from typing import Any


def build_data_health_repair_plan(status: dict[str, Any]) -> dict[str, Any]:
    """Translate health warnings into explicit repair actions."""
    quality = status.get("quality") or {}
    actions: list[dict[str, Any]] = []

    minute5 = quality.get("minute5") or {}
    if int(minute5.get("missing_symbols") or 0) > 0:
        actions.append(
            {
                "key": "minute5_sync",
                "title": "补齐 5m 分钟线缺口",
                "status": "ready",
                "auto_repair": True,
                "reason": f"5m 最新完整桶缺 {int(minute5.get('missing_symbols') or 0)} 只标的",
                "trade_date": _date_from_datetime(minute5.get("latest_datetime")),
                "symbols": _sample_symbols(minute5.get("missing_samples")),
                "runner": "minute5_sync",
            }
        )

    daily = quality.get("daily") or {}
    if int(daily.get("missing_symbols") or 0) > 0:
        actions.append(
            {
                "key": "daily_from_minute5",
                "title": "用 5m 聚合修复最新日线",
                "status": "ready",
                "auto_repair": True,
                "reason": f"最新日线缺 {int(daily.get('missing_symbols') or 0)} 只标的",
                "trade_date": daily.get("latest_date"),
                "symbols": _sample_symbols(daily.get("missing_samples")),
                "runner": "daily_repair",
            }
        )

    quote_quality = quality.get("quote_snapshots") or {}
    quote_issues = list(quote_quality.get("issues") or [])
    if quote_quality.get("status") in {"warning", "missing"}:
        actions.append(
            {
                "key": "quote_snapshot_sync",
                "title": "重新采集行情快照并刷新 1m/5m 聚合",
                "status": "ready",
                "auto_repair": True,
                "reason": "；".join(str(issue) for issue in quote_issues) or "行情快照覆盖不足",
                "runner": "quote_snapshot_sync",
            }
        )

    scheduled = quality.get("scheduled_checks") or {}
    completeness = scheduled.get("completeness_30d") or {}
    if int(completeness.get("affected_symbols") or 0) > 0:
        actions.append(
            {
                "key": "daily_history_backfill",
                "title": "补历史日线缺口",
                "status": "manual",
                "auto_repair": False,
                "reason": f"近30日有 {int(completeness.get('affected_symbols') or 0)} 只标的日线天数不足",
                "samples": completeness.get("samples") or [],
                "runner": None,
            }
        )

    if quality.get("status") in {"warning", "missing"}:
        actions.append(
            {
                "key": "quality_snapshot",
                "title": "写入修复后的质量快照",
                "status": "ready",
                "auto_repair": True,
                "reason": "记录本次修复前后的质量状态",
                "runner": "quality_snapshot",
            }
        )

    auto_actions = [action for action in actions if action.get("auto_repair")]
    manual_actions = [action for action in actions if not action.get("auto_repair")]
    return {
        "status": "ready" if auto_actions else "manual_only" if manual_actions else "ok",
        "summary": {
            "quality_status": quality.get("status", "unknown"),
            "issue_count": len(quality.get("issues") or []),
            "auto_repair_count": len(auto_actions),
            "manual_count": len(manual_actions),
        },
        "issues": list(quality.get("issues") or []),
        "actions": actions,
    }


def _sample_symbols(samples: Any) -> list[str]:
    if not isinstance(samples, list):
        return []
    symbols = []
    for sample in samples:
        if isinstance(sample, dict) and sample.get("symbol"):
            symbols.append(str(sample["symbol"]))
    return symbols


def _date_from_datetime(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else None
