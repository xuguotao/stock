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
    if isinstance(value, str) and value.strip().endswith("%"):
        return value.strip()
    return f"{float(value) * 100:.2f}%"


def _row_value(row: pd.Series, key: str, default: object = "") -> object:
    return row[key] if key in row and pd.notna(row[key]) else default


def _sell_rows(report: pd.DataFrame) -> pd.DataFrame:
    if "卖出建议" not in report.columns:
        return report.iloc[0:0]
    return report[report["卖出建议"].isin(["止盈减仓", "小比例止盈", "止损减仓", "分批减仓"])]


def next_trading_day_label(trade_date: str) -> str:
    """Return the next A-share trading day label for report wording."""
    scheduler = TradingScheduler()
    next_day = scheduler.next_trading_day(date.fromisoformat(trade_date))
    return next_day.isoformat()


def build_markdown_report(report: pd.DataFrame, trade_date: str) -> str:
    """Build a concise human-facing Markdown report from the Chinese CSV."""
    next_trade_label = next_trading_day_label(trade_date)
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

    sell_rows = _sell_rows(report)
    if not sell_rows.empty:
        lines.extend(
            [
                "",
                "## 尾盘卖出/减仓关注",
                "",
                "| 基金 | 代码 | 卖出等级 | 卖出建议 | 卖出原因 | 卖出评分 |",
                "|---|---:|---:|---|---|---:|",
            ]
        )
        for _, row in sell_rows.iterrows():
            lines.append(
                "| {name} | {code} | {grade} | {action} | {reason} | {score} |".format(
                    name=_row_value(row, "基金名称"),
                    code=str(_row_value(row, "基金代码")).zfill(6),
                    grade=_row_value(row, "卖出等级"),
                    action=_row_value(row, "卖出建议"),
                    reason=_row_value(row, "卖出原因"),
                    score=_row_value(row, "卖出评分", "-"),
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
                    f"- 代理：{_row_value(row, '代理标的', '-')}；"
                    f"匹配度：{pct(_row_value(row, '代理匹配度', 0.0))}；"
                    f"匹配等级：{_row_value(row, '代理匹配等级', '-')}"
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
                (
                    f"- 预测：3日上涨概率 {pct(_row_value(row, '3日预测上涨概率', 0.0))}，"
                    f"5日上涨概率 {pct(_row_value(row, '5日预测上涨概率', 0.0))}，"
                    f"5日中位数收益 {pct(_row_value(row, '5日预测中位数收益', 0.0))}，"
                    f"5日跌超2%概率 {pct(_row_value(row, '5日预测跌超2%概率', 0.0))}，"
                    f"评分 {_row_value(row, '预测加仓评分', '-')}"
                ),
                f"- 操作：{_row_value(row, '最终操作建议')}（{_row_value(row, '建议原因')}）",
                (
                    f"- 卖出：{_row_value(row, '卖出建议', '不卖出')}；"
                    f"等级：{_row_value(row, '卖出等级', '-')}；"
                    f"原因：{_row_value(row, '卖出原因', '卖出信号未触发')}"
                ),
                "",
            ]
        )

    lines.extend(
        [
            f"## 下一交易日观察（{next_trade_label}）",
            "",
            "- 高开不追；只有回踩不破且放量修复时，再考虑第二笔。",
            "- 若中间隔周末或节假日，周末消息只作为风险变量，不把非交易日涨跌当成验证信号。",
            "- 连续弱势品种先等企稳，不在贴近日内低位时连续摊平。",
            "- 技术信号和预测结果冲突时，以未来 3-5 日预测胜率、收益和回撤风险为准。",
            "",
            "这不是保证收益的投资建议，只用于辅助你做尾盘加仓和卖出节奏判断。",
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
