"""Fund tail-session advice API helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from scripts.backtest_fund_tail_advice import FUNDS, PROXY_INDEXES
from scripts.daily_fund_tail_advice import build_markdown_report
from src.research.fund_tail_backtest import (
    classify_tail_signals,
    evaluate_forward_returns,
    evaluate_latest_condition,
    summarize_latest_signal,
    to_chinese_report,
)


class FundTailAdviceRequest(BaseModel):
    """Request body for local fund-tail advice jobs."""

    trade_date: date
    fund_codes: list[str] | None = Field(default=None)


@dataclass(frozen=True)
class FundTailPaths:
    """Configured local paths used by fund-tail dashboard features."""

    data_dir: Path = Path("data/fund_tail")
    report_path: Path = Path("reports/fund_tail_backtest.csv")
    raw_report_path: Path = Path("reports/fund_tail_backtest_raw.csv")
    advice_dir: Path = Path("reports/fund_tail_advice")
    markdown_path: Path = Path("reports/fund_tail_advice/latest.md")


def list_fund_universe(data_dir: str | Path) -> list[dict[str, Any]]:
    """Return configured fund universe plus local CSV availability."""
    root = Path(data_dir)
    items = []
    for code, name in FUNDS.items():
        proxy = PROXY_INDEXES.get(code)
        nav_path = root / f"{code}_nav.csv"
        proxy_path = root / f"{code}_proxy.csv"
        items.append(
            {
                "code": code,
                "name": name,
                "proxy_provider": proxy[0] if proxy else "nav",
                "proxy_code": proxy[1] if proxy else code,
                "has_nav": nav_path.exists(),
                "has_proxy": proxy_path.exists(),
                "latest_nav_date": _latest_csv_date(nav_path),
                "latest_proxy_date": _latest_csv_date(proxy_path),
            }
        )
    return items


def load_latest_fund_tail_report(
    report_path: str | Path,
    markdown_path: str | Path,
) -> dict[str, Any]:
    """Load the latest Chinese CSV and Markdown advice report."""
    report = Path(report_path)
    markdown = Path(markdown_path)
    rows: list[dict[str, Any]] = []
    if report.exists():
        rows = pd.read_csv(report, dtype={"基金代码": str}).fillna("").to_dict(orient="records")
    return {
        "rows": rows,
        "markdown": markdown.read_text(encoding="utf-8") if markdown.exists() else "",
        "report_path": str(report),
        "markdown_path": str(markdown),
    }


def run_local_fund_tail_advice(
    paths: FundTailPaths,
    request: FundTailAdviceRequest,
) -> dict[str, Any]:
    """Generate fund-tail advice from existing local CSV inputs."""
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.advice_dir.mkdir(parents=True, exist_ok=True)

    benchmark_path = paths.data_dir / "benchmark.csv"
    benchmark = _read_csv(benchmark_path) if benchmark_path.exists() else None
    rows = []
    for code, name in _selected_funds(request.fund_codes).items():
        proxy = _read_csv(paths.data_dir / f"{code}_proxy.csv")
        nav_path = paths.data_dir / f"{code}_nav.csv"
        nav = _read_csv(nav_path) if nav_path.exists() else proxy
        signals = classify_tail_signals(proxy, benchmark=benchmark)
        metrics = evaluate_forward_returns(signals, nav)
        condition = evaluate_latest_condition(signals, nav)
        rows.append(summarize_latest_signal(name, code, signals, metrics, condition))

    report = pd.DataFrame(rows)
    report.to_csv(paths.raw_report_path, index=False)
    chinese_report = to_chinese_report(report)
    chinese_report.to_csv(paths.report_path, index=False)
    markdown = build_markdown_report(chinese_report, request.trade_date.isoformat())

    dated_path = paths.advice_dir / f"{request.trade_date.isoformat()}.md"
    dated_path.write_text(markdown, encoding="utf-8")
    paths.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    paths.markdown_path.write_text(markdown, encoding="utf-8")
    rows_for_api = chinese_report.fillna("").astype(str).to_dict(orient="records")
    return {
        "row_count": int(len(chinese_report)),
        "rows": rows_for_api,
        "markdown": markdown,
        "report_path": str(paths.report_path),
        "raw_report_path": str(paths.raw_report_path),
        "markdown_path": str(dated_path),
    }


def _selected_funds(fund_codes: list[str] | None) -> dict[str, str]:
    if not fund_codes:
        return dict(FUNDS)
    missing = [code for code in fund_codes if code not in FUNDS]
    if missing:
        raise ValueError(f"Unknown fund codes: {', '.join(missing)}")
    return {code: FUNDS[code] for code in fund_codes}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing input file: {path}")
    return pd.read_csv(path)


def _latest_csv_date(path: Path) -> str | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=["date"])
    if df.empty:
        return None
    return str(df["date"].iloc[-1])[:10]
