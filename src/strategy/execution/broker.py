"""A-share aware simulated broker.

Enforces:
  - T+1 settlement (cannot sell shares bought today)
  - Price limits (no fill at limit-up/limit-down)
  - Lot size (buy must be 100-share multiple)
  - Commission and stamp duty calculation

Uses BaseBroker for shared execution logic.
"""

from __future__ import annotations

import logging
from datetime import date

from config.settings import get_settings
from src.core.broker_base import BaseBroker, BrokerPosition, BrokerTrade
from src.core.types import OrderStatus, OrderType, Side
from src.strategy.execution.order import Order, OrderResult

# Backward compatibility aliases
Position = BrokerPosition
Trade = BrokerTrade

logger = logging.getLogger(__name__)


class SimulatedBroker(BaseBroker):
    """A-share aware simulated broker with price limit enforcement.

    Extends BaseBroker with:
      - Order object interface (submit_order)
      - Price limit checks
      - OrderResult return type
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        commission_rate: float | None = None,
        stamp_duty_rate: float | None = None,
        min_commission: float | None = None,
        lot_size: int | None = None,
    ):
        super().__init__(
            initial_capital=initial_capital,
            commission_rate=commission_rate,
            stamp_duty_rate=stamp_duty_rate,
            min_commission=min_commission,
            lot_size=lot_size,
        )
        self.price_limits = get_settings().trading

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
            result = OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                reject_reason=reject,
            )
            logger.info(
                f"Order REJECTED: {order.symbol} {order.side.value} "
                f"x{order.quantity}: {reject}"
            )
            return result

        # Adjust quantity to lot size
        qty = self._adjust_lot_size(order)
        if qty <= 0:
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                reject_reason="Quantity rounded to 0",
            )

        order.quantity = qty

        # Price limit check
        if not self._check_price_limit(order, current_price, prev_close):
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                reject_reason="Price limit violation",
            )

        # Execute via base broker
        if order.is_buy:
            result = self._execute_buy(order, current_date, current_price)
        else:
            result = self._execute_sell(order, current_date, current_price)

        return result

    # ── Order Execution ───────────────────────────────────────

    def _execute_buy(
        self, order: Order, current_date: date, current_price: float
    ) -> OrderResult:
        """Execute a buy order through base broker."""
        amount = current_price * order.quantity
        commission = self.fees.calc_commission(amount, "buy")
        total_cost = amount + commission

        if total_cost > self.cash:
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                reject_reason=f"Insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}",
            )

        # Execute
        self.cash -= total_cost
        self._update_position_buy(order.symbol, order.quantity, current_price, current_date)

        self._trade_counter += 1
        self.trades.append(BrokerTrade(
            trade_id=f"T{self._trade_counter:06d}",
            symbol=order.symbol,
            side="buy",
            quantity=order.quantity,
            price=current_price,
            amount=amount,
            commission=commission,
            date=current_date,
        ))

        return OrderResult(
            order=order,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            filled_price=current_price,
            commission=commission,
            date=current_date,
        )

    def _execute_sell(
        self, order: Order, current_date: date, current_price: float
    ) -> OrderResult:
        """Execute a sell order through base broker."""
        pos = self.positions.get(order.symbol)
        if not pos or not pos.can_sell(order.quantity):
            available = pos.available if pos else 0
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                reject_reason=f"T+1 violation: available={available}, requested={order.quantity}",
            )

        if not pos or pos.quantity < order.quantity:
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                reject_reason=f"Insufficient shares: have {pos.quantity if pos else 0}, need {order.quantity}",
            )

        # Realized P&L
        realized_pnl = (current_price - pos.avg_cost) * order.quantity
        amount = current_price * order.quantity
        commission = self.fees.calc_commission(amount, "sell")

        # Execute
        self.cash += amount - commission
        pos.quantity -= order.quantity
        pos.available -= order.quantity
        if pos.quantity <= 0:
            del self.positions[order.symbol]

        self._trade_counter += 1
        self.trades.append(BrokerTrade(
            trade_id=f"T{self._trade_counter:06d}",
            symbol=order.symbol,
            side="sell",
            quantity=order.quantity,
            price=current_price,
            amount=amount,
            commission=commission,
            date=current_date,
            realized_pnl=realized_pnl,
        ))

        return OrderResult(
            order=order,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            filled_price=current_price,
            commission=commission,
            date=current_date,
        )

    # ── Validation ────────────────────────────────────────────

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
