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
        f"# Zijin Mining Monitor - {snapshot.date}",
        "",
        "## Snapshot",
        "",
        f"- Stock: `{snapshot.stock_symbol}`",
        f"- Price: {_fmt_optional(snapshot.stock_price)}",
        f"- Change: {_fmt_pct(snapshot.stock_change_pct)}",
        "",
        "## Price And Commodity Trends",
        "",
        "| Name | Status | Latest | 20D MA | 60D MA | Reason |",
        "|---|---|---:|---:|---:|---|",
    ]

    for trend in snapshot.trends:
        lines.append(
            "| {name} | {status} | {latest:.2f} | {short} | {long} | {reason} |".format(
                name=trend.name,
                status=trend.status,
                latest=trend.latest_close,
                short=_fmt_optional(trend.short_ma),
                long=_fmt_optional(trend.long_ma),
                reason=trend.reason,
            )
        )

    lines.extend(
        [
            "",
            "## Production Delivery",
            "",
            "| Item | Status | Actual YTD | Annual Target | Actual Progress | Expected Progress | Reason |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in snapshot.production:
        lines.append(
            "| {name} | {status} | {actual:.2f} {unit} | {target:.2f} {unit} | {actual_ratio} | {expected_ratio} | {reason} |".format(
                name=item.name,
                status=item.status,
                actual=item.actual_ytd,
                unit=item.unit,
                target=item.annual_target,
                actual_ratio=_fmt_pct(item.actual_ratio * 100),
                expected_ratio=_fmt_pct(item.expected_ratio * 100),
                reason=item.reason,
            )
        )

    lines.extend(["", "## Triggers", ""])
    weak_trends = [t.name for t in snapshot.trends if t.status == "weak"]
    behind_items = [p.name for p in snapshot.production if p.status == "behind"]
    if weak_trends:
        lines.append(f"- Trend warning: {', '.join(weak_trends)} below 60-day average.")
    else:
        lines.append("- Trend warning: no monitored series is below the 60-day average.")
    if behind_items:
        lines.append(f"- Production warning: {', '.join(behind_items)} materially behind elapsed-year pace.")
    else:
        lines.append("- Production warning: no monitored item is materially behind elapsed-year pace.")

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

