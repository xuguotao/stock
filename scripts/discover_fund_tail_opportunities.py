#!/usr/bin/env python
"""Discover fund tail-session opportunities from an existing advice report."""

from __future__ import annotations

import argparse
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
    parser.add_argument("--candidate-file", default="config/fund_tail_candidates.csv")
    parser.add_argument("--report", default="reports/fund_tail_opportunities.csv")
    parser.add_argument("--markdown", default="reports/fund_tail_opportunities/latest.md")
    return parser.parse_args()


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
