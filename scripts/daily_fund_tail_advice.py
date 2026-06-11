#!/usr/bin/env python
"""Generate a daily Chinese fund tail-session advice report."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.scheduler import TradingScheduler


def pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%"


def _row_value(row: pd.Series, key: str, default: object = "") -> object:
    return row[key] if key in row and pd.notna(row[key]) else default


def build_markdown_report(report: pd.DataFrame, trade_date: str) -> str:
    """Build a concise human-facing Markdown report from the Chinese CSV."""
    actionable = report[report["最终操作建议"].isin(["尾盘加仓", "小额试探"])]
    if actionable.empty:
        summary = "总判断：今天不适合大额尾盘加仓，整体以观察和等待企稳为主。"
    else:
        names = "、".join(actionable["基金名称"].astype(str).tolist())
        summary = f"总判断：今天不适合大额尾盘加仓；可关注 {names} 的小额试探机会。"

    lines = [
        f"# 基金尾盘操作建议 - {trade_date}",
        "",
        summary,
        "",
        "| 基金 | 代码 | 今日代理涨跌 | 操作等级 | 最终建议 | 建议原因 |",
        "|---|---:|---:|---:|---|---|",
    ]

    for _, row in report.iterrows():
        lines.append(
            "| {name} | {code} | {daily} | {grade} | {action} | {reason} |".format(
                name=_row_value(row, "基金名称"),
                code=str(_row_value(row, "基金代码")).zfill(6),
                daily=pct(_row_value(row, "今日代理涨跌率", 0.0)),
                grade=_row_value(row, "操作等级"),
                action=_row_value(row, "最终操作建议"),
                reason=_row_value(row, "建议原因"),
            )
        )

    lines.extend(["", "## 逐只依据", ""])
    for _, row in report.iterrows():
        name = _row_value(row, "基金名称")
        code = str(_row_value(row, "基金代码")).zfill(6)
        lines.extend(
            [
                f"### {name} `{code}`",
                (
                    f"- 今日代理涨跌：{pct(_row_value(row, '今日代理涨跌率', 0.0))}；"
                    f"技术信号：{_row_value(row, '技术信号')}；"
                    f"信号原因：{_row_value(row, '信号原因')}"
                ),
                (
                    f"- 同类次日上涨/下跌概率：{pct(_row_value(row, '同类次日上涨概率', 0.0))} / "
                    f"{pct(_row_value(row, '同类次日下跌概率', 0.0))}；"
                    f"样本数：{int(float(_row_value(row, '同类样本数', 0)))}"
                ),
                (
                    f"- 同类次日平均/中位数收益：{pct(_row_value(row, '同类次日平均收益', 0.0))} / "
                    f"{pct(_row_value(row, '同类次日中位数收益', 0.0))}；"
                    f"跌超1%/2%概率：{pct(_row_value(row, '同类次日跌超1%概率', 0.0))} / "
                    f"{pct(_row_value(row, '同类次日跌超2%概率', 0.0))}"
                ),
                f"- 操作：{_row_value(row, '最终操作建议')}（{_row_value(row, '建议原因')}）",
                "",
            ]
        )

    lines.extend(
        [
            "## 明日观察",
            "",
            "- 高开不追；只有回踩不破且放量修复时，再考虑第二笔。",
            "- 连续弱势品种先等企稳，不在贴近日内低位时连续摊平。",
            "- 主题基金优先看同类历史概率，技术信号和最终建议冲突时，以最终建议为准。",
            "",
            "这不是保证收益的投资建议，只用于辅助你做尾盘加仓节奏判断。",
            "",
        ]
    )
    return "\n".join(lines)


def run_backtest_script(
    *,
    python_bin: str,
    data_dir: Path,
    report: Path,
    raw_report: Path,
    start_date: str,
    end_date: str,
) -> None:
    cmd = [
        python_bin,
        str(ROOT / "scripts" / "backtest_fund_tail_advice.py"),
        "--download",
        "--data-dir",
        str(data_dir),
        "--report",
        str(report),
        "--raw-report",
        str(raw_report),
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily fund tail-session advice.")
    parser.add_argument("--date", default=None, help="Trade date YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--start-date", default="20250101", help="Backtest start date YYYYMMDD.")
    parser.add_argument("--data-dir", default="data/fund_tail")
    parser.add_argument("--report", default="reports/fund_tail_backtest.csv")
    parser.add_argument("--raw-report", default="reports/fund_tail_backtest_raw.csv")
    parser.add_argument("--output-dir", default="reports/fund_tail_advice")
    parser.add_argument("--force", action="store_true", help="Run outside trading day/tail session.")
    parser.add_argument("--skip-download", action="store_true", help="Use existing CSV report.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trade_date = date.fromisoformat(args.date) if args.date else date.today()
    scheduler = TradingScheduler()
    if not args.force and not scheduler.is_trading_day(trade_date):
        print(f"{trade_date} is not a trading day. Use --force to run anyway.")
        return
    if not args.force and not scheduler.is_tail_session():
        print("Not in tail session. Use --force for a manual run.")
        return

    data_dir = ROOT / args.data_dir
    report_path = ROOT / args.report
    raw_report_path = ROOT / args.raw_report
    if not args.skip_download:
        run_backtest_script(
            python_bin=sys.executable,
            data_dir=data_dir,
            report=report_path,
            raw_report=raw_report_path,
            start_date=args.start_date,
            end_date=trade_date.strftime("%Y%m%d"),
        )

    report = pd.read_csv(report_path, dtype={"基金代码": str})
    markdown = build_markdown_report(report, trade_date=trade_date.isoformat())

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    dated = output_dir / f"{trade_date.isoformat()}.md"
    latest = output_dir / "latest.md"
    dated.write_text(markdown, encoding="utf-8")
    latest.write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"Report saved: {dated}")
    print(f"Latest report: {latest}")


if __name__ == "__main__":
    main()
