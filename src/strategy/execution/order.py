"""Order types and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.core.types import OrderStatus, OrderType, Side


@dataclass
class Order:
    """A trading order."""
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    date: date | None = None

    @property
    def is_buy(self) -> bool:
        return self.side == Side.BUY

    @property
    def is_sell(self) -> bool:
        return self.side == Side.SELL


@dataclass
class OrderResult:
    """Result of an order execution."""
    order: Order
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0
    commission: float = 0.0
    reject_reason: str = ""
    date: date | None = None

    @property
    def filled_amount(self) -> float:
        """Filled quantity * price."""
        return self.filled_quantity * self.filled_price

    @property
    def is_rejected(self) -> bool:
        return self.status == OrderStatus.REJECTED

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED
