#!/usr/bin/env python
"""Discover fund tail-session opportunities from an existing advice report."""

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

from src.research.fund_tail_opportunities import (
    build_opportunity_markdown,
    build_opportunity_rows,
    filter_eligible_candidates,
    load_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover fund tail-session opportunities.")
    parser.add_argument("--trade-date", default=date.today().isoformat(), help="Trade date YYYY-MM-DD.")
    parser.add_argument("--advice-report", default="reports/fund_tail_backtest.csv")
    parser.add_argument("--raw-advice-report", default="reports/fund_tail_opportunity_backtest_raw.csv")
    parser.add_argument("--candidate-file", default="config/fund_tail_candidates.csv")
    parser.add_argument("--data-dir", default="data/fund_tail_opportunities")
    parser.add_argument("--start-date", default="20250101", help="Backtest start date YYYYMMDD.")
    parser.add_argument("--end-date", default=None, help="Backtest end date YYYYMMDD. Defaults to --trade-date.")
    parser.add_argument(
        "--refresh-advice",
        action="store_true",
        help="Download and generate an advice report for the candidate universe before discovering opportunities.",
    )
    parser.add_argument("--report", default="reports/fund_tail_opportunities.csv")
    parser.add_argument("--markdown", default="reports/fund_tail_opportunities/latest.md")
    return parser.parse_args()


def refresh_candidate_advice(
    *,
    trade_date: str,
    candidate_file: str | Path,
    data_dir: str | Path,
    advice_report: str | Path,
    raw_advice_report: str | Path,
    start_date: str,
    end_date: str | None,
) -> None:
    actual_end_date = end_date or trade_date.replace("-", "")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "backtest_fund_tail_advice.py"),
        "--download",
        "--candidate-file",
        str(candidate_file),
        "--data-dir",
        str(data_dir),
        "--report",
        str(advice_report),
        "--raw-report",
        str(raw_advice_report),
        "--start-date",
        start_date,
        "--end-date",
        actual_end_date,
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def discover_opportunities(
    *,
    trade_date: str,
    advice_report: str | Path,
    candidate_file: str | Path,
    report: str | Path,
    markdown: str | Path,
    watchlist_codes: set[str] | None = None,
) -> dict[str, object]:
    advice = pd.read_csv(advice_report, dtype={"基金代码": str})
    candidates = filter_eligible_candidates(load_candidates(candidate_file))
    rows = build_opportunity_rows(advice, candidates, watchlist_codes=watchlist_codes or set())
    output = pd.DataFrame(rows)

    report_path = Path(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(report_path, index=False)

    markdown_text = build_opportunity_markdown(rows, trade_date=trade_date)
    markdown_path = Path(markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown_text, encoding="utf-8")

    return {
        "row_count": len(rows),
        "rows": rows,
        "markdown": markdown_text,
        "report_path": str(report_path),
        "markdown_path": str(markdown_path),
    }


def main() -> None:
    args = parse_args()
    if args.refresh_advice:
        refresh_candidate_advice(
            trade_date=args.trade_date,
            candidate_file=args.candidate_file,
            data_dir=args.data_dir,
            advice_report=args.advice_report,
            raw_advice_report=args.raw_advice_report,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    result = discover_opportunities(
        trade_date=args.trade_date,
        advice_report=args.advice_report,
        candidate_file=args.candidate_file,
        report=args.report,
        markdown=args.markdown,
    )
    print(result["markdown"])
    print(f"Opportunity report written to {result['report_path']}")


if __name__ == "__main__":
    main()
