#!/usr/bin/env python3
"""Download historical A-share daily data.

Downloads daily bars for specified stocks and date range,
caches them locally as Parquet files.

Usage:
    python scripts/download_history.py                          # Download CSI 300, last 5 years
    python scripts/download_history.py --symbols 000001 600519  # Download specific stocks
    python scripts/download_history.py --start 2020-01-01       # Custom date range
    python scripts/download_history.py --clear-cache             # Clear cache first
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from src.core.calendar import get_trading_days
from src.data.aggregator import DataAggregator
from src.data.akshare_source import AKShareSource


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Download A-share historical data")
    parser.add_argument(
        "--symbols", nargs="+", type=str,
        help="Stock codes to download (without suffix, e.g., 000001 600519)"
    )
    parser.add_argument("--start", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cache before downloading")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of stocks (0=all)")
    args = parser.parse_args()

    agg = DataAggregator([AKShareSource(rate_limit=0.15)])

    # Clear cache if requested
    if args.clear_cache:
        agg.cache.clear()
        logger.info("Cache cleared")

    # Date range
    start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else date(2021, 1, 1)
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()

    # Symbols
    if args.symbols:
        from src.core.constants import format_symbol
        symbols = [format_symbol(s) for s in args.symbols]
    else:
        logger.info("Fetching CSI 300 constituent symbols...")
        symbols = agg.get_csi300_symbols()
        logger.info(f"Found {len(symbols)} stocks")

    if args.limit > 0:
        symbols = symbols[:args.limit]

    if not symbols:
        logger.error("No symbols to download")
        return

    # Download
    logger.info(f"Downloading {len(symbols)} stocks from {start} to {end}")

    success = 0
    failed = 0
    for i, sym in enumerate(symbols):
        try:
            df = agg.get_bars(sym, start, end, use_cache=True)
            if not df.empty:
                success += 1
                if (i + 1) % 50 == 0:
                    logger.info(f"Progress: {i + 1}/{len(symbols)} ({success} success, {failed} failed)")
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to download {sym}: {e}")

    logger.info(f"Download complete: {success} success, {failed} failed out of {len(symbols)}")

    # Summary
    cache_files = list(agg.cache.bars_dir.glob("*.parquet"))
    total_size = sum(f.stat().st_size for f in cache_files)
    logger.info(f"Cache: {len(cache_files)} files, {total_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
