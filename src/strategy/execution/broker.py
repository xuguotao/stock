"""A-share aware simulated broker.

Enforces:
  - T+1 settlement (cannot sell shares bought today)
  - Price limits (no fill at limit-up/limit-down)
  - Lot size (buy must be 100-share multiple)
  - Commission and stamp duty calculation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from config.settings import get_settings
from src.core.types import OrderStatus, OrderType, Side
from src.strategy.execution.order import Order, OrderResult

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """A-share position with T+1 tracking."""
    symbol: str
    quantity: int = 0
    available: int = 0  # Available to sell (T+1)
    avg_cost: float = 0.0
    buy_date: date | None = None  # Date of last purchase

    @property
    def market_value(self) -> float:
        """Current price needed for market value (set externally)."""
        return self.quantity * self.avg_cost

    def can_sell(self, qty: int) -> bool:
        """Check if we can sell given T+1 rules."""
        return self.available >= qty

    def update_available(self, current_date: date) -> None:
        """Make yesterday's purchases available (T+1)."""
        if self.buy_date and current_date > self.buy_date:
            self.available = self.quantity


@dataclass
class Trade:
    """A completed trade record."""
    date: date
    symbol: str
    side: Side
    quantity: int
    price: float
    amount: float
    commission: float
    pnl: float = 0.0  # Realized P&L (for sells)


class SimulatedBroker:
    """A-share aware simulated broker.

    Manages cash, positions, and order execution.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        commission_rate: float | None = None,
        stamp_duty_rate: float | None = None,
        min_commission: float | None = None,
        lot_size: int | None = None,
    ):
        settings = get_settings()

        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.frozen_cash = 0.0
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self._trade_counter = 0

        # Fee settings
        self.commission_rate = commission_rate or settings.commission.commission.rate
        self.stamp_duty_rate = stamp_duty_rate or settings.commission.stamp_duty.rate
        self.min_commission = min_commission or settings.trading.min_commission
        self.lot_size = lot_size or settings.trading.lot_size
        self.price_limits = settings.trading

    def submit_order(
        self,
        order: Order,
        current_date: date,
        current_price: float,
        prev_close: float = 0.0,
    ) -> OrderResult:
        """Submit and execute an order.

        Args:
            order: The order to execute.
            current_date: Current trading date.
            current_price: Execution price.
            prev_close: Previous day's close (for price limit check).

        Returns:
            OrderResult with execution details.
        """
        order.date = current_date

        # Validation
        reject = self._validate_order(order, current_price, prev_close)
        if reject:
            result = OrderResult(order=order, status=OrderStatus.REJECTED, reject_reason=reject)
            logger.info(f"Order REJECTED: {order.symbol} {order.side.value} x{order.quantity}: {reject}")
            return result

        # Adjust quantity to lot size
        qty = self._adjust_lot_size(order)
        if qty <= 0:
            return OrderResult(order=order, status=OrderStatus.REJECTED,
                               reject_reason="Quantity rounded to 0")

        order.quantity = qty

        # Price limit check
        if not self._check_price_limit(order, current_price, prev_close):
            return OrderResult(order=order, status=OrderStatus.REJECTED,
                               reject_reason="Price limit violation")

        # Calculate cost
        amount = current_price * qty
        commission = self._calculate_commission(amount, order.side)

        if order.is_buy:
            total_cost = amount + commission
            if total_cost > self.cash:
                return OrderResult(order=order, status=OrderStatus.REJECTED,
                                   reject_reason=f"Insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}")

            # Execute buy
            self.cash -= total_cost
            self._update_position_buy(order.symbol, qty, current_price, current_date)

            self._trade_counter += 1
            self.trades.append(Trade(
                date=current_date,
                symbol=order.symbol,
                side=Side.BUY,
                quantity=qty,
                price=current_price,
                amount=amount,
                commission=commission,
            ))

            return OrderResult(
                order=order,
                status=OrderStatus.FILLED,
                filled_quantity=qty,
                filled_price=current_price,
                commission=commission,
                date=current_date,
            )

        else:  # sell
            # Check T+1
            pos = self.positions.get(order.symbol)
            if not pos or not pos.can_sell(qty):
                available = pos.available if pos else 0
                return OrderResult(order=order, status=OrderStatus.REJECTED,
                                   reject_reason=f"T+1 violation: available={available}, requested={qty}")

            # Check if we have the shares
            if not pos or pos.quantity < qty:
                return OrderResult(order=order, status=OrderStatus.REJECTED,
                                   reject_reason=f"Insufficient shares: have {pos.quantity if pos else 0}, need {qty}")

            # Calculate realized P&L
            realized_pnl = (current_price - pos.avg_cost) * qty
            commission = self._calculate_commission(amount, order.side)

            # Execute sell
            self.cash += amount - commission
            self._update_position_sell(order.symbol, qty, current_price)

            self._trade_counter += 1
            self.trades.append(Trade(
                date=current_date,
                symbol=order.symbol,
                side=Side.SELL,
                quantity=qty,
                price=current_price,
                amount=amount,
                commission=commission,
                pnl=realized_pnl,
            ))

            return OrderResult(
                order=order,
                status=OrderStatus.FILLED,
                filled_quantity=qty,
                filled_price=current_price,
                commission=commission,
                date=current_date,
            )

    def _validate_order(
        self,
        order: Order,
        current_price: float,
        prev_close: float,
    ) -> str | None:
        """Validate order. Returns rejection reason or None."""
        if current_price <= 0:
            return f"Invalid price: {current_price}"
        if order.quantity <= 0:
            return f"Invalid quantity: {order.quantity}"
        # Lot size: rounded in _adjust_lot_size, not rejected here
        return None

    def _adjust_lot_size(self, order: Order) -> int:
        """Round quantity down to lot size multiple."""
        if order.is_buy:
            return (order.quantity // self.lot_size) * self.lot_size
        return order.quantity

    def _check_price_limit(
        self,
        order: Order,
        current_price: float,
        prev_close: float,
    ) -> bool:
        """Check if price violates daily limit."""
        if prev_close <= 0:
            return True
        limit_pct = self.price_limits.get_price_limit(order.symbol)
        upper = prev_close * (1 + limit_pct)
        lower = prev_close * (1 - limit_pct)
        return lower <= current_price <= upper

    def _calculate_commission(self, amount: float, side: Side) -> float:
        """Calculate total commission and fees."""
        # Commission (with minimum)
        commission = max(amount * self.commission_rate, self.min_commission)

        # Stamp duty (sell only)
        if side == Side.SELL:
            commission += amount * self.stamp_duty_rate

        # Transfer fee + management fee (small, always charged)
        commission += amount * 0.00001  # transfer
        commission += amount * 0.0000487  # management

        return commission

    def _update_position_buy(
        self, symbol: str, qty: int, price: float, buy_date: date
    ) -> None:
        """Update position after a buy."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]
        # Update average cost
        total_cost = pos.avg_cost * pos.quantity + price * qty
        pos.quantity += qty
        if pos.quantity > 0:
            pos.avg_cost = total_cost / pos.quantity
        pos.buy_date = buy_date
        # New buys are NOT available until T+1
        pos.available = pos.quantity - qty if pos.quantity > qty else 0

    def _update_position_sell(self, symbol: str, qty: int, price: float) -> None:
        """Update position after a sell."""
        pos = self.positions[symbol]
        pos.quantity -= qty
        pos.available -= qty
        if pos.quantity <= 0:
            del self.positions[symbol]

    def update_available_positions(self, current_date: date) -> None:
        """Make previous day's purchases available (T+1)."""
        for pos in self.positions.values():
            pos.update_available(current_date)

    def portfolio_value(self, prices: dict[str, float]) -> float:
        """Calculate total portfolio value."""
        total = self.cash
        for symbol, pos in self.positions.items():
            price = prices.get(symbol, pos.avg_cost)
            total += pos.quantity * price
        return total

    def summary(self) -> dict:
        """Get broker summary."""
        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "positions": len(self.positions),
            "total_trades": len(self.trades),
            "buys": sum(1 for t in self.trades if t.side == Side.BUY),
            "sells": sum(1 for t in self.trades if t.side == Side.SELL),
            "total_commission": sum(t.commission for t in self.trades),
        }
