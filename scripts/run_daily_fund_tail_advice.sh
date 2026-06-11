#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/hw-val/Dev/stock"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$ROOT"

"$PYTHON_BIN" scripts/daily_fund_tail_advice.py \
  --start-date 20250101 \
  --data-dir data/fund_tail \
  --report reports/fund_tail_backtest.csv \
  --raw-report reports/fund_tail_backtest_raw.csv \
  "$@"
