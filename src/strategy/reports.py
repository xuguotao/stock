"""Markdown reports for tail-session paper trading."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.core.broker_base import BrokerTrade
from src.strategy.scanner import TailSessionSignal


def render_tail_session_report(
    trade_date: date,
    scanned_count: int,
    candidates: list[TailSessionSignal],
    confirmed: list[TailSessionSignal],
    trades: list[BrokerTrade],
    account_summary: dict[str, Any],
) -> str:
    """Render a daily tail-session paper-trading report as Markdown."""
    lines = [
        f"# 尾盘策略日报 {trade_date.isoformat()}",
        "",
        "## 扫描摘要",
        "",
        f"- 扫描股票数: {scanned_count}",
        f"- 候选信号: {len(candidates)}",
        f"- 确认信号: {len(confirmed)}",
        f"- 成交笔数: {len(trades)}",
        "",
    ]

    lines.extend(_render_signals("候选信号", candidates))
    lines.extend(_render_signals("确认信号", confirmed))
    lines.extend(_render_trades(trades))
    lines.extend(_render_account_summary(account_summary))
    return "\n".join(lines).rstrip() + "\n"


def write_tail_session_report(
    output_dir: str | Path,
    trade_date: date,
    scanned_count: int,
    candidates: list[TailSessionSignal],
    confirmed: list[TailSessionSignal],
    trades: list[BrokerTrade],
    account_summary: dict[str, Any],
) -> Path:
    """Write a Markdown daily report and return the created path."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"tail_session_{trade_date.isoformat()}.md"
    path.write_text(
        render_tail_session_report(
            trade_date=trade_date,
            scanned_count=scanned_count,
            candidates=candidates,
            confirmed=confirmed,
            trades=trades,
            account_summary=account_summary,
        ),
        encoding="utf-8",
    )
    return path


def _render_signals(title: str, signals: list[TailSessionSignal]) -> list[str]:
    lines = [f"## {title}", ""]
    if not signals:
        return lines + ["无。", ""]

    lines.append("| 股票 | 强度 | 最新价 | 量比 | 尾盘涨幅 | 原因 |")
    lines.append("|------|------|--------|------|----------|------|")
    for signal in signals:
        lines.append(
            f"| {signal.symbol} | {signal.strength:.3f} | {signal.last_price:.2f} | "
            f"{signal.volume_ratio:.2f} | {signal.tail_return:.2%} | {signal.reason} |"
        )
    lines.append("")
    return lines


def _render_trades(trades: list[BrokerTrade]) -> list[str]:
    lines = ["## 成交记录", ""]
    if not trades:
        return lines + ["无。", ""]

    lines.append("| 方向 | 股票 | 数量 | 价格 | 金额 | 佣金 |")
    lines.append("|------|------|------|------|------|------|")
    for trade in trades:
        lines.append(
            f"| {trade.side.upper()} | {trade.symbol} | {trade.quantity} | "
            f"{trade.price:.2f} | {trade.amount:.2f} | {trade.commission:.2f} |"
        )
    lines.append("")
    return lines


def _render_account_summary(account_summary: dict[str, Any]) -> list[str]:
    lines = ["## 账户摘要", ""]
    if not account_summary:
        return lines + ["无。", ""]

    for key in sorted(account_summary):
        lines.append(f"- {key}: {account_summary[key]}")
    lines.append("")
    return lines
