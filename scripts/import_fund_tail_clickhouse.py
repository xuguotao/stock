#!/usr/bin/env python
"""Import local fund-tail CSV files into ClickHouse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_fund_tail_advice import FUNDS, PROXY_INDEXES
from src.data.fund_tail_repository import ClickHouseFundTailRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import fund-tail CSV data into ClickHouse")
    parser.add_argument("--data-dir", default="data/fund_tail")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = ClickHouseFundTailRepository().import_csv_directory(
        ROOT / args.data_dir,
        fund_names=FUNDS,
        proxy_specs=PROXY_INDEXES,
    )
    print(result)


if __name__ == "__main__":
    main()
