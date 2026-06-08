"""Local Parquet cache for market data.

Caches data as Parquet files with TTL-based invalidation.
Cache structure:
  data/cache/bars/
    000001.SZ_20200101_20250101.parquet
  data/cache/stock_list.parquet
  data/cache/financials/
    000001.SZ.parquet

TTL defaults:
  bars: 1 day
  stock_list: 7 days
  financials: 90 days
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class DataCache:
    """Parquet-based local cache with TTL."""

    def __init__(self, cache_dir: Path | str | None = None, ttl_days: dict | None = None):
        from config.settings import get_settings
        settings = get_settings()

        self.cache_dir = Path(cache_dir or settings.data.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.ttl_days = ttl_days or settings.data.cache_ttl_days

        # Subdirectories
        self.bars_dir = self.cache_dir / "bars"
        self.financials_dir = self.cache_dir / "financials"
        self.bars_dir.mkdir(exist_ok=True)
        self.financials_dir.mkdir(exist_ok=True)

    def _bars_path(self, symbol: str, start: date, end: date) -> Path:
        """Get cache file path for bars."""
        s = symbol.replace(".", "_")
        return self.bars_dir / f"{s}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"

    def read_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame | None:
        """Read cached bars. Returns None if cache miss or expired."""
        path = self._bars_path(symbol, start, end)
        if not path.exists():
            return None

        mtime = path.stat().st_mtime
        ttl_sec = self.ttl_days.get("bars", 1) * 86400
        if time.time() - mtime > ttl_sec:
            path.unlink(missing_ok=True)
            return None

        try:
            df = pd.read_parquet(path)
            logger.debug(f"Cache hit: bars for {symbol}")
            return df
        except Exception as e:
            logger.warning(f"Cache read failed for {path}: {e}")
            return None

    def write_bars(self, df: pd.DataFrame, symbol: str, start: date, end: date) -> None:
        """Write bars to cache."""
        path = self._bars_path(symbol, start, end)
        df.to_parquet(path, index=False)
        logger.debug(f"Cache write: bars for {symbol} -> {path.name}")

    def _stock_list_path(self) -> Path:
        return self.cache_dir / "stock_list.parquet"

    def read_stock_list(self) -> pd.DataFrame | None:
        path = self._stock_list_path()
        if not path.exists():
            return None

        mtime = path.stat().st_mtime
        ttl_sec = self.ttl_days.get("stock_list", 7) * 86400
        if time.time() - mtime > ttl_sec:
            path.unlink(missing_ok=True)
            return None

        try:
            return pd.read_parquet(path)
        except Exception:
            return None

    def write_stock_list(self, df: pd.DataFrame) -> None:
        df.to_parquet(self._stock_list_path(), index=False)

    def _financials_path(self, symbol: str) -> Path:
        s = symbol.replace(".", "_")
        return self.financials_dir / f"{s}.parquet"

    def read_financials(self, symbol: str) -> pd.DataFrame | None:
        path = self._financials_path(symbol)
        if not path.exists():
            return None

        mtime = path.stat().st_mtime
        ttl_sec = self.ttl_days.get("financials", 90) * 86400
        if time.time() - mtime > ttl_sec:
            path.unlink(missing_ok=True)
            return None

        try:
            return pd.read_parquet(path)
        except Exception:
            return None

    def write_financials(self, df: pd.DataFrame, symbol: str) -> None:
        df.to_parquet(self._financials_path(symbol), index=False)

    def clear(self, data_type: str | None = None) -> None:
        """Clear cache. If data_type is given, only clear that type."""
        if data_type == "bars":
            for f in self.bars_dir.glob("*.parquet"):
                f.unlink()
        elif data_type == "financials":
            for f in self.financials_dir.glob("*.parquet"):
                f.unlink()
        elif data_type == "stock_list":
            self._stock_list_path().unlink(missing_ok=True)
        else:
            for f in self.cache_dir.rglob("*.parquet"):
                f.unlink()
        logger.info(f"Cache cleared: {data_type or 'all'}")
