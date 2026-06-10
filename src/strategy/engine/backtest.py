"""Event-driven backtest engine for A-share strategies.

Walks through historical data day by day, generating signals and
executing trades through the simulated broker.

Usage:
    engine = BacktestEngine(
        bars=bars_df,           # MultiIndex (date, symbol)
        factors=[momentum, trend],
        top_n=10,               # Hold top N ranked stocks
        rebalance_days=5,       # Rebalance every N days
        initial_capital=1_000_000,
    )
    result = engine.run()
    print(result.metrics)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from src.core.types import Side
from src.strategy.base import Factor
from src.strategy.execution.broker import SimulatedBroker, Position
from src.strategy.execution.order import Order

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Backtest result with performance metrics."""
    daily_returns: pd.Series
    portfolio_values: pd.Series
    positions_history: pd.DataFrame
    trades: list
    benchmark_returns: pd.Series | None = None
    initial_capital: float = 0.0
    final_value: float = 0.0

    @property
    def metrics(self) -> dict[str, float]:
        """Calculate performance metrics."""
        if self.daily_returns.empty:
            return {}

        returns = self.daily_returns
        n_days = len(returns)

        # Total return
        total_return = (self.final_value / self.initial_capital - 1) if self.initial_capital > 0 else 0

        # Annualized return (252 trading days)
        ann_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1

        # Annualized volatility
        ann_vol = returns.std() * np.sqrt(252) if len(returns) > 1 else 0

        # Sharpe ratio (risk-free rate ~2%)
        sharpe = (ann_return - 0.02) / ann_vol if ann_vol > 0 else 0

        # Max drawdown
        cum_returns = (1 + returns).cumprod()
        running_max = cum_returns.cummax()
        drawdown = (cum_returns - running_max) / running_max
        max_drawdown = drawdown.min()

        # Calmar ratio
        calmar = ann_return / abs(max_drawdown) if max_drawdown != 0 else 0

        # Win rate
        win_rate = (returns > 0).sum() / max(len(returns), 1)

        return {
            "total_return": round(total_return * 100, 2),
            "annualized_return": round(ann_return * 100, 2),
            "annualized_volatility": round(ann_vol * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_drawdown * 100, 2),
            "calmar_ratio": round(calmar, 3),
            "win_rate": round(win_rate * 100, 2),
            "trading_days": n_days,
            "final_value": round(self.final_value, 2),
        }

    def plot(self, title: str = "Backtest Result") -> None:
        """Plot backtest results."""
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1, 1]})
        fig.suptitle(title, fontsize=14)

        # Portfolio value
        ax1 = axes[0]
        self.portfolio_values.plot(ax=ax1, label="Portfolio", color="blue")
        if self.benchmark_returns is not None and not self.benchmark_returns.empty:
            bench = (1 + self.benchmark_returns).cumprod() * self.initial_capital
            bench.plot(ax=ax1, label="Benchmark", alpha=0.5, color="gray")
        ax1.set_ylabel("Portfolio Value")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Drawdown
        ax2 = axes[1]
        cum = (1 + self.daily_returns).cumprod()
        running_max = cum.cummax()
        dd = (cum - running_max) / running_max * 100
        dd.plot(ax=ax2, color="red", alpha=0.5)
        ax2.fill_between(dd.index, dd.values, 0, alpha=0.3, color="red")
        ax2.set_ylabel("Drawdown %")
        ax2.grid(True, alpha=0.3)

        # Daily returns
        ax3 = axes[2]
        self.daily_returns.plot(ax=ax3, kind="bar", color=self.daily_returns.apply(
            lambda x: "green" if x >= 0 else "red"
        ))
        ax3.set_ylabel("Daily Return")
        ax3.set_xlabel("Date")
        ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()


class BacktestEngine:
    """Event-driven backtest engine.

    Uses factor rankings to select top-N stocks and rebalances periodically.
    """

    def __init__(
        self,
        bars: pd.DataFrame,
        factors: list[Factor],
        factor_weights: list[float] | None = None,
        top_n: int = 10,
        rebalance_days: int = 5,
        initial_capital: float = 1_000_000.0,
        equal_weight: bool = True,
        min_score: float | None = None,
    ):
        """Initialize backtest engine.

        Args:
            bars: MultiIndex DataFrame (date, symbol) with OHLCV.
            factors: List of Factor objects to combine.
            factor_weights: Weight for each factor (default: equal).
            top_n: Number of stocks to hold after ranking.
            rebalance_days: Days between rebalancing.
            initial_capital: Starting cash.
            equal_weight: If True, allocate equally to each position.
            min_score: Minimum raw factor score required before ranking.
        """
        self.bars = bars.sort_index()
        self.factors = factors
        self.factor_weights = factor_weights or [1.0 / len(factors)] * len(factors)
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.initial_capital = initial_capital
        self.equal_weight = equal_weight
        self.min_score = min_score

        self.broker = SimulatedBroker(initial_capital=initial_capital)

    def run(self) -> BacktestResult:
        """Run the backtest."""
        dates = sorted(self.bars.index.get_level_values("date").unique())
        logger.info(f"Backtesting {len(dates)} trading days, {len(self.bars.index.unique('symbol'))} symbols")

        daily_returns = []
        portfolio_values = []
        positions_history = []

        prev_value = self.initial_capital

        for i, current_date in enumerate(dates):
            # Update T+1 availability
            self.broker.update_available_positions(current_date)

            # Get today's bars
            try:
                today_bars = self.bars.loc[current_date]
            except KeyError:
                continue

            if isinstance(today_bars, pd.Series):
                today_bars = today_bars.to_frame().T

            # Get current prices
            prices = today_bars["close"].to_dict()

            # Rebalance periodically
            if i % self.rebalance_days == 0:
                # Get historical data up to current date for factor computation
                mask = self.bars.index.get_level_values("date") <= current_date
                historical_bars = self.bars[mask]
                composite_score = self._compute_composite_score(historical_bars)

                if composite_score is not None and not composite_score.empty:
                    # Get today's scores
                    try:
                        today_scores = composite_score.loc[current_date]
                    except KeyError:
                        today_scores = None

                    if today_scores is not None:
                        # Rank and select top-N
                        scores_series = today_scores.squeeze()
                        if isinstance(scores_series, pd.DataFrame):
                            # Multiple columns - take mean across factors
                            scores_series = scores_series.mean(axis=1)
                        scores_series = scores_series.dropna()
                        ranked = scores_series.rank(ascending=False, pct=False)
                        selected = ranked.nsmallest(self.top_n).index.tolist()

                        # Sell positions not in selected
                        current_holdings = set(self.broker.positions.keys())
                        for symbol in current_holdings:
                            if symbol not in selected:
                                pos = self.broker.positions[symbol]
                                sell_price = prices.get(symbol, 0)
                                if sell_price > 0 and pos.available > 0:
                                    from src.strategy.execution.order import Order as O
                                    order = O(symbol=symbol, side=Side.SELL, quantity=pos.available)
                                    self.broker.submit_order(order, current_date, sell_price)

                        # Buy selected stocks
                        if self.equal_weight:
                            cash_per_stock = self.broker.cash / max(self.top_n, 1)
                        else:
                            cash_per_stock = self.broker.cash / max(self.top_n, 1)

                        for symbol in selected:
                            if symbol not in self.broker.positions:
                                buy_price = prices.get(symbol, 0)
                                if buy_price > 0 and cash_per_stock > 0:
                                    qty = int(cash_per_stock / buy_price)
                                    from src.strategy.execution.order import Order as O
                                    order = O(symbol=symbol, side=Side.BUY, quantity=qty)
                                    self.broker.submit_order(order, current_date, buy_price)

            # Record daily portfolio value
            current_value = self.broker.portfolio_value(prices)
            daily_return = (current_value / prev_value - 1) if prev_value > 0 else 0
            daily_returns.append(daily_return)
            portfolio_values.append(current_value)

            # Record positions
            pos_record = {"date": current_date}
            for symbol in self.broker.positions:
                pos_record[symbol] = self.broker.positions[symbol].quantity
            positions_history.append(pos_record)

            prev_value = current_value

        # Build result
        date_index = pd.Index(dates[:len(daily_returns)], name="date")
        returns_series = pd.Series(daily_returns, index=date_index, name="daily_return")
        values_series = pd.Series(portfolio_values, index=date_index, name="portfolio_value")
        pos_df = pd.DataFrame(positions_history).set_index("date").fillna(0)

        return BacktestResult(
            daily_returns=returns_series,
            portfolio_values=values_series,
            positions_history=pos_df,
            trades=self.broker.trades,
            initial_capital=self.initial_capital,
            final_value=portfolio_values[-1] if portfolio_values else self.initial_capital,
        )

    def _compute_composite_score(self, bars_to_date: pd.DataFrame) -> pd.DataFrame | None:
        """Compute weighted composite factor score."""
        if not self.factors:
            return None

        scores = []
        for factor, weight in zip(self.factors, self.factor_weights):
            try:
                values = factor.compute(bars_to_date)
                if not values.empty:
                    if self.min_score is not None:
                        values = values.where(values >= self.min_score)
                    ranked = values.groupby(level=0).rank(pct=True)
                    scores.append(ranked * weight)
            except Exception as e:
                logger.warning(f"Factor {factor.name} failed: {e}")

        if not scores:
            return None

        # Sum weighted scores
        composite = scores[0]
        for s in scores[1:]:
            composite = composite.add(s, fill_value=0)

        return composite
