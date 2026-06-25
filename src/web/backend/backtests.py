"""Backtest API models and runners."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd
from pydantic import AliasChoices, BaseModel, Field, model_validator

from src.core.constants import format_symbol
from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.research_dataset import load_research_dataset
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.scoring import FactorScoreEngine, Selection


class TailBacktestRequest(BaseModel):
    """Request body for tail-session backtest jobs."""

    start: date = Field(validation_alias=AliasChoices("start", "start_date"))
    end: date = Field(validation_alias=AliasChoices("end", "end_date"))
    capital: float = Field(default=100_000, gt=0, validation_alias=AliasChoices("capital", "initial_cash"))
    top_n: int = Field(default=5, ge=1)
    hold_days: int = Field(default=1, ge=1)
    min_score: float | None = None
    min_market_breadth_above_ma20: float | None = None
    dataset_id: str | None = None
    dataset_path: str | None = None
    symbols: list[str] | None = None
    sample: bool = Field(default=False, validation_alias=AliasChoices("sample", "use_sample"))
    source: Literal["clickhouse", "dataset"] = "clickhouse"

    @model_validator(mode="after")
    def require_dataset_or_sample(self) -> "TailBacktestRequest":
        if (self.dataset_path or self.dataset_id) and self.source == "clickhouse":
            self.source = "dataset"
        if not self.sample and self.source == "dataset" and not self.dataset_path and not self.dataset_id:
            raise ValueError("dataset_path or dataset_id is required unless sample is true")
        return self


ProgressCallback = Callable[[int, str, str], None]


def run_tail_backtest(
    request: TailBacktestRequest,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run a tail-session backtest and return UI-friendly result data."""
    _report_progress(progress, 10, "loading_data", "加载回测数据")
    bars = _load_bars(request)
    if bars.empty:
        raise ValueError(_empty_bars_message(request))

    _report_progress(progress, 30, "computing_factors", "计算尾盘因子和每日选股")
    factors = _tail_factors(request)
    rebalance_selections = _rebalance_selections(
        bars=bars,
        factors=factors,
        top_n=request.top_n,
        min_score=request.min_score,
    )
    _report_progress(progress, 65, "simulating_events", "执行次日开盘事件回测")
    event_result = _run_tail_event_backtest(
        request=request,
        bars=bars,
        selections=rebalance_selections,
    )
    trades = event_result["trades"]
    position_outcomes = event_result["position_outcomes"]
    _report_progress(progress, 85, "building_result", "生成图表和交易明细")
    return {
        "experiment": _experiment_summary(request, bars, factors),
        "metrics": event_result["metrics"],
        "trade_count": len(trades),
        "symbol_count": int(bars.index.get_level_values("symbol").nunique()),
        "universe_symbols": sorted(map(str, bars.index.get_level_values("symbol").unique())),
        "latest_selection": _latest_selection(rebalance_selections),
        "rebalance_selections": rebalance_selections,
        "tail_verifications": _tail_verifications(
            request=request,
            selections=_latest_selection(rebalance_selections),
        ),
        "daily_return_curve": _daily_return_curve(event_result["daily_returns"]),
        "monthly_returns": _monthly_returns(event_result["daily_returns"]),
        "equity_curve": event_result["equity_curve"],
        "drawdown_curve": _drawdown_curve(event_result["portfolio_values"]),
        "trades": trades,
        "position_outcomes": position_outcomes,
        "outcome_summary": _outcome_summary(position_outcomes, trades),
    }


def _report_progress(
    progress: ProgressCallback | None,
    percent: int,
    stage: str,
    message: str,
) -> None:
    if progress is not None:
        progress(percent, stage, message)


def _load_bars(request: TailBacktestRequest) -> pd.DataFrame:
    if request.sample:
        return _sample_bars(request.start, request.end)
    if request.source == "dataset":
        return _load_dataset(request)
    return _load_clickhouse_bars(request)


def _load_dataset(request: TailBacktestRequest) -> pd.DataFrame:
    if request.dataset_path is None:
        return pd.DataFrame()
    return load_research_dataset(
        Path(request.dataset_path),
        symbols=request.symbols,
        start=request.start,
        end=request.end,
    )


def _load_clickhouse_bars(request: TailBacktestRequest) -> pd.DataFrame:
    clickhouse = ClickHouseStockDataSource()._client_instance()
    symbols = _clickhouse_symbols(clickhouse, request)
    if not symbols:
        return pd.DataFrame()
    rows = clickhouse.execute(
        """
        select symbol, date, open, high, low, close, volume, amount
        from daily_kline
        where symbol in %(symbols)s and date >= %(start)s and date <= %(end)s
            and open > 0 and high > 0 and low > 0 and close > 0 and volume > 0
        order by date, symbol
        """,
        {
            "symbols": tuple(symbol.split(".")[0].zfill(6) for symbol in symbols),
            "start": request.start,
            "end": request.end,
        },
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows,
        columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
    )
    df["symbol"] = df["symbol"].astype(str).map(format_symbol)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df = df[
        (df["open"] > 0)
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
        & (df["volume"] > 0)
    ].copy()
    df["adjusted_close"] = df["close"]
    return df[
        ["date", "open", "high", "low", "close", "volume", "amount", "adjusted_close", "symbol"]
    ].drop_duplicates(["date", "symbol"]).set_index(["date", "symbol"]).sort_index()


def _clickhouse_symbols(client: Any, request: TailBacktestRequest) -> list[str]:
    if request.symbols:
        return [format_symbol(symbol) for symbol in request.symbols]
    rows = client.execute(
        """
        select
            d.symbol as symbol,
            count() as bars,
            max(d.date) as end_date,
            avg(d.amount) as avg_amount,
            avg(d.volume) as avg_volume
        from daily_kline d
        any left join stocks s on d.symbol = s.symbol
        where d.date >= %(start)s and d.date <= %(end)s
            and d.volume > 0
            and d.amount > 0
            and positionUTF8(coalesce(s.name, ''), 'ST') = 0
        group by symbol
        having bars >= 30
        order by avg_amount desc, avg_volume desc, d.symbol asc
        """,
        {"start": request.start, "end": request.end},
    )
    return [format_symbol(str(symbol)) for symbol, *_rest in rows]


def _empty_bars_message(request: TailBacktestRequest) -> str:
    parts = [
        "No bars available after applying filters",
        f"requested={request.start.isoformat()}..{request.end.isoformat()}",
        f"universe={_universe_source(request)}",
    ]
    if request.dataset_id:
        parts.append(f"dataset_id={request.dataset_id}")
    if request.dataset_path:
        parts.extend(_dataset_filter_context(Path(request.dataset_path), request.symbols))
    if request.symbols:
        preview = ",".join(request.symbols[:8])
        suffix = "..." if len(request.symbols) > 8 else ""
        parts.append(f"symbols={preview}{suffix}")
    return "; ".join(parts)


def _dataset_filter_context(dataset_path: Path, symbols: list[str] | None) -> list[str]:
    if not dataset_path.exists():
        return [f"dataset_path_missing={dataset_path}"]
    try:
        df = pd.read_parquet(dataset_path, columns=["date", "symbol"])
    except Exception as exc:
        return [f"dataset_read_error={exc}"]
    if df.empty:
        return ["available=empty"]
    dates = pd.to_datetime(df["date"])
    parts = [f"available={dates.min().date().isoformat()}..{dates.max().date().isoformat()}"]
    available_symbols = set(map(str, df["symbol"].dropna().unique()))
    if symbols:
        matched = sorted(set(symbols) & available_symbols)
        missing = sorted(set(symbols) - available_symbols)
        parts.append(f"matched_symbols={len(matched)}/{len(symbols)}")
        if missing:
            preview = ",".join(missing[:8])
            suffix = "..." if len(missing) > 8 else ""
            parts.append(f"missing_symbols={preview}{suffix}")
    return parts


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


def _run_tail_event_backtest(
    *,
    request: TailBacktestRequest,
    bars: pd.DataFrame,
    selections: list[dict[str, Any]],
) -> dict[str, Any]:
    dates = sorted(bars.index.get_level_values("date").unique())
    date_to_index = {pd.Timestamp(value).date().isoformat(): index for index, value in enumerate(dates)}
    selections_by_date: dict[str, list[dict[str, Any]]] = {}
    for selection in selections:
        selections_by_date.setdefault(selection["date"], []).append(selection)

    trades: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    realized_by_date: dict[str, float] = {}
    allocation = request.capital / max(request.top_n, 1)
    trade_counter = 1

    for signal_date in sorted(selections_by_date):
        signal_index = date_to_index.get(signal_date)
        if signal_index is None or signal_index + 1 >= len(dates):
            continue
        entry_date = pd.Timestamp(dates[signal_index + 1])
        exit_index = min(signal_index + request.hold_days, len(dates) - 1)
        exit_date = pd.Timestamp(dates[exit_index])
        if exit_date < entry_date:
            exit_date = entry_date

        for selection in selections_by_date[signal_date]:
            symbol = selection["symbol"]
            try:
                signal_bar = bars.loc[(pd.Timestamp(signal_date), symbol)]
                entry_bar = bars.loc[(entry_date, symbol)]
                exit_bar = bars.loc[(exit_date, symbol)]
            except KeyError:
                continue

            entry_price = float(entry_bar["open"])
            exit_price = float(exit_bar["close"])
            if entry_price <= 0 or exit_price <= 0:
                continue
            quantity = int(allocation / entry_price)
            if quantity <= 0:
                continue

            buy_amount = round(entry_price * quantity, 2)
            sell_amount = round(exit_price * quantity, 2)
            buy_commission = _commission(buy_amount)
            sell_commission = _commission(sell_amount)
            realized_pnl = round((exit_price - entry_price) * quantity - buy_commission - sell_commission, 2)
            return_pct = (exit_price / entry_price - 1) * 100
            exit_date_text = exit_date.date().isoformat()
            realized_by_date[exit_date_text] = realized_by_date.get(exit_date_text, 0.0) + realized_pnl

            trades.append({
                "trade_id": f"T{trade_counter:06d}",
                "symbol": symbol,
                "side": "buy",
                "price": round(entry_price, 4),
                "quantity": quantity,
                "amount": buy_amount,
                "commission": buy_commission,
                "date": entry_date.date().isoformat(),
                "signal_date": signal_date,
                "signal_close": round(float(signal_bar["close"]), 4),
                "price_source": "next_open",
                "realized_pnl": 0.0,
                "selection_score": selection.get("score"),
                "selection_rank": selection.get("rank"),
                "reason": f"tail_signal_rank_{selection.get('rank')}_next_open_entry",
            })
            trade_counter += 1
            trades.append({
                "trade_id": f"T{trade_counter:06d}",
                "symbol": symbol,
                "side": "sell",
                "price": round(exit_price, 4),
                "quantity": quantity,
                "amount": sell_amount,
                "commission": sell_commission,
                "date": exit_date_text,
                "signal_date": signal_date,
                "signal_close": round(float(signal_bar["close"]), 4),
                "price_source": "exit_close",
                "realized_pnl": realized_pnl,
                "selection_score": selection.get("score"),
                "selection_rank": selection.get("rank"),
                "reason": f"hold_{request.hold_days}_trading_day_exit",
            })
            trade_counter += 1
            outcomes.append({
                "symbol": symbol,
                "status": "closed",
                "signal_date": signal_date,
                "buy_date": entry_date.date().isoformat(),
                "sell_date": exit_date_text,
                "holding_days": _trading_day_diff(dates, entry_date, exit_date),
                "quantity": quantity,
                "buy_price": round(entry_price, 4),
                "sell_price": round(exit_price, 4),
                "signal_close": round(float(signal_bar["close"]), 4),
                "return_pct": round(return_pct, 4),
                "realized_pnl": realized_pnl,
                "buy_reason": f"rank_{selection.get('rank')}_selected_on_signal_day",
                "sell_reason": f"hold_{request.hold_days}_trading_day_exit",
            })

    portfolio_values = _event_portfolio_values(dates, request.capital, realized_by_date)
    daily_returns = portfolio_values.pct_change().fillna(0.0)
    return {
        "trades": trades,
        "position_outcomes": outcomes,
        "portfolio_values": portfolio_values,
        "daily_returns": daily_returns,
        "equity_curve": [
            {"date": pd.Timestamp(idx).date().isoformat(), "value": round(float(value), 4)}
            for idx, value in portfolio_values.items()
        ],
        "metrics": _event_metrics(
            daily_returns=daily_returns,
            portfolio_values=portfolio_values,
            initial_capital=request.capital,
            outcomes=outcomes,
        ),
    }


def _commission(amount: float) -> float:
    return round(max(amount * 0.0003, 5.0), 2)


def _trading_day_diff(dates: list[Any], start: pd.Timestamp, end: pd.Timestamp) -> int:
    start_date = start.date().isoformat()
    end_date = end.date().isoformat()
    text_dates = [pd.Timestamp(value).date().isoformat() for value in dates]
    return max(text_dates.index(end_date) - text_dates.index(start_date) + 1, 1)


def _event_portfolio_values(
    dates: list[Any],
    initial_capital: float,
    realized_by_date: dict[str, float],
) -> pd.Series:
    values = []
    current_value = initial_capital
    index = []
    for current_date in dates:
        date_text = pd.Timestamp(current_date).date().isoformat()
        current_value += realized_by_date.get(date_text, 0.0)
        values.append(current_value)
        index.append(pd.Timestamp(current_date))
    return pd.Series(values, index=pd.DatetimeIndex(index), name="portfolio_value")


def _event_metrics(
    *,
    daily_returns: pd.Series,
    portfolio_values: pd.Series,
    initial_capital: float,
    outcomes: list[dict[str, Any]],
) -> dict[str, float]:
    if portfolio_values.empty:
        return {}
    final_value = float(portfolio_values.iloc[-1])
    total_return = (final_value / initial_capital - 1) if initial_capital > 0 else 0.0
    n_days = max(len(daily_returns), 1)
    annualized_return = (1 + total_return) ** (252 / n_days) - 1
    annualized_volatility = float(daily_returns.std() * (252 ** 0.5)) if len(daily_returns) > 1 else 0.0
    sharpe = (annualized_return - 0.02) / annualized_volatility if annualized_volatility > 0 else 0.0
    running_max = portfolio_values.cummax()
    drawdown = (portfolio_values - running_max) / running_max
    returns = [float(row.get("return_pct", 0.0)) for row in outcomes]
    return {
        "total_return": round(total_return * 100, 2),
        "annualized_return": round(annualized_return * 100, 2),
        "annualized_volatility": round(annualized_volatility * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(float(drawdown.min()) * 100, 2),
        "calmar_ratio": round(annualized_return / abs(float(drawdown.min())), 3) if float(drawdown.min()) != 0 else 0,
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 2) if returns else 0.0,
        "trading_days": n_days,
        "final_value": round(final_value, 2),
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
        "mode": _experiment_mode(request),
        "dataset_id": request.dataset_id,
        "dataset_path": request.dataset_path,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "actual_start": pd.Timestamp(dates[0]).date().isoformat() if dates else None,
        "actual_end": pd.Timestamp(dates[-1]).date().isoformat() if dates else None,
        "capital": request.capital,
        "top_n": request.top_n,
        "hold_days": request.hold_days,
        "universe_source": _universe_source(request),
        "requested_symbols": request.symbols or [],
        "min_score": request.min_score,
        "min_market_breadth_above_ma20": request.min_market_breadth_above_ma20,
        "rebalance_days": 1,
        "factor_weights": {factor.name: weight for factor, weight in zip(factors, [0.7, 0.3])},
        "execution_assumption": "tail signal today, next-session open execution",
        "notes": [
            "Signals are selected after the signal-day tail session; entries execute on the next trading day's open.",
            f"Each event exits after {request.hold_days} trading day(s) using the exit day's close.",
            "Selections use weighted cross-sectional ranks from tail_session and overnight_momentum factors.",
        ],
    }


def _universe_source(request: TailBacktestRequest) -> str:
    if request.sample:
        return "sample_fixed"
    if request.symbols:
        return "custom_symbols"
    if request.source == "clickhouse":
        return "clickhouse_strategy_tradable"
    return "dataset_all"


def _experiment_mode(request: TailBacktestRequest) -> str:
    if request.sample:
        return "sample"
    return request.source


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
