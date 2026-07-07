"""Build reproducible research datasets from ClickHouse daily bars."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.research_dataset import BAR_COLUMNS


def build_clickhouse_research_dataset(
    *,
    start: date,
    end: date,
    output_path: str | Path,
    manifest_path: str | Path | None = None,
    symbols: list[str] | None = None,
    limit: int = 0,
    client: Any | None = None,
) -> dict[str, Any]:
    """Build a standard parquet research dataset from ClickHouse ``daily_kline``."""
    source = ClickHouseStockDataSource()
    clickhouse = client or source._client_instance()
    output = Path(output_path)
    manifest = Path(manifest_path) if manifest_path else output.with_name(f"{output.stem}_manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)

    requested_symbols = _target_symbols(clickhouse, symbols=symbols, limit=limit)
    rows = _daily_rows(clickhouse, start=start, end=end, symbols=requested_symbols)
    dataset = _dataset_frame(rows)
    if requested_symbols and not dataset.empty:
        dataset = dataset[dataset["symbol"].isin(requested_symbols)].copy()
    dataset.to_parquet(output, index=False)

    built_symbols = sorted(dataset["symbol"].unique().tolist()) if not dataset.empty else []
    missing = [symbol for symbol in requested_symbols if symbol not in set(built_symbols)]
    info = {
        "dataset_path": str(output),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols": built_symbols,
        "requested_symbols": requested_symbols,
        "missing_symbols": missing,
        "symbol_count": len(built_symbols),
        "row_count": int(len(dataset)),
        "source": "clickhouse",
        "clickhouse": {
            "table": "daily_kline",
            "host": source.host,
            "database": source.database,
        },
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    manifest.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def _target_symbols(client: Any, *, symbols: list[str] | None, limit: int) -> list[str]:
    if symbols:
        filtered = [format_symbol(symbol) for symbol in symbols]
    else:
        rows = client.execute("select symbol, name, market from stocks final order by symbol")
        filtered = [
            format_symbol(str(code))
            for code, name, market in rows
            if not is_st(str(name or ""))
            and str(market or "").upper() in ("SH", "SZ")
        ]
    if limit and limit > 0:
        return filtered[:limit]
    return filtered


def _daily_rows(client: Any, *, start: date, end: date, symbols: list[str]) -> list[tuple]:
    if not symbols:
        return []
    codes = tuple(symbol.split(".")[0].zfill(6) for symbol in symbols)
    return client.execute(
        """
        select symbol, date, open, high, low, close, volume, amount
        from daily_kline
        where symbol in %(symbols)s and date >= %(start)s and date <= %(end)s
        order by date, symbol
        """,
        {"symbols": codes, "start": start, "end": end},
    )


def _dataset_frame(rows: list[tuple]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=BAR_COLUMNS)
    df = pd.DataFrame(
        rows,
        columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
    )
    df["symbol"] = df["symbol"].astype(str).map(format_symbol)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df["adjusted_close"] = df["close"]
    df = df[BAR_COLUMNS].drop_duplicates(["date", "symbol"])
    # 防御历史 invalid OHLC（如 000937 2020-2021 负价），避免进回测/训练 parquet
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)
