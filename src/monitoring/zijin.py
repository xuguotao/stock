"""Zijin Mining monitoring helpers.

The core functions are pure so reports can be tested without network access.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TrendStatus:
    name: str
    status: str
    latest_close: float
    short_ma: float | None
    long_ma: float | None
    reason: str


@dataclass(frozen=True)
class ProductionInput:
    name: str
    annual_target: float
    actual_ytd: float
    unit: str


@dataclass(frozen=True)
class ProductionStatus:
    name: str
    status: str
    annual_target: float
    actual_ytd: float
    unit: str
    actual_ratio: float
    expected_ratio: float
    reason: str


@dataclass(frozen=True)
class MonitorSnapshot:
    date: str
    stock_symbol: str
    stock_price: float | None
    stock_change_pct: float | None
    trends: list[TrendStatus]
    production: list[ProductionStatus]


def evaluate_trend(
    name: str,
    bars: pd.DataFrame,
    short_window: int = 20,
    long_window: int = 60,
) -> TrendStatus:
    """Classify a close-price series with 20/60 day trend rules."""
    if bars.empty or "close" not in bars.columns:
        raise ValueError("bars must contain at least one close value")

    closes = pd.to_numeric(bars["close"], errors="coerce").dropna()
    if closes.empty:
        raise ValueError("bars close column does not contain numeric values")

    latest = float(closes.iloc[-1])
    short_ma = _moving_average(closes, short_window)
    long_ma = _moving_average(closes, long_window)

    if long_ma is not None and latest < long_ma:
        return TrendStatus(
            name=name,
            status="weak",
            latest_close=latest,
            short_ma=short_ma,
            long_ma=long_ma,
            reason=f"latest close is below 60-day average ({long_ma:.2f})",
        )

    if short_ma is not None and long_ma is not None and latest >= short_ma and latest >= long_ma:
        return TrendStatus(
            name=name,
            status="strong",
            latest_close=latest,
            short_ma=short_ma,
            long_ma=long_ma,
            reason="latest close is above both 20-day and 60-day averages",
        )

    return TrendStatus(
        name=name,
        status="neutral",
        latest_close=latest,
        short_ma=short_ma,
        long_ma=long_ma,
        reason="trend is mixed or there is not enough history for full confirmation",
    )


def evaluate_production(
    items: list[ProductionInput],
    elapsed_ratio: float,
) -> list[ProductionStatus]:
    """Classify year-to-date production delivery against elapsed-year pace."""
    if elapsed_ratio <= 0:
        raise ValueError("elapsed_ratio must be positive")

    results: list[ProductionStatus] = []
    for item in items:
        if item.annual_target <= 0:
            raise ValueError(f"{item.name} annual_target must be positive")

        actual_ratio = item.actual_ytd / item.annual_target
        pace_ratio = actual_ratio / elapsed_ratio
        if pace_ratio >= 0.9:
            status = "on_track"
            reason = "actual progress is within 90% of elapsed-year pace"
        elif pace_ratio >= 0.75:
            status = "watch"
            reason = "actual progress is between 75% and 90% of elapsed-year pace"
        else:
            status = "behind"
            reason = "actual progress is below 75% of elapsed-year pace"

        results.append(
            ProductionStatus(
                name=item.name,
                status=status,
                annual_target=item.annual_target,
                actual_ytd=item.actual_ytd,
                unit=item.unit,
                actual_ratio=round(actual_ratio, 4),
                expected_ratio=round(elapsed_ratio, 4),
                reason=reason,
            )
        )
    return results


def render_markdown_report(snapshot: MonitorSnapshot) -> str:
    """Render a local Markdown report."""
    lines = [
        f"# 紫金矿业监控报告 - {snapshot.date}",
        "",
        "## 快照",
        "",
        f"- 股票：`{snapshot.stock_symbol}`",
        f"- 最新价：{_fmt_optional(snapshot.stock_price)}",
        f"- 涨跌幅：{_fmt_pct(snapshot.stock_change_pct)}",
        "",
        "## 价格与商品趋势",
        "",
        "| 名称 | 状态 | 最新值 | 20日均线 | 60日均线 | 判断依据 |",
        "|---|---|---:|---:|---:|---|",
    ]

    for trend in snapshot.trends:
        lines.append(
            "| {name} | {status} | {latest:.2f} | {short} | {long} | {reason} |".format(
                name=_display_name(trend.name),
                status=_display_status(trend.status),
                latest=trend.latest_close,
                short=_fmt_optional(trend.short_ma),
                long=_fmt_optional(trend.long_ma),
                reason=_display_reason(trend.reason),
            )
        )

    lines.extend(
        [
            "",
            "## 产量兑现",
            "",
            "| 项目 | 状态 | 年初至今产量 | 年度目标 | 实际进度 | 时间进度 | 判断依据 |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in snapshot.production:
        lines.append(
            "| {name} | {status} | {actual:.2f} {unit} | {target:.2f} {unit} | {actual_ratio} | {expected_ratio} | {reason} |".format(
                name=_display_name(item.name),
                status=_display_status(item.status),
                actual=item.actual_ytd,
                unit=_display_unit(item.unit),
                target=item.annual_target,
                actual_ratio=_fmt_pct(item.actual_ratio * 100),
                expected_ratio=_fmt_pct(item.expected_ratio * 100),
                reason=_display_reason(item.reason),
            )
        )

    lines.extend(["", "## 触发信号", ""])
    weak_trends = [_display_name(t.name) for t in snapshot.trends if t.status == "weak"]
    behind_items = [_display_name(p.name) for p in snapshot.production if p.status == "behind"]
    if weak_trends:
        lines.append(f"- 趋势预警：{', '.join(weak_trends)}低于60日均线。")
    else:
        lines.append("- 趋势预警：没有监控项低于60日均线。")
    if behind_items:
        lines.append(f"- 产量预警：{', '.join(behind_items)}明显落后于时间进度。")
    else:
        lines.append("- 产量预警：没有监控项明显落后于时间进度。")

    lines.append("")
    return "\n".join(lines)


def _moving_average(closes: pd.Series, window: int) -> float | None:
    if len(closes) < window:
        return None
    return float(closes.tail(window).mean())


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _display_name(value: str) -> str:
    names = {
        "zijin": "紫金矿业",
        "gold": "黄金",
        "copper": "铜",
        "mined gold": "矿产金",
        "mined copper": "矿产铜",
        "lithium carbonate equivalent": "碳酸锂当量",
    }
    return names.get(value, value)


def _display_status(value: str) -> str:
    statuses = {
        "strong": "强",
        "neutral": "中性",
        "weak": "弱",
        "on_track": "达标",
        "watch": "观察",
        "behind": "落后",
    }
    return statuses.get(value, value)


def _display_unit(value: str) -> str:
    units = {
        "tonnes": "吨",
        "10k tonnes": "万吨",
    }
    return units.get(value, value)


def _display_reason(value: str) -> str:
    reasons = {
        "latest close is above both 20-day and 60-day averages": "最新值高于20日和60日均线",
        "trend is mixed or there is not enough history for full confirmation": "趋势混合，或历史数据不足以完整确认",
        "actual progress is within 90% of elapsed-year pace": "实际进度达到时间进度的90%以上",
        "actual progress is between 75% and 90% of elapsed-year pace": "实际进度为时间进度的75%-90%",
        "actual progress is below 75% of elapsed-year pace": "实际进度低于时间进度的75%",
    }
    if value.startswith("latest close is below 60-day average"):
        suffix = value.removeprefix("latest close is below 60-day average")
        return f"最新值低于60日均线{suffix}"
    return reasons.get(value, value)
