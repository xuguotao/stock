"""模拟交易账户.

管理资金、持仓(T+1)、交易日志、P&L计算。
与回测引擎的Broker不同，PaperAccount是持久化的，
可以跨多个交易日持续运行。

基于 BaseBroker 实现，共享核心交易逻辑。

Usage:
    account = PaperAccount(initial_capital=1_000_000)
    account.buy("000001.SZ", 11.00, 100, date(2025, 6, 3))
    account.sell("000001.SZ", 11.10, 100, date(2025, 6, 4))
    print(account.portfolio_value(prices))
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.core.broker_base import BaseBroker, BrokerPosition, BrokerTrade

logger = logging.getLogger(__name__)


class PaperAccount(BaseBroker):
    """模拟交易账户，基于 BaseBroker，增加持久化和每日盈亏追踪。"""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        data_dir: str | None = None,
    ):
        super().__init__(initial_capital=initial_capital)

        self.frozen_cash = 0.0  # 挂单冻结资金
        self.daily_pnl = 0.0
        self.daily_peak = initial_capital
        self.max_drawdown = 0.0

        # Persistence
        self.data_dir = Path(data_dir) if data_dir else Path("data/paper_trading")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── Buy / Sell (add timestamp) ────────────────────────────

    def buy(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
    ) -> BrokerTrade | None:
        """买入股票."""
        trade = super().buy(symbol, price, quantity, trade_date)
        if trade:
            trade.timestamp = datetime.now().isoformat()
        return trade

    def sell(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
    ) -> BrokerTrade | None:
        """卖出股票."""
        trade = super().sell(symbol, price, quantity, trade_date)
        if trade:
            trade.timestamp = datetime.now().isoformat()
        return trade

    # ── Daily P&L ─────────────────────────────────────────────

    def update_t_plus_one(self, trade_date: date) -> None:
        """更新T+1可卖状态 (backward compatible alias)."""
        self.update_available_positions(trade_date)

    def update_daily_pnl(self, prices: dict[str, float]) -> float:
        """计算当日盈亏."""
        current_value = self.portfolio_value(prices)
        # Approximate daily P&L from unrealized P&L
        unrealized = sum(
            (prices.get(pos.symbol, pos.avg_cost) - pos.avg_cost) * pos.quantity
            for pos in self.positions.values()
        )
        self.daily_pnl = current_value - self.initial_capital + \
            sum(t.commission for t in self.trades) - unrealized

        # Track peak and drawdown
        if current_value > self.daily_peak:
            self.daily_peak = current_value
        if self.daily_peak > 0:
            self.max_drawdown = (self.daily_peak - current_value) / self.daily_peak

        return self.daily_pnl

    # ── Summary ──────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """账户摘要."""
        base = super().summary()
        base.update({
            "frozen_cash": round(self.frozen_cash, 2),
            "max_drawdown": round(self.max_drawdown * 100, 2),
        })
        return base

    # ── Persistence ──────────────────────────────────────────

    def save(self, filename: str | None = None) -> str:
        """Save account state to JSON."""
        if filename is None:
            filename = f"paper_account_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = self.data_dir / filename

        data = {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "positions": {s: {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "available": p.available,
                "avg_cost": p.avg_cost,
                "buy_date": p.buy_date.isoformat() if p.buy_date else None,
                "frozen": p.frozen,
            } for s, p in self.positions.items()},
            "trade_log": [t.to_dict() for t in self.trades],
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
            self.positions[sym] = BrokerPosition(
                symbol=sym,
                quantity=pdata["quantity"],
                available=pdata["available"],
                avg_cost=pdata["avg_cost"],
                buy_date=datetime.fromisoformat(bd).date() if bd else None,
                frozen=pdata.get("frozen", 0),
            )

        self.trades = []
        for tdata in data.get("trade_log", []):
            self.trades.append(BrokerTrade(
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
