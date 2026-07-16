"""Read published, research-only adjusted daily bars.

This module intentionally has no dependency on the online strategy data paths.
It resolves an explicitly published research run, then requires a matching factor
for every returned raw Mootdx daily bar.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

import pandas as pd

from src.data.research_adjustment_store import ResearchAdjustmentStore


OUTPUT_COLUMNS = [
    "symbol", "trade_date",
    "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_amount",
    "forward_open", "forward_high", "forward_low", "forward_close", "forward_volume", "forward_amount",
    "backward_open", "backward_high", "backward_low", "backward_close", "backward_volume", "backward_amount",
    "forward_factor", "backward_factor", "quality_status",
]


class ResearchAdjustmentReader:
    """Expose only completed, published research adjustment conventions."""

    def __init__(self, client: Any | None = None, store: ResearchAdjustmentStore | None = None) -> None:
        self._store = store or ResearchAdjustmentStore(client=client)
        self._client = client if client is not None else self._store.client

    def get_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        formula_version: str,
    ) -> pd.DataFrame:
        """Return raw, forward, and backward bars for the current published run.

        A missing run or factor is a hard data boundary: this method returns an
        empty frame rather than returning unadjusted raw prices.
        """
        if not symbols:
            return _empty_frame()
        current = self._store.current_run(formula_version)
        if current is None:
            return _empty_frame()
        rows = self._client.execute(
            """
            select
                k.symbol, k.trade_date, k.open, k.high, k.low, k.close, k.volume, k.amount,
                f.forward_factor, f.backward_factor, f.quality_status
            from research_adjustment_raw_bars final as k
            inner join research_daily_adjustment_factors final as f
                on f.symbol = k.symbol
               and f.trade_date = k.trade_date
            where k.symbol in %(symbols)s
              and k.trade_date >= %(start)s
              and k.trade_date <= %(end)s
              and f.run_id = %(run_id)s
              and f.formula_version = %(formula_version)s
              and k.run_id = %(run_id)s
              and k.formula_version = %(formula_version)s
              and f.forward_factor > 0
              and f.backward_factor > 0
            order by k.trade_date, k.symbol
            """,
            {
                "symbols": tuple(str(symbol) for symbol in symbols),
                "start": start,
                "end": end,
                "run_id": current["run_id"],
                "formula_version": formula_version,
            },
        )
        if not rows:
            return _empty_frame()
        frame = pd.DataFrame(
            rows,
            columns=[
                "symbol", "trade_date", "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_amount",
                "forward_factor", "backward_factor", "quality_status",
            ],
        )
        for column in ["raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_amount", "forward_factor", "backward_factor"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["forward_factor", "backward_factor"])
        frame = frame[(frame["forward_factor"] > 0) & (frame["backward_factor"] > 0)].copy()
        if frame.empty:
            return _empty_frame()
        for convention, factor in (("forward", "forward_factor"), ("backward", "backward_factor")):
            for field in ("open", "high", "low", "close"):
                frame[f"{convention}_{field}"] = frame[f"raw_{field}"] * frame[factor]
            frame[f"{convention}_volume"] = frame["raw_volume"] / frame[factor]
            frame[f"{convention}_amount"] = frame["raw_amount"]
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        return frame[OUTPUT_COLUMNS].reset_index(drop=True)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)
