"""Repository interface for local daily bar datasets."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.research_dataset import BAR_COLUMNS, select_liquid_symbols_from_cache


class CacheBarRepository:
    """Read daily bars from the project Parquet cache without TTL checks."""

    def __init__(self, bars_dir: str | Path):
        self.bars_dir = Path(bars_dir)

    def load_range(self, symbols: list[str], start: date, end: date) -> pd.DataFrame:
        """Load cached bars for symbols as MultiIndex(date, symbol)."""
        frames = []
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)

        for symbol in symbols:
            bars = self.load_latest_until(symbol, end_ts)
            if bars.empty:
                continue
            mask = (bars["date"] >= start_ts) & (bars["date"] <= end_ts)
            sample = bars[mask]
            if not sample.empty:
                frames.append(sample)

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        return combined.set_index(["date", "symbol"]).sort_index()

    def load_latest_until(self, symbol: str, end_ts: pd.Timestamp) -> pd.DataFrame:
        """Load all cached bars for one symbol up to and including end_ts."""
        stem = symbol.replace(".", "_")
        frames = []
        for path in self.bars_dir.glob(f"{stem}_*.parquet"):
            df = pd.read_parquet(path)
            if df.empty or "date" not in df.columns:
                continue
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["date"] <= end_ts]
            if df.empty:
                continue
            columns = [column for column in BAR_COLUMNS if column in df.columns]
            frames.append(df[columns])

        if not frames:
            return pd.DataFrame(columns=BAR_COLUMNS)

        combined = pd.concat(frames, ignore_index=True)
        return combined.drop_duplicates(["date", "symbol"]).sort_values("date")

    def rank_liquid_symbols(
        self,
        start: date,
        end: date,
        limit: int,
        min_bars: int = 120,
        min_end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Rank cached symbols by average traded value."""
        return select_liquid_symbols_from_cache(
            bars_dir=self.bars_dir,
            start=start,
            end=end,
            limit=limit,
            min_bars=min_bars,
            min_end_date=min_end_date,
        )
