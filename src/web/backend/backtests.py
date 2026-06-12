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
    selection_lookup = _selection_lookup(rebalance_selections)
    trades = [_trade_row(trade, selection_lookup) for trade in result.trades]
    position_outcomes = _position_outcomes(trades, bars)
    return {
        "experiment": _experiment_summary(request, bars, factors),
        "metrics": result.metrics,
        "trade_count": len(result.trades),
        "symbol_count": int(bars.index.get_level_values("symbol").nunique()),
        "universe_symbols": sorted(map(str, bars.index.get_level_values("symbol").unique())),
        "latest_selection": _latest_selection(rebalance_selections),
        "rebalance_selections": rebalance_selections,
        "tail_verifications": _tail_verifications(
            request=request,
            selections=_latest_selection(rebalance_selections),
        ),
        "daily_return_curve": _daily_return_curve(result.daily_returns),
        "monthly_returns": _monthly_returns(result.daily_returns),
        "equity_curve": [
            {"date": pd.Timestamp(idx).date().isoformat(), "value": float(value)}
            for idx, value in result.portfolio_values.items()
        ],
        "drawdown_curve": _drawdown_curve(result.portfolio_values),
        "trades": trades,
        "position_outcomes": position_outcomes,
        "outcome_summary": _outcome_summary(position_outcomes, trades),
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
        explanations = _factor_explanations(
            historical,
            factors=factors,
            weights=[0.7, 0.3],
            min_score=min_score,
        )
        for selection in scorer.select(historical, pd.Timestamp(current_date).date()):
            rows.append(_selection_row(selection, bars, explanations))
    return rows


def _selection_row(
    selection: Selection,
    bars: pd.DataFrame,
    explanations: dict[str, dict[str, dict[str, float | None]]],
) -> dict[str, Any]:
    date_value = pd.Timestamp(selection.date)
    close = None
    try:
        close = float(bars.loc[(date_value, selection.symbol), "close"])
    except KeyError:
        pass
    explanation = explanations.get(selection.symbol, {})
    return {
        "date": date_value.date().isoformat(),
        "rank": selection.rank,
        "symbol": selection.symbol,
        "score": round(selection.score, 6),
        "close": close,
        "factor_values": explanation.get("factor_values", {}),
        "factor_contributions": explanation.get("factor_contributions", {}),
    }


def _latest_selection(selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not selections:
        return []
    latest_date = max(row["date"] for row in selections)
    return [row for row in selections if row["date"] == latest_date]


def _trade_row(trade, selection_lookup: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    row = trade.to_dict()
    row["date"] = pd.Timestamp(row["date"]).date().isoformat()
    selected = selection_lookup.get((row["date"], row["symbol"]))
    row["selection_score"] = selected["score"] if selected else None
    row["selection_rank"] = selected["rank"] if selected else None
    if row["side"] == "buy":
        row["reason"] = f"rank_{selected['rank']}_selected" if selected else "selected_by_strategy"
    else:
        row["reason"] = "not_in_current_selection"
    return row


def _experiment_summary(
    request: TailBacktestRequest,
    bars: pd.DataFrame,
    factors: list,
) -> dict[str, Any]:
    dates = sorted(bars.index.get_level_values("date").unique())
    return {
        "mode": "sample" if request.sample else "dataset",
        "dataset_id": request.dataset_id,
        "dataset_path": request.dataset_path,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "actual_start": pd.Timestamp(dates[0]).date().isoformat() if dates else None,
        "actual_end": pd.Timestamp(dates[-1]).date().isoformat() if dates else None,
        "capital": request.capital,
        "top_n": request.top_n,
        "min_score": request.min_score,
        "min_market_breadth_above_ma20": request.min_market_breadth_above_ma20,
        "rebalance_days": 1,
        "factor_weights": {factor.name: weight for factor, weight in zip(factors, [0.7, 0.3])},
        "execution_assumption": "daily close rebalance proxy",
        "notes": [
            "This is a daily-bar proxy backtest, not a minute-level 14:30-15:00 fill simulation.",
            "Selections use weighted cross-sectional ranks from tail_session and overnight_momentum factors.",
        ],
    }


def _factor_explanations(
    bars: pd.DataFrame,
    *,
    factors: list,
    weights: list[float],
    min_score: float | None,
) -> dict[str, dict[str, dict[str, float | None]]]:
    if bars.empty:
        return {}
    latest_date = sorted(bars.index.get_level_values("date").unique())[-1]
    by_symbol: dict[str, dict[str, dict[str, float | None]]] = {}
    for factor, weight in zip(factors, weights):
        values = factor.compute(bars)
        if values.empty:
            continue
        if min_score is not None:
            ranked_source = values.where(values >= min_score)
        else:
            ranked_source = values
        contributions = ranked_source.groupby(level=0).rank(pct=True) * weight
        try:
            raw_today = values.loc[latest_date].squeeze()
            contrib_today = contributions.loc[latest_date].squeeze()
        except KeyError:
            continue
        if isinstance(raw_today, pd.DataFrame):
            raw_today = raw_today.iloc[:, 0]
        if isinstance(contrib_today, pd.DataFrame):
            contrib_today = contrib_today.iloc[:, 0]
        if not isinstance(raw_today, pd.Series) or not isinstance(contrib_today, pd.Series):
            continue
        for symbol, raw_value in raw_today.items():
            row = by_symbol.setdefault(str(symbol), {"factor_values": {}, "factor_contributions": {}})
            row["factor_values"][factor.name] = _float_or_none(raw_value)
            row["factor_contributions"][factor.name] = _float_or_none(contrib_today.get(symbol))
    return by_symbol


def _float_or_none(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), 6)


def _selection_lookup(selections: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["date"], row["symbol"]): row for row in selections}


def _daily_return_curve(returns: pd.Series) -> list[dict[str, Any]]:
    return [
        {"date": pd.Timestamp(idx).date().isoformat(), "value": round(float(value) * 100, 4)}
        for idx, value in returns.items()
    ]


def _monthly_returns(returns: pd.Series) -> list[dict[str, Any]]:
    if returns.empty:
        return []
    monthly = (1 + returns).resample("ME").prod() - 1
    return [
        {"month": pd.Timestamp(idx).strftime("%Y-%m"), "return_pct": round(float(value) * 100, 4)}
        for idx, value in monthly.items()
    ]


def _position_outcomes(trades: list[dict[str, Any]], bars: pd.DataFrame) -> list[dict[str, Any]]:
    open_lots: dict[str, list[dict[str, Any]]] = {}
    outcomes: list[dict[str, Any]] = []
    last_prices = _last_prices(bars)
    last_date = pd.Timestamp(sorted(bars.index.get_level_values("date").unique())[-1]).date().isoformat()
    for trade in trades:
        symbol = trade["symbol"]
        if trade["side"] == "buy":
            open_lots.setdefault(symbol, []).append({
                "symbol": symbol,
                "buy_date": trade["date"],
                "buy_price": trade["price"],
                "quantity": trade["quantity"],
                "buy_amount": trade["amount"],
                "buy_reason": trade["reason"],
            })
            continue

        remaining = int(trade["quantity"])
        lots = open_lots.get(symbol, [])
        while remaining > 0 and lots:
            lot = lots[0]
            qty = min(remaining, int(lot["quantity"]))
            outcomes.append(_closed_outcome(lot, trade, qty))
            lot["quantity"] -= qty
            remaining -= qty
            if lot["quantity"] <= 0:
                lots.pop(0)

    for symbol, lots in open_lots.items():
        for lot in lots:
            if lot["quantity"] <= 0:
                continue
            current_price = last_prices.get(symbol)
            if current_price is None:
                continue
            outcomes.append(_open_outcome(lot, current_price, last_date))
    return outcomes


def _closed_outcome(lot: dict[str, Any], sell: dict[str, Any], quantity: int) -> dict[str, Any]:
    buy_price = float(lot["buy_price"])
    sell_price = float(sell["price"])
    return_pct = (sell_price / buy_price - 1) * 100 if buy_price else 0.0
    return {
        "symbol": lot["symbol"],
        "status": "closed",
        "buy_date": lot["buy_date"],
        "sell_date": sell["date"],
        "holding_days": _date_diff(lot["buy_date"], sell["date"]),
        "quantity": quantity,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "return_pct": round(return_pct, 4),
        "realized_pnl": round((sell_price - buy_price) * quantity, 2),
        "buy_reason": lot.get("buy_reason"),
        "sell_reason": sell.get("reason"),
    }


def _open_outcome(lot: dict[str, Any], current_price: float, current_date: str) -> dict[str, Any]:
    buy_price = float(lot["buy_price"])
    return_pct = (current_price / buy_price - 1) * 100 if buy_price else 0.0
    quantity = int(lot["quantity"])
    return {
        "symbol": lot["symbol"],
        "status": "open",
        "buy_date": lot["buy_date"],
        "sell_date": None,
        "holding_days": _date_diff(lot["buy_date"], current_date),
        "quantity": quantity,
        "buy_price": buy_price,
        "sell_price": None,
        "current_price": round(current_price, 4),
        "return_pct": round(return_pct, 4),
        "unrealized_pnl": round((current_price - buy_price) * quantity, 2),
        "buy_reason": lot.get("buy_reason"),
        "sell_reason": "still_in_position",
    }


def _last_prices(bars: pd.DataFrame) -> dict[str, float]:
    latest_date = sorted(bars.index.get_level_values("date").unique())[-1]
    frame = bars.loc[latest_date]
    return {str(symbol): float(value) for symbol, value in frame["close"].items()}


def _date_diff(start: str, end: str) -> int:
    return int((pd.Timestamp(end) - pd.Timestamp(start)).days)


def _outcome_summary(outcomes: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in outcomes if row["status"] == "closed"]
    open_rows = [row for row in outcomes if row["status"] == "open"]
    realized_pnl = sum(float(row.get("realized_pnl", 0.0)) for row in closed)
    unrealized_pnl = sum(float(row.get("unrealized_pnl", 0.0)) for row in open_rows)
    total_commission = sum(float(row.get("commission", 0.0)) for row in trades)
    returns = [float(row.get("return_pct", 0.0)) for row in outcomes]
    return {
        "closed_positions": len(closed),
        "open_positions": len(open_rows),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_commission": round(total_commission, 2),
        "avg_position_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
        "win_rate_pct": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 2) if returns else 0.0,
    }


def _tail_verifications(
    *,
    request: TailBacktestRequest,
    selections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if request.sample:
        return [_sample_tail_verification(selection) for selection in selections]
    return [
        {
            "symbol": selection["symbol"],
            "date": selection["date"],
            "status": "missing_intraday_data",
            "reason": "No local 1m/5m intraday bars are configured for this dataset run.",
            "signal_time": None,
            "tail_return_pct": None,
            "volume_ratio": None,
            "signal_price": None,
            "close_price": selection.get("close"),
            "bars": [],
        }
        for selection in selections
    ]


def _sample_tail_verification(selection: dict[str, Any]) -> dict[str, Any]:
    close_price = float(selection.get("close") or 10.0)
    start_price = close_price * 0.985
    volumes = [1000, 1100, 1200, 2600, 3000, 3400, 3600]
    times = ["14:25", "14:30", "14:35", "14:40", "14:45", "14:50", "14:55"]
    bars = []
    for index, time_label in enumerate(times):
        progress = index / (len(times) - 1)
        price = start_price + (close_price - start_price) * progress
        bars.append({
            "time": time_label,
            "close": round(price, 4),
            "volume": volumes[index],
        })
    baseline_volume = sum(volumes[:3]) / 3
    tail_volume = sum(volumes[3:]) / 4
    tail_return = (bars[-1]["close"] / bars[1]["close"] - 1) * 100
    return {
        "symbol": selection["symbol"],
        "date": selection["date"],
        "status": "confirmed",
        "reason": "Synthetic sample 5m bars confirm rising tail price and stronger tail volume.",
        "signal_time": "14:50",
        "tail_return_pct": round(tail_return, 4),
        "volume_ratio": round(tail_volume / baseline_volume, 4),
        "signal_price": bars[-2]["close"],
        "close_price": close_price,
        "bars": bars,
    }
