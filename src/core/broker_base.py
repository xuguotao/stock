"""Base broker with shared execution logic.

Extracted common code from SimulatedBroker and PaperAccount:
  - Position management (quantity, available, avg_cost)
  - T+1 settlement
  - Lot size enforcement
  - Commission calculation
  - Portfolio value

Subclasses add their own features:
  - SimulatedBroker: price limits, Order objects
  - PaperAccount: persistence, daily P&L tracking
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class BrokerPosition:
    """A-share position with T+1 tracking."""

    symbol: str
    quantity: int = 0
    available: int = 0  # Available to sell (T+1)
    avg_cost: float = 0.0
    buy_date: date | None = None
    frozen: int = 0  # frozen quantity (for pending orders)

    @property
    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def can_sell(self, qty: int) -> bool:
        """Check if we can sell given quantity (T+1 + frozen)."""
        return self.available - self.frozen >= qty

    def update_available(self, current_date: date) -> None:
        """Make yesterday's purchases available (T+1)."""
        if self.buy_date and current_date > self.buy_date:
            self.available = self.quantity - self.frozen


@dataclass
class BrokerTrade:
    """A completed trade record."""

    trade_id: str
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    quantity: int
    amount: float
    commission: float
    date: date
    realized_pnl: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "quantity": self.quantity,
            "amount": round(self.amount, 2),
            "commission": round(self.commission, 2),
            "date": self.date.isoformat(),
            "realized_pnl": round(self.realized_pnl, 2),
        }


class FeeCalculator:
    """Centralized A-share fee calculation."""

    def __init__(
        self,
        commission_rate: float = 0.00025,
        stamp_duty_rate: float = 0.0005,
        min_commission: float = 5.0,
    ):
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.min_commission = min_commission

    @classmethod
    def from_settings(cls) -> "FeeCalculator":
        settings = get_settings()
        return cls(
            commission_rate=settings.commission.commission.rate,
            stamp_duty_rate=settings.commission.stamp_duty.rate,
            min_commission=settings.trading.min_commission,
        )

    def calc_commission(self, amount: float, side: str) -> float:
        """Calculate total fees for a trade.

        Includes: commission (with minimum), stamp duty (sell only),
                  transfer fee, and securities management fee.
        """
        commission = max(amount * self.commission_rate, self.min_commission)

        if side == "sell":
            commission += amount * self.stamp_duty_rate

        # Transfer fee + management fee
        commission += amount * 0.00001      # transfer
        commission += amount * 0.0000487    # management

        return commission


class BaseBroker:
    """Base broker with shared execution logic.

    Subclasses should override or extend for specific features.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        commission_rate: float | None = None,
        stamp_duty_rate: float | None = None,
        min_commission: float | None = None,
        lot_size: int | None = None,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, BrokerPosition] = {}
        self.trades: list[BrokerTrade] = []
        self._trade_counter = 0

        # Use FeeCalculator (centralized)
        if commission_rate and stamp_duty_rate and min_commission:
            self.fees = FeeCalculator(
                commission_rate=commission_rate,
                stamp_duty_rate=stamp_duty_rate,
                min_commission=min_commission,
            )
        else:
            self.fees = FeeCalculator.from_settings()

        self.lot_size = lot_size or get_settings().trading.lot_size

    # ── Position Management ───────────────────────────────────

    def buy(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
    ) -> BrokerTrade | None:
        """Execute a buy order."""
        # Round to lot size
        quantity = (quantity // self.lot_size) * self.lot_size
        if quantity <= 0:
            logger.warning(f"Buy quantity rounded to 0 for {symbol}")
            return None

        amount = price * quantity
        commission = self.fees.calc_commission(amount, "buy")
        total_cost = amount + commission

        if total_cost > self.cash:
            logger.warning(
                f"Insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}"
            )
            return None

        # Execute
        self.cash -= total_cost
        self._update_position_buy(symbol, quantity, price, trade_date)

        self._trade_counter += 1
        trade = BrokerTrade(
            trade_id=f"T{self._trade_counter:06d}",
            symbol=symbol,
            side="buy",
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
            date=trade_date,
        )
        self.trades.append(trade)
        logger.info(f"BUY  {trade.trade_id}: {symbol} x{quantity} @ {price:.2f}")
        return trade

    def sell(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
    ) -> BrokerTrade | None:
        """Execute a sell order."""
        pos = self.positions.get(symbol)
        if not pos:
            logger.warning(f"No position in {symbol}")
            return None

        quantity = min(quantity, pos.available - pos.frozen)
        if quantity <= 0:
            logger.warning(
                f"No available shares to sell for {symbol} "
                f"(T+1: available={pos.available}, frozen={pos.frozen})"
            )
            return None

        amount = price * quantity
        commission = self.fees.calc_commission(amount, "sell")

        # Realized P&L (FIFO: avg cost)
        realized_pnl = (price - pos.avg_cost) * quantity

        # Execute
        self.cash += amount - commission
        pos.quantity -= quantity
        pos.available -= quantity
        if pos.quantity <= 0:
            del self.positions[symbol]

        self._trade_counter += 1
        trade = BrokerTrade(
            trade_id=f"T{self._trade_counter:06d}",
            symbol=symbol,
            side="sell",
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
            date=trade_date,
            realized_pnl=realized_pnl,
        )
        self.trades.append(trade)
        logger.info(
            f"SELL {trade.trade_id}: {symbol} x{quantity} @ {price:.2f} "
            f"(P&L: {realized_pnl:+.2f})"
        )
        return trade

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
            "cash": round(self.cash, 2),
            "positions": len(self.positions),
            "total_trades": len(self.trades),
            "buys": sum(1 for t in self.trades if t.side == "buy"),
            "sells": sum(1 for t in self.trades if t.side == "sell"),
            "total_commission": round(sum(t.commission for t in self.trades), 2),
            "realized_pnl": round(
                sum(t.realized_pnl for t in self.trades if t.side == "sell"), 2
            ),
        }

    # ── Internal ──────────────────────────────────────────────

    def _update_position_buy(
        self, symbol: str, qty: int, price: float, buy_date: date
    ) -> None:
        if symbol not in self.positions:
            self.positions[symbol] = BrokerPosition(symbol=symbol)

        pos = self.positions[symbol]
        total_cost = pos.avg_cost * pos.quantity + price * qty
        pos.quantity += qty
        if pos.quantity > 0:
            pos.avg_cost = total_cost / pos.quantity
        pos.buy_date = buy_date
        # New buys are NOT available until T+1
        pos.available = pos.quantity - qty if pos.quantity > qty else 0
