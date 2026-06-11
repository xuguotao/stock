"""Build and load offline research datasets for backtests."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


BAR_COLUMNS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adjusted_close",
]


def build_research_dataset(
    symbols: list[str],
    start: date,
    end: date,
    bars_dir: str | Path,
    output_path: str | Path,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build one normalized parquet dataset from cached per-symbol bars."""
    output = Path(output_path)
    manifest = Path(manifest_path) if manifest_path else output.with_name(f"{output.stem}_manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)

    frames = []
    source_files: dict[str, str] = {}
    missing_symbols = []

    for symbol in symbols:
        df, source_path = _load_symbol_from_cache(Path(bars_dir), symbol, start, end)
        if df.empty:
            missing_symbols.append(symbol)
            continue
        frames.append(df)
        source_files[symbol] = str(source_path)

    if frames:
        dataset = pd.concat(frames, ignore_index=True)
        dataset = dataset[BAR_COLUMNS].drop_duplicates(["date", "symbol"]).sort_values(["date", "symbol"])
    else:
        dataset = pd.DataFrame(columns=BAR_COLUMNS)

    dataset.to_parquet(output, index=False)

    built_symbols = sorted(dataset["symbol"].unique().tolist()) if not dataset.empty else []
    info = {
        "dataset_path": str(output),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols": built_symbols,
        "missing_symbols": missing_symbols,
        "symbol_count": len(built_symbols),
        "row_count": int(len(dataset)),
        "source_files": source_files,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    manifest.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def load_research_dataset(
    dataset_path: str | Path,
    symbols: list[str] | None,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Load a parquet research dataset as MultiIndex(date, symbol) bars."""
    df = pd.read_parquet(dataset_path)
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    if symbols:
        mask &= df["symbol"].isin(symbols)
    df = df[mask]
    if df.empty:
        return pd.DataFrame()
    return df.set_index(["date", "symbol"]).sort_index()


def dataset_symbols(dataset_path: str | Path) -> list[str]:
    """Return sorted symbols available in a research dataset."""
    df = pd.read_parquet(dataset_path, columns=["symbol"])
    return sorted(df["symbol"].dropna().unique().tolist())


def select_liquid_symbols_from_cache(
    bars_dir: str | Path,
    start: date,
    end: date,
    limit: int,
    min_bars: int = 120,
    min_end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Rank cached symbols by average traded value over a date range."""
    rows_by_symbol: dict[str, dict[str, Any]] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    min_end_ts = pd.Timestamp(min_end_date) if min_end_date else None

    for path in Path(bars_dir).glob("*.parquet"):
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if df.empty or not {"date", "symbol", "close", "volume"}.issubset(df.columns):
            continue

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"] >= start_ts) & (df["date"] <= end_ts)
        sample = df[mask]
        if len(sample) < min_bars:
            continue
        if min_end_ts is not None and sample["date"].max() < min_end_ts:
            continue

        symbol = str(sample["symbol"].iloc[0])
        traded_value = _traded_value(sample)
        avg_traded_value = float(traded_value.mean())
        row = {
            "symbol": symbol,
            "avg_traded_value": avg_traded_value,
            "bar_count": int(len(sample)),
            "start": sample["date"].min().date().isoformat(),
            "end": sample["date"].max().date().isoformat(),
            "source_file": str(path),
        }

        existing = rows_by_symbol.get(symbol)
        if existing is None or row["bar_count"] > existing["bar_count"]:
            rows_by_symbol[symbol] = row

    ranked = sorted(
        rows_by_symbol.values(),
        key=lambda row: (row["avg_traded_value"], row["bar_count"], row["symbol"]),
        reverse=True,
    )
    return ranked[:limit]


def _load_symbol_from_cache(
    bars_dir: Path,
    symbol: str,
    start: date,
    end: date,
) -> tuple[pd.DataFrame, Path | None]:
    stem = symbol.replace(".", "_")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    candidates = sorted(bars_dir.glob(f"{stem}_*.parquet"))
    frames = []
    used_paths = []

    for path in candidates:
        df = pd.read_parquet(path)
        if df.empty:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"] >= start_ts) & (df["date"] <= end_ts)
        if not mask.any():
            continue
        frames.append(df.loc[mask, BAR_COLUMNS])
        used_paths.append(path)

    if not frames:
        return pd.DataFrame(columns=BAR_COLUMNS), None

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(["date", "symbol"]).sort_values(["date", "symbol"])
    return combined, used_paths[-1]


def _traded_value(df: pd.DataFrame) -> pd.Series:
    if "amount" in df.columns:
        amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        if (amount > 0).any():
            return amount
    close = pd.to_numeric(df["close"], errors="coerce").fillna(0)
    volume = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return close * volume
