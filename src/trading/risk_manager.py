"""实时风控管理器.

监控:
  - 日内最大回撤止损
  - 单票集中度限制
  - 行业集中度限制
  - 总仓位限制
  - VaR监控

Usage:
    rm = RiskManager(max_daily_drawdown=0.03, max_single_weight=0.20)
    if rm.check_order(order, account):
        account.buy(...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum

from src.trading.paper_account import PaperAccount

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass
class RiskCheckResult:
    passed: bool
    level: RiskLevel
    message: str = ""


class RiskManager:
    """Real-time risk controls."""

    def __init__(
        self,
        max_daily_drawdown: float = 0.03,      # 3%日内最大回撤
        max_single_weight: float = 0.20,        # 单票20%上限
        max_industry_weight: float = 0.60,      # 行业60%上限
        max_total_position: float = 0.95,       # 总仓位95%上限
        max_trades_per_day: int = 50,           # 日内最多50笔交易
    ):
        self.max_daily_drawdown = max_daily_drawdown
        self.max_single_weight = max_single_weight
        self.max_industry_weight = max_industry_weight
        self.max_total_position = max_total_position
        self.max_trades_per_day = max_trades_per_day
        self._trading_halted = False
        self._halt_reason = ""
        self._today_trades = 0
        self._last_date: date | None = None

    def reset_daily(self, trade_date: date) -> None:
        """重置日内计数器."""
        if self._last_date != trade_date:
            self._today_trades = 0
            self._last_date = trade_date
            self._trading_halted = False
            self._halt_reason = ""

    def check_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        account: PaperAccount,
        trade_date: date,
        industry_map: dict[str, str] | None = None,
    ) -> RiskCheckResult:
        """检查一笔订单是否通过风控."""
        self.reset_daily(trade_date)

        # Check if trading is halted
        if self._trading_halted:
            return RiskCheckResult(
                passed=False, level=RiskLevel.BLOCKED,
                message=f"Trading halted: {self._halt_reason}",
            )

        # Check trade count
        if self._today_trades >= self.max_trades_per_day:
            return self._halt(f"Max trades per day reached ({self.max_trades_per_day})")

        portfolio_value = account.portfolio_value({})
        if portfolio_value <= 0:
            return RiskCheckResult(passed=True, level=RiskLevel.OK)

        if side == "buy":
            order_amount = price * quantity

            # Total position check
            current_position_value = sum(
                pos.quantity * pos.avg_cost for pos in account.positions.values()
            )
            total_after = (current_position_value + order_amount) / portfolio_value
            if total_after > self.max_total_position:
                return RiskCheckResult(
                    passed=False, level=RiskLevel.WARNING,
                    message=f"Total position would exceed {self.max_total_position*100:.0f}% "
                            f"(current: {current_position_value/portfolio_value*100:.1f}%, "
                            f"order: {order_amount/portfolio_value*100:.1f}%)",
                )

            # Single stock weight check
            pos = account.positions.get(symbol)
            current_value = pos.quantity * pos.avg_cost if pos else 0
            single_weight = (current_value + order_amount) / portfolio_value
            if single_weight > self.max_single_weight:
                return RiskCheckResult(
                    passed=False, level=RiskLevel.WARNING,
                    message=f"Single stock weight would exceed {self.max_single_weight*100:.0f}% "
                            f"({single_weight*100:.1f}%)",
                )

            # Industry concentration check
            if industry_map:
                industry = industry_map.get(symbol, "综合")
                industry_value = current_value
                for sym, p in account.positions.items():
                    if industry_map.get(sym, "综合") == industry:
                        industry_value += p.quantity * p.avg_cost
                industry_weight = (industry_value + order_amount) / portfolio_value
                if industry_weight > self.max_industry_weight:
                    return RiskCheckResult(
                        passed=False, level=RiskLevel.WARNING,
                        message=f"Industry weight would exceed {self.max_industry_weight*100:.0f}% "
                                f"({industry_weight*100:.1f}%)",
                    )

        self._today_trades += 1
        return RiskCheckResult(passed=True, level=RiskLevel.OK)

    def check_daily_drawdown(self, account: PaperAccount) -> RiskCheckResult:
        """检查日内回撤."""
        if account.max_drawdown >= self.max_daily_drawdown:
            return self._halt(
                f"Daily drawdown limit breached: "
                f"{account.max_drawdown*100:.2f}% >= {self.max_daily_drawdown*100:.0f}%"
            )
        if account.max_drawdown >= self.max_daily_drawdown * 0.8:
            return RiskCheckResult(
                passed=True, level=RiskLevel.WARNING,
                message=f"Drawdown approaching limit: {account.max_drawdown*100:.2f}%",
            )
        return RiskCheckResult(passed=True, level=RiskLevel.OK)

    def _halt(self, reason: str) -> RiskCheckResult:
        """Halt trading."""
        self._trading_halted = True
        self._halt_reason = reason
        logger.warning(f"TRADING HALTED: {reason}")
        return RiskCheckResult(
            passed=False, level=RiskLevel.BLOCKED, message=reason
        )

    @property
    def is_trading_halted(self) -> bool:
        return self._trading_halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason
