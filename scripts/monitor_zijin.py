#!/usr/bin/env python
"""Generate a local Zijin Mining monitoring report."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.aggregator import DataAggregator
from src.monitoring.zijin import (
    MonitorSnapshot,
    ProductionInput,
    evaluate_production,
    evaluate_trend,
    render_markdown_report,
)

COMMODITY_FUTURES_SYMBOLS = {
    "gold": "AU0",
    "copper": "CU0",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/zijin_monitor.yaml")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    config = _load_config(Path(args.config))
    report_date = date.fromisoformat(args.date)
    output_dir = Path(args.output_dir or config.get("output_dir", "reports/zijin_monitor"))
    output_dir.mkdir(parents=True, exist_ok=True)

    stock_symbol = str(config.get("stock_symbol", "601899.SH"))
    stock_bars = _load_stock_bars(stock_symbol, report_date)
    trends = [evaluate_trend("zijin", stock_bars)]

    for name, csv_path in config.get("commodity_csv", {}).items():
        bars = _load_commodity_bars(str(name), str(csv_path))
        if not bars.empty:
            trends.append(evaluate_trend(str(name), bars))

    production_cfg = config.get("production", {})
    production_inputs = [
        ProductionInput(
            name=str(item["name"]),
            annual_target=float(item["annual_target"]),
            actual_ytd=float(item["actual_ytd"]),
            unit=str(item["unit"]),
        )
        for item in production_cfg.get("items", [])
    ]
    production = evaluate_production(
        production_inputs,
        elapsed_ratio=float(production_cfg.get("elapsed_ratio", 0.25)),
    )

    quote = _load_stock_quote(stock_symbol)
    snapshot = MonitorSnapshot(
        date=report_date.isoformat(),
        stock_symbol=stock_symbol,
        stock_price=quote.get("price"),
        stock_change_pct=quote.get("change_pct"),
        trends=trends,
        production=production,
    )

    output_path = output_dir / f"{report_date.isoformat()}.md"
    output_path.write_text(render_markdown_report(snapshot), encoding="utf-8")
    print(output_path)


def _load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_stock_bars(symbol: str, report_date: date) -> pd.DataFrame:
    start = report_date - timedelta(days=140)
    df = DataAggregator().get_bars(symbol, start, report_date, use_cache=True)
    if df.empty:
        raise RuntimeError(f"could not load stock bars for {symbol}")
    return df


def _load_stock_quote(symbol: str) -> dict[str, float]:
    df = DataAggregator().get_realtime_quotes([symbol])
    if df.empty:
        return {}
    row = df.iloc[0]
    return {
        "price": float(row["price"]),
        "change_pct": float(row["change_pct"]),
    }


def _load_csv_bars(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "close" not in df.columns:
        raise RuntimeError(f"{path} must contain a close column")
    return df


def _load_commodity_bars(name: str, csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)
    if path.exists():
        return _load_csv_bars(path)

    symbol = COMMODITY_FUTURES_SYMBOLS.get(name)
    if symbol is None:
        return pd.DataFrame()

    try:
        import akshare as ak

        return ak.futures_zh_daily_sina(symbol=symbol)
    except Exception:
        return pd.DataFrame()


if __name__ == "__main__":
    main()
