"""Real-time executor for tail-session paper trading."""

from __future__ import annotations

from datetime import date

from src.strategy.scanner import TailSessionSignal
from src.trading.paper_account import PaperAccount
from src.trading.risk_manager import RiskManager


class RealTimeExecutor:
    """Execute confirmed tail-session signals against a PaperAccount."""

    def __init__(
        self,
        account: PaperAccount,
        risk_manager: RiskManager,
        max_single_weight: float = 0.20,
        take_profit_pct: float = 0.03,
        stop_loss_pct: float = -0.02,
    ):
        self.account = account
        self.risk_manager = risk_manager
        self.max_single_weight = max_single_weight
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct

    def execute_buy_signals(
        self,
        signals: list[TailSessionSignal],
        prices: dict[str, float],
        trade_date: date,
    ):
        """Buy confirmed signals, respecting lot size and risk checks."""
        trades = []
        portfolio_value = self.account.portfolio_value(prices)
        budget_per_signal = portfolio_value * self.max_single_weight

        for signal in sorted(signals, key=lambda s: s.strength, reverse=True):
            if signal.symbol in self.account.positions:
                continue

            price = float(prices.get(signal.symbol, signal.last_price))
            if price <= 0:
                continue

            quantity = int(budget_per_signal / price // 100 * 100)
            if quantity <= 0:
                continue

            risk = self.risk_manager.check_order(
                signal.symbol,
                "buy",
                quantity,
                price,
                self.account,
                trade_date,
            )
            if not risk.passed:
                continue

            trade = self.account.buy(signal.symbol, price, quantity, trade_date)
            if trade is not None:
                trades.append(trade)

        return trades

    def sell_positions(
        self,
        prices: dict[str, float],
        trade_date: date,
        force: bool = False,
    ):
        """Sell positions on take-profit, stop-loss, or forced morning exit."""
        trades = []
        self.account.update_t_plus_one(trade_date)

        for symbol, position in list(self.account.positions.items()):
            price = float(prices.get(symbol, 0))
            if price <= 0 or position.available <= 0:
                continue

            pnl_pct = (price - position.avg_cost) / position.avg_cost if position.avg_cost > 0 else 0.0
            should_sell = force or pnl_pct >= self.take_profit_pct or pnl_pct <= self.stop_loss_pct
            if not should_sell:
                continue

            risk = self.risk_manager.check_order(
                symbol,
                "sell",
                position.available,
                price,
                self.account,
                trade_date,
            )
            if not risk.passed:
                continue

            trade = self.account.sell(symbol, price, position.available, trade_date)
            if trade is not None:
                trades.append(trade)

        return trades
