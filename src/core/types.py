"""Type definitions for the quant platform."""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TimeFrame(str, Enum):
    """Supported bar frequencies."""
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    MINUTE_60 = "60m"
    DAILY = "1d"
    WEEKLY = "1w"
    MONTHLY = "1M"


class DataSourceType(str, Enum):
    """Available data sources."""
    AKSHARE = "akshare"
    TUSHARE = "tushare"
    EASTMONEY = "eastmoney"


class Sector(str, Enum):
    """Shenwan industry sectors (Level 1)."""
    AGRICULTURE = "农林牧渔"
    BASE_METALS = "有色金属"
    BUILDING_MATERIALS = "建筑材料"
    CONSTRUCTION = "建筑装饰"
    DEFENSE = "国防军工"
    ELECTRICAL_EQUIPMENT = "电气设备"
    ELECTRONICS = "电子"
    FOOD_BEVERAGE = "食品饮料"
    HEALTHCARE = "医药生物"
    HOUSEHOLD_APPLIANCES = "家用电器"
    MEDIA = "传媒"
    NONFERROUS_METALS = "有色金属"
    REAL_ESTATE = "房地产"
    COMMERCE = "商业贸易"
    COMPUTERS = "计算机"
    COMMUNICATIONS = "通信"
    BANKS = "银行"
    NONBANK_FINANCE = "非银金融"
    AUTOS = "汽车"
    TEXTILES = "纺织服装"
    LIGHT_MANUFACTURING = "轻工制造"
    CHEMICALS = "化工"
    STEEL = "钢铁"
    MACHINERY = "机械设备"
    UTILITIES = "公用事业"
    TRANSPORTATION = "交通运输"
    COMPREHENSIVE = "综合"
