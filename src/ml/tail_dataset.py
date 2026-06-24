"""Dataset assembly for tail-session ML training."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.core.constants import format_symbol
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.ml.tail_features import DEFAULT_DECISION_TIMES, build_tail_feature_frame
from src.ml.tail_labels import build_tail_label_frame


@dataclass(frozen=True)
class TailMlDatasetResult:
    samples: pd.DataFrame
    summary: dict[str, int]


def build_tail_ml_samples(
    *,
    daily_bars: pd.DataFrame,
    minute5_bars: pd.DataFrame,
    decision_times: Iterable[time] = DEFAULT_DECISION_TIMES,
) -> TailMlDatasetResult:
    """Build features + labels and return a quality summary."""
    features = build_tail_feature_frame(
        daily_bars=daily_bars,
        minute5_bars=minute5_bars,
        decision_times=decision_times,
    )
    labels = build_tail_label_frame(daily_bars=daily_bars, feature_frame=features)
    if features.empty or labels.empty:
        samples = pd.DataFrame()
    else:
        samples = features.merge(
            labels,
            on=["trade_date", "symbol", "decision_time"],
            how="left",
        )
    summary = {
        "feature_rows": int(len(features)),
        "label_rows": int(len(labels)),
        "sample_rows": int(len(samples)),
        "symbols": int(samples["symbol"].nunique()) if not samples.empty else 0,
        "trade_dates": int(samples["trade_date"].nunique()) if not samples.empty else 0,
        "null_label_rows": int(samples["outcome_date"].isna().sum()) if not samples.empty and "outcome_date" in samples else 0,
    }
    return TailMlDatasetResult(samples=samples, summary=summary)


def build_tail_ml_samples_from_clickhouse(
    *,
    client: Any | None = None,
    start: date,
    end: date,
    symbols: list[str] | None = None,
    decision_times: Iterable[time] = DEFAULT_DECISION_TIMES,
) -> TailMlDatasetResult:
    """Load ClickHouse daily/minute5 bars and build tail ML samples."""
    clickhouse = client or ClickHouseStockDataSource()._client_instance()
    query_symbols = tuple(_code(symbol) for symbol in symbols) if symbols else tuple()
    daily_bars = _load_daily_bars(clickhouse, start=start, end=end, symbols=query_symbols)
    minute5_bars = _load_minute5_bars(clickhouse, start=start, end=end, symbols=query_symbols)
    return build_tail_ml_samples(
        daily_bars=daily_bars,
        minute5_bars=minute5_bars,
        decision_times=decision_times,
    )


def write_tail_ml_samples_cache(result: TailMlDatasetResult, output_path: str | Path) -> dict[str, int | str]:
    """Persist a validated sample frame as parquet cache."""
    if result.samples.empty:
        raise ValueError("cannot write empty tail ML samples")
    if int(result.summary.get("null_label_rows") or 0) > 0:
        raise ValueError(f"cannot write tail ML samples with null labels: {result.summary['null_label_rows']}")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result.samples.to_parquet(path, index=False)
    return {
        "path": str(path),
        "sample_rows": int(result.summary["sample_rows"]),
        "symbols": int(result.summary["symbols"]),
        "trade_dates": int(result.summary["trade_dates"]),
        "null_label_rows": int(result.summary["null_label_rows"]),
    }


def _load_daily_bars(client: Any, *, start: date, end: date, symbols: tuple[str, ...]) -> pd.DataFrame:
    params: dict[str, Any] = {"start": start - timedelta(days=60), "end": end + timedelta(days=10)}
    symbol_filter = ""
    if symbols:
        params["symbols"] = symbols
        symbol_filter = "and symbol in %(symbols)s"
    rows = client.execute(
        f"""
        select symbol, date, open, high, low, close, volume, amount
        from daily_kline
        where date >= %(start)s and date <= %(end)s
            {symbol_filter}
            and open > 0 and high > 0 and low > 0 and close > 0 and volume > 0
        order by symbol, date
        """,
        params,
    )
    return _bars_dataframe(rows, date_col="date")


def _load_minute5_bars(client: Any, *, start: date, end: date, symbols: tuple[str, ...]) -> pd.DataFrame:
    params: dict[str, Any] = {"start": start, "end": end}
    symbol_filter = ""
    if symbols:
        params["symbols"] = symbols
        symbol_filter = "and symbol in %(symbols)s"
    rows = client.execute(
        f"""
        select symbol, datetime, open, high, low, close, volume, amount
        from minute5_kline
        where toDate(datetime) >= %(start)s and toDate(datetime) <= %(end)s
            {symbol_filter}
            and open > 0 and high > 0 and low > 0 and close > 0 and volume > 0
            and toHour(datetime) = 14 and toMinute(datetime) >= 30
        order by symbol, datetime
        """,
        params,
    )
    return _bars_dataframe(rows, date_col="datetime")


def _bars_dataframe(rows: list[tuple[Any, ...]], *, date_col: str) -> pd.DataFrame:
    columns = ["symbol", date_col, "open", "high", "low", "close", "volume", "amount"]
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        return df
    df["symbol"] = df["symbol"].astype(str).map(format_symbol)
    return df


def _code(symbol: str) -> str:
    return str(symbol).split(".")[0].zfill(6)
