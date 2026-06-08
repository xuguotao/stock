"""模拟交易账户.

管理资金、持仓(T+1)、交易日志、P&L计算。
与回测引擎的Broker不同，PaperAccount是持久化的，
可以跨多个交易日持续运行。

Usage:
    account = PaperAccount(initial_capital=1_000_000)
    account.buy("000001.SZ", 11.00, 100, date(2025, 6, 3))
    account.sell("000001.SZ", 11.10, 100, date(2025, 6, 4))
    print(account.portfolio_value(prices))
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings
from src.core.types import Side

logger = logging.getLogger(__name__)


@dataclass
class PaperTrade:
    """一条交易记录."""
    trade_id: str
    symbol: str
    side: str          # "buy" or "sell"
    price: float
    quantity: int
    amount: float
    commission: float
    date: date
    timestamp: str = ""
    realized_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
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


@dataclass
class PaperPosition:
    """持仓信息."""
    symbol: str
    quantity: int = 0
    available: int = 0      # T+1可卖数量
    avg_cost: float = 0.0
    buy_date: date | None = None
    frozen: int = 0         # 挂单冻结数量

    @property
    def unrealized_pnl(self, current_price: float) -> float:
        """未实现盈亏."""
        return (current_price - self.avg_cost) * self.quantity

    @property
    def unrealized_pnl_pct(self, current_price: float) -> float:
        """未实现盈亏百分比."""
        if self.avg_cost <= 0:
            return 0
        return (current_price / self.avg_cost - 1) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "available": self.available,
            "avg_cost": round(self.avg_cost, 4),
            "buy_date": self.buy_date.isoformat() if self.buy_date else None,
        }


class PaperAccount:
    """模拟交易账户."""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        data_dir: str | None = None,
    ):
        settings = get_settings()
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.frozen_cash = 0.0  # 挂单冻结资金
        self.positions: dict[str, PaperPosition] = {}
        self.trade_log: list[PaperTrade] = []
        self._trade_counter = 0
        self.daily_pnl = 0.0
        self.daily_peak = initial_capital
        self.max_drawdown = 0.0

        # Fee settings
        self.commission_rate = settings.commission.commission.rate
        self.stamp_duty_rate = settings.commission.stamp_duty.rate
        self.min_commission = settings.trading.min_commission
        self.lot_size = settings.trading.lot_size

        # Persistence
        self.data_dir = Path(data_dir) if data_dir else Path("data/paper_trading")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── Buy ───────────────────────────────────────────────────

    def buy(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
    ) -> PaperTrade | None:
        """买入股票."""
        # Round to lot size
        quantity = (quantity // self.lot_size) * self.lot_size
        if quantity <= 0:
            logger.warning(f"Buy quantity rounded to 0 for {symbol}")
            return None

        amount = price * quantity
        commission = self._calc_commission(amount, "buy")
        total_cost = amount + commission

        if total_cost > self.cash:
            logger.warning(f"Insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}")
            return None

        # Execute
        self.cash -= total_cost
        self._update_position_buy(symbol, quantity, price, trade_date)

        self._trade_counter += 1
        trade = PaperTrade(
            trade_id=f"T{self._trade_counter:06d}",
            symbol=symbol,
            side="buy",
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
            date=trade_date,
            timestamp=datetime.now().isoformat(),
        )
        self.trade_log.append(trade)
        logger.info(f"BUY  {trade.trade_id}: {symbol} x{quantity} @ {price:.2f}")
        return trade

    # ── Sell ──────────────────────────────────────────────────

    def sell(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
    ) -> PaperTrade | None:
        """卖出股票."""
        pos = self.positions.get(symbol)
        if not pos:
            logger.warning(f"No position in {symbol}")
            return None

        quantity = min(quantity, pos.available)
        if quantity <= 0:
            logger.warning(f"No available shares to sell for {symbol} (T+1: available={pos.available})")
            return None

        amount = price * quantity
        commission = self._calc_commission(amount, "sell")

        # Calculate realized P&L (FIFO)
        realized_pnl = (price - pos.avg_cost) * quantity

        # Execute
        self.cash += amount - commission
        pos.quantity -= quantity
        pos.available -= quantity
        if pos.quantity <= 0:
            del self.positions[symbol]

        self._trade_counter += 1
        trade = PaperTrade(
            trade_id=f"T{self._trade_counter:06d}",
            symbol=symbol,
            side="sell",
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
            date=trade_date,
            timestamp=datetime.now().isoformat(),
            realized_pnl=realized_pnl,
        )
        self.trade_log.append(trade)
        logger.info(f"SELL {trade.trade_id}: {symbol} x{quantity} @ {price:.2f} (P&L: {realized_pnl:+.2f})")
        return trade

    # ── Position Management ───────────────────────────────────

    def update_t_plus_one(self, trade_date: date) -> None:
        """更新T+1可卖状态."""
        for pos in self.positions.values():
            if pos.buy_date and trade_date > pos.buy_date:
                pos.available = pos.quantity - pos.frozen

    def _update_position_buy(
        self, symbol: str, quantity: int, price: float, buy_date: date
    ) -> None:
        if symbol not in self.positions:
            self.positions[symbol] = PaperPosition(symbol=symbol)

        pos = self.positions[symbol]
        total_cost = pos.avg_cost * pos.quantity + price * quantity
        pos.quantity += quantity
        pos.avg_cost = total_cost / pos.quantity if pos.quantity > 0 else price
        pos.buy_date = buy_date
        # New buys not available until T+1
        pos.available = pos.quantity - quantity if pos.quantity > quantity else 0

    # ── Portfolio Value ──────────────────────────────────────

    def portfolio_value(self, prices: dict[str, float]) -> float:
        """计算组合总价值."""
        total = self.cash
        for symbol, pos in self.positions.items():
            price = prices.get(symbol, pos.avg_cost)
            total += pos.quantity * price
        return total

    def update_daily_pnl(self, prices: dict[str, float]) -> float:
        """计算当日盈亏."""
        current_value = self.portfolio_value(prices)
        # Approximate daily P&L from unrealized P&L
        unrealized = sum(
            pos.unrealized_pnl(prices.get(pos.symbol, pos.avg_cost))
            for pos in self.positions.values()
        )
        self.daily_pnl = current_value - self.initial_capital + \
            sum(t.commission for t in self.trade_log) - unrealized

        # Track peak and drawdown
        if current_value > self.daily_peak:
            self.daily_peak = current_value
        if self.daily_peak > 0:
            self.max_drawdown = (self.daily_peak - current_value) / self.daily_peak

        return self.daily_pnl

    # ── Commission ───────────────────────────────────────────

    def _calc_commission(self, amount: float, side: str) -> float:
        """计算交易费用."""
        commission = max(amount * self.commission_rate, self.min_commission)
        if side == "sell":
            commission += amount * self.stamp_duty_rate
        commission += amount * 0.00001     # transfer
        commission += amount * 0.0000487   # management
        return commission

    # ── Summary ──────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """账户摘要."""
        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "frozen_cash": round(self.frozen_cash, 2),
            "positions": len(self.positions),
            "total_trades": len(self.trade_log),
            "buys": sum(1 for t in self.trade_log if t.side == "buy"),
            "sells": sum(1 for t in self.trade_log if t.side == "sell"),
            "total_commission": round(sum(t.commission for t in self.trade_log), 2),
            "realized_pnl": round(sum(t.realized_pnl for t in self.trade_log if t.side == "sell"), 2),
            "max_drawdown": round(self.max_drawdown * 100, 2),
        }

    # ── Persistence ──────────────────────────────────────────

    def save(self, filename: str | None = None) -> str:
        """Save account state to JSON."""
        if filename is None:
            filename = f"paper_account_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = self.data_dir / filename

        data = {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "trade_log": [t.to_dict() for t in self.trade_log],
            "trade_counter": self._trade_counter,
            "daily_peak": self.daily_peak,
            "max_drawdown": self.max_drawdown,
            "saved_at": datetime.now().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Account saved to {path}")
        return str(path)

    def load(self, filename: str) -> None:
        """Load account state from JSON."""
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Account file not found: {path}")

        with open(path) as f:
            data = json.load(f)

        self.initial_capital = data["initial_capital"]
        self.cash = data["cash"]
        self._trade_counter = data.get("trade_counter", 0)
        self.daily_peak = data.get("daily_peak", self.initial_capital)
        self.max_drawdown = data.get("max_drawdown", 0)

        self.positions = {}
        for sym, pdata in data.get("positions", {}).items():
            bd = pdata.get("buy_date")
            self.positions[sym] = PaperPosition(
                symbol=sym,
                quantity=pdata["quantity"],
                available=pdata["available"],
                avg_cost=pdata["avg_cost"],
                buy_date=datetime.fromisoformat(bd).date() if bd else None,
            )

        self.trade_log = []
        for tdata in data.get("trade_log", []):
            self.trade_log.append(PaperTrade(
                trade_id=tdata["trade_id"],
                symbol=tdata["symbol"],
                side=tdata["side"],
                price=tdata["price"],
                quantity=tdata["quantity"],
                amount=tdata["amount"],
                commission=tdata["commission"],
                date=datetime.fromisoformat(tdata["date"]).date(),
                realized_pnl=tdata.get("realized_pnl", 0),
            ))

        logger.info(f"Account loaded from {path}")
