"""Tail-session backtest workflow helpers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.constants import format_symbol
from src.data.aggregator import DataAggregator
from src.data.bar_repository import CacheBarRepository
from src.data.research_dataset import dataset_symbols, load_research_dataset


def make_aggregator(fallback_sources: bool = False) -> DataAggregator:
    """Create the data aggregator used by tail-session backtests."""
    if fallback_sources:
        return DataAggregator()

    from src.data.sina_source import SinaSource
    return DataAggregator([SinaSource(rate_limit=0.2)])


def resolve_symbols(
    agg: DataAggregator,
    raw_symbols: list[str] | None,
    limit: int,
) -> list[str]:
    """Resolve CLI symbols or default stock pool."""
    if raw_symbols:
        return [format_symbol(symbol) for symbol in raw_symbols]
    return agg.get_csi300_symbols()[:limit]


def load_bars_with_progress(
    agg: DataAggregator,
    symbols: list[str],
    start: date,
    end: date,
    verbose: bool = True,
) -> pd.DataFrame:
    """Load daily bars symbol-by-symbol so long runs show progress."""
    all_dfs = []
    for index, symbol in enumerate(symbols, start=1):
        if verbose:
            print(f"  [{index:>3}/{len(symbols)}] loading {symbol}...", flush=True)
        df = agg.get_bars(symbol, start, end)
        if df is not None and not df.empty:
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    return combined.set_index(["date", "symbol"])


def load_bars_from_offline_cache(
    bars_dir: str | Path,
    symbols: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Load bars from local parquet cache files, ignoring TTL."""
    return CacheBarRepository(bars_dir).load_range(symbols, start, end)


def load_bars_from_research_dataset(
    dataset_path: str | Path,
    raw_symbols: list[str] | None,
    start: date,
    end: date,
) -> tuple[pd.DataFrame, list[str]]:
    """Load bars from a consolidated research dataset."""
    symbols = [format_symbol(symbol) for symbol in raw_symbols] if raw_symbols else dataset_symbols(dataset_path)
    bars = load_research_dataset(dataset_path, symbols=symbols, start=start, end=end)
    return bars, symbols


def write_metrics_json(path: str | Path, result: Any, symbol_count: int) -> Path:
    """Write backtest metrics to JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol_count": symbol_count,
        "trade_count": len(result.trades),
        "metrics": result.metrics,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def write_selection_rows_json(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write historical selection rows to JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "selection_day_count": len({row["date"] for row in rows}),
        "selection_count": len(rows),
        "selections": rows,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def write_selection_rows_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write historical selection rows to CSV."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["date", "rank", "symbol", "score"]).to_csv(output_path, index=False)
    return output_path
