"""Data models for A-share market data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class DailyBar:
    """A-share daily bar.

    Attributes are designed to match the output of AKShare's stock_zh_a_hist endpoint.
    """
    symbol: str                # e.g., "000001.SZ"
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int                # shares traded
    amount: float              # turnover in yuan
    adjusted_close: float      # forward-adjusted close
    suspended: bool = False    # trading suspension flag

    @property
    def mid(self) -> float:
        """Mid price."""
        return (self.high + self.low) / 2


@dataclass(frozen=True)
class StockInfo:
    """Basic stock information."""
    symbol: str                # e.g., "000001.SZ"
    code: str                  # e.g., "000001"
    name: str                  # e.g., "平安银行"
    industry: str = ""         # Shenwan industry classification
    list_date: date | None = None
    is_st: bool = False


@dataclass(frozen=True)
class FinancialStatement:
    """Quarterly financial statement data."""
    symbol: str
    report_date: date          # e.g., date(2025, 3, 31) for Q1
    publish_date: date
    revenue: float             # 营业收入
    net_profit: float          # 净利润
    total_assets: float        # 总资产
    total_equity: float        # 股东权益
    eps: float                 # 每股收益
    roe: float                 # 净资产收益率
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    ps_ratio: float | None = None


@dataclass
class TradeRecord:
    """A single trade record."""
    symbol: str
    side: str                  # "buy" or "sell"
    price: float
    quantity: int
    amount: float
    commission: float
    date: date
    order_id: str = ""

    @property
    def net_amount(self) -> float:
        """Net amount after commission."""
        if self.side == "buy":
            return -(self.amount + self.commission)
        return self.amount - self.commission
