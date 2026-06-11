"""Backtest API models and runners."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from src.data.research_dataset import load_research_dataset
from src.strategy.engine.backtest import BacktestEngine
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.scoring import FactorScoreEngine, Selection


class TailBacktestRequest(BaseModel):
    """Request body for tail-session backtest jobs."""

    start: date
    end: date
    capital: float = Field(default=100_000, gt=0)
    top_n: int = Field(default=5, ge=1)
    min_score: float | None = None
    min_market_breadth_above_ma20: float | None = None
    dataset_id: str | None = None
    dataset_path: str | None = None
    symbols: list[str] | None = None
    sample: bool = False

    @model_validator(mode="after")
    def require_dataset_or_sample(self) -> "TailBacktestRequest":
        if not self.sample and not self.dataset_path and not self.dataset_id:
            raise ValueError("dataset_path or dataset_id is required unless sample is true")
        return self


def run_tail_backtest(request: TailBacktestRequest) -> dict[str, Any]:
    """Run a tail-session backtest and return UI-friendly result data."""
    bars = _sample_bars(request.start, request.end) if request.sample else _load_dataset(request)
    if bars.empty:
        raise ValueError("No bars available for backtest")

    factors = _tail_factors(request)
    engine = BacktestEngine(
        bars=bars,
        factors=factors,
        factor_weights=[0.7, 0.3],
        top_n=request.top_n,
        rebalance_days=1,
        initial_capital=request.capital,
        equal_weight=True,
        min_score=request.min_score,
    )
    result = engine.run()
    rebalance_selections = _rebalance_selections(
        bars=bars,
        factors=factors,
        top_n=request.top_n,
        min_score=request.min_score,
    )
    return {
        "metrics": result.metrics,
        "trade_count": len(result.trades),
        "symbol_count": int(bars.index.get_level_values("symbol").nunique()),
        "universe_symbols": sorted(map(str, bars.index.get_level_values("symbol").unique())),
        "latest_selection": _latest_selection(rebalance_selections),
        "rebalance_selections": rebalance_selections,
        "equity_curve": [
            {"date": pd.Timestamp(idx).date().isoformat(), "value": float(value)}
            for idx, value in result.portfolio_values.items()
        ],
        "drawdown_curve": _drawdown_curve(result.portfolio_values),
        "trades": [_trade_row(trade) for trade in result.trades],
    }


def _load_dataset(request: TailBacktestRequest) -> pd.DataFrame:
    if request.dataset_path is None:
        return pd.DataFrame()
    return load_research_dataset(
        Path(request.dataset_path),
        symbols=request.symbols,
        start=request.start,
        end=request.end,
    )


def _sample_bars(start: date, end: date) -> pd.DataFrame:
    dates = pd.bdate_range(start, end)
    if len(dates) < 30:
        dates = pd.bdate_range(start, periods=35)

    rows = []
    symbols = ["000001.SZ", "600519.SH", "300750.SZ"]
    for symbol_index, symbol in enumerate(symbols):
        base = 10.0 + symbol_index * 5
        for index, current_date in enumerate(dates):
            close = base + index * (0.08 + symbol_index * 0.02)
            if symbol == "600519.SH" and index == len(dates) - 1:
                close += 3.0
            volume = 1_000_000 + index * 1_000
            if symbol == "600519.SH" and index == len(dates) - 1:
                volume *= 3
            rows.append({
                "date": current_date,
                "symbol": symbol,
                "open": close * 0.995,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": volume,
                "amount": close * volume,
                "adjusted_close": close,
            })
    return pd.DataFrame(rows).set_index(["date", "symbol"]).sort_index()


def _drawdown_curve(values: pd.Series) -> list[dict[str, Any]]:
    if values.empty:
        return []
    running_max = values.cummax()
    drawdown = (values - running_max) / running_max
    return [
        {"date": pd.Timestamp(idx).date().isoformat(), "value": float(value)}
        for idx, value in drawdown.items()
    ]


def _tail_factors(request: TailBacktestRequest):
    return [
        TailSessionFactor(
            breakout_window=20,
            trend_window=5,
            volume_ratio_threshold=1.2,
            min_market_breadth_above_ma20=request.min_market_breadth_above_ma20,
        ),
        OvernightMomentumFactor(smoothing_window=1),
    ]


def _rebalance_selections(
    *,
    bars: pd.DataFrame,
    factors: list,
    top_n: int,
    min_score: float | None,
) -> list[dict[str, Any]]:
    scorer = FactorScoreEngine(
        factors=factors,
        factor_weights=[0.7, 0.3],
        top_n=top_n,
        min_score=min_score,
    )
    rows: list[dict[str, Any]] = []
    dates = sorted(bars.index.get_level_values("date").unique())
    for current_date in dates:
        historical = bars[bars.index.get_level_values("date") <= current_date]
        for selection in scorer.select(historical, pd.Timestamp(current_date).date()):
            rows.append(_selection_row(selection, bars))
    return rows


def _selection_row(selection: Selection, bars: pd.DataFrame) -> dict[str, Any]:
    date_value = pd.Timestamp(selection.date)
    close = None
    try:
        close = float(bars.loc[(date_value, selection.symbol), "close"])
    except KeyError:
        pass
    return {
        "date": date_value.date().isoformat(),
        "rank": selection.rank,
        "symbol": selection.symbol,
        "score": round(selection.score, 6),
        "close": close,
    }


def _latest_selection(selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not selections:
        return []
    latest_date = max(row["date"] for row in selections)
    return [row for row in selections if row["date"] == latest_date]


def _trade_row(trade) -> dict[str, Any]:
    row = trade.to_dict()
    row["date"] = pd.Timestamp(row["date"]).date().isoformat()
    return row
