"""Pydantic-based settings loader.

Loads configuration from:
  1. YAML files (trading_rules.yaml, commission.yaml)
  2. Environment variables / .env file
  3. Code defaults

Usage:
    from config.settings import get_settings
    settings = get_settings()
    print(settings.trading.lot_size)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: str) -> dict[str, Any]:
    """Load a YAML file, returning empty dict on failure."""
    p = PROJECT_ROOT / path
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


# ── Trading Rules ──────────────────────────────────────────────

class TradingHours(BaseModel):
    open: str = "09:30"
    close: str = "11:30"


class AfternoonHours(BaseModel):
    open: str = "13:00"
    close: str = "15:00"


class TradingHoursConfig(BaseModel):
    morning: TradingHours = Field(default_factory=TradingHours)
    afternoon: AfternoonHours = Field(default_factory=AfternoonHours)


class BoardRule(BaseModel):
    name: str
    code_prefix: list[str]
    price_limit_pct: float


class TradingRules(BaseModel):
    lot_size: int = 100
    t_plus_one: bool = True
    min_commission: float = 5.0
    hours: TradingHoursConfig = Field(default_factory=TradingHoursConfig)
    boards: dict[str, BoardRule] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls) -> "TradingRules":
        data = _load_yaml("config/trading_rules.yaml")
        if not data:
            return cls()
        # Parse boards
        boards = {}
        for key, val in data.get("boards", {}).items():
            boards[key] = BoardRule(**val)
        # Parse hours
        hours_data = data.get("trading_hours", {})
        hours = TradingHoursConfig(
            morning=TradingHours(**hours_data.get("morning", {})),
            afternoon=AfternoonHours(**hours_data.get("afternoon", {})),
        )
        return cls(
            lot_size=data.get("lot_size", 100),
            t_plus_one=data.get("t_plus_one", True),
            min_commission=data.get("min_commission", 5.0),
            hours=hours,
            boards=boards,
        )

    def get_price_limit(self, symbol: str) -> float:
        """Get price limit percentage for a stock symbol."""
        prefix = symbol.split(".")[0][:3]
        for board in self.boards.values():
            for p in board.code_prefix:
                if prefix.startswith(p[:3]):
                    return board.price_limit_pct
        return 0.10  # default: main board


# ── Commission ─────────────────────────────────────────────────

class FeeRule(BaseModel):
    rate: float
    side: str = "both"
    min_amount: float = 0.0
    description: str = ""


class CommissionConfig(BaseModel):
    stamp_duty: FeeRule = Field(default_factory=lambda: FeeRule(rate=0.0005, side="sell", description="印花税"))
    commission: FeeRule = Field(default_factory=lambda: FeeRule(rate=0.00025, min_amount=5.0, description="券商佣金"))
    transfer_fee: FeeRule = Field(default_factory=lambda: FeeRule(rate=0.00001, description="过户费"))
    securities_mgmt_fee: FeeRule = Field(default_factory=lambda: FeeRule(rate=0.0000487, description="证管费"))

    @classmethod
    def from_yaml(cls) -> "CommissionConfig":
        data = _load_yaml("config/commission.yaml")
        if not data:
            return cls()
        fees = data.get("fees", {})
        kwargs: dict[str, Any] = {}
        for key in ["stamp_duty", "commission", "transfer_fee", "securities_mgmt_fee"]:
            if key in fees:
                fee_data = fees[key].copy()
                if "min" in fee_data:
                    fee_data["min_amount"] = fee_data.pop("min")
                kwargs[key] = FeeRule(**fee_data)
        return cls(**kwargs)

    def total_buy_cost(self, amount: float) -> float:
        """Total fees for a buy order (amount in yuan)."""
        total = 0.0
        for fee in [self.commission, self.transfer_fee, self.securities_mgmt_fee]:
            if fee.side in ("both", "buy"):
                cost = amount * fee.rate
                if fee.min_amount > 0:
                    cost = max(cost, fee.min_amount)
                total += cost
        return total

    def total_sell_cost(self, amount: float) -> float:
        """Total fees for a sell order (amount in yuan)."""
        total = 0.0
        for fee in [self.stamp_duty, self.commission, self.transfer_fee, self.securities_mgmt_fee]:
            if fee.side in ("both", "sell"):
                cost = amount * fee.rate
                if fee.min_amount > 0:
                    cost = max(cost, fee.min_amount)
                total += cost
        return total


# ── Data Source Config ─────────────────────────────────────────

class DataSourceConfig(BaseModel):
    primary: str = "akshare"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    cache_ttl_days: dict[str, int] = Field(default_factory=lambda: {
        "bars": 1,
        "financials": 90,
        "stock_list": 7,
    })

    def __init__(self, **data: Any):
        super().__init__(**data)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


# ── App Settings ───────────────────────────────────────────────

class AppSettings(BaseModel):
    trading: TradingRules = Field(default_factory=TradingRules.from_yaml)
    commission: CommissionConfig = Field(default_factory=CommissionConfig.from_yaml)
    data: DataSourceConfig = Field(default_factory=DataSourceConfig)
    tushare_token: str = ""
    log_level: str = "INFO"

    def __init__(self, **data: Any):
        # Load .env
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv(PROJECT_ROOT / ".env.example")

        data.setdefault("tushare_token", os.getenv("TUSHARE_TOKEN", ""))
        super().__init__(**data)


# ── Singleton ──────────────────────────────────────────────────

_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """Get singleton app settings."""
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings


def reset_settings() -> None:
    """Reset settings (useful for testing)."""
    global _settings
    _settings = None
