"""Tencent Finance quote source.

Tencent's quote endpoint is useful for low-frequency real-time quotes and
valuation fields such as PE, PB, market cap, turnover, and price limits.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

import pandas as pd
import requests

from src.core.constants import format_symbol
from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo


HttpGet = Callable[[str], str]

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def parse_tencent_quote_text(text: str) -> pd.DataFrame:
    """Parse Tencent quote response text into the project's quote schema."""
    rows = []
    for line in text.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=", 1)[0].split("_")[-1]
        values = line.split('"', 2)[1].split("~")
        if len(values) < 50:
            continue

        code = key[2:] if len(key) >= 8 else str(values[2]).zfill(6)
        price = _float_at(values, 3)
        prev_close = _float_at(values, 4)
        amount = _float_at(values, 37) * 10_000
        timestamp = _parse_timestamp(_str_at(values, 30))
        rows.append({
            "symbol": format_symbol(code),
            "name": _str_at(values, 1),
            "price": price,
            "open": _float_at(values, 5),
            "prev_close": prev_close,
            "high": _float_at(values, 33),
            "low": _float_at(values, 34),
            "change_amt": _float_at(values, 31),
            "change_pct": _float_at(values, 32),
            "volume": int(_float_at(values, 36)),
            "amount": amount,
            "turnover_pct": _float_at(values, 38),
            "pe_ttm": _float_at(values, 39),
            "amplitude_pct": _float_at(values, 43),
            "mcap": _float_at(values, 44) * 100_000_000,
            "float_mcap": _float_at(values, 45) * 100_000_000,
            "pb": _float_at(values, 46),
            "limit_up": _float_at(values, 47),
            "limit_down": _float_at(values, 48),
            "vol_ratio": _float_at(values, 49),
            "pe_static": _float_at(values, 52),
            "timestamp": timestamp,
        })

    return pd.DataFrame(rows)


class TencentQuoteSource(DataSourceBase):
    """Tencent Finance adapter for real-time quotes and valuation fields."""

    name = "tencent"

    def __init__(
        self,
        rate_limit: float = 0.2,
        http_get: Callable[..., str] | None = None,
    ):
        super().__init__(rate_limit=rate_limit)
        self._http_get = http_get or _requests_get_text

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_stock_list(self) -> list[StockInfo]:
        return []

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        self._wait_for_rate_limit()
        query = ",".join(_tencent_symbol(symbol) for symbol in symbols)
        text = self._http_get(
            f"https://qt.gtimg.cn/q={query}",
            headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"},
            timeout=10,
        )
        return parse_tencent_quote_text(text)

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        return []


def _requests_get_text(url: str, *, headers: dict[str, str], timeout: int) -> str:
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.content.decode("gbk", errors="ignore")


def _tencent_symbol(symbol: str) -> str:
    code = symbol.split(".")[0].zfill(6)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("8", "4")):
        return f"bj{code}"
    return f"sz{code}"


def _float_at(values: list[str], index: int) -> float:
    if index >= len(values) or values[index] == "":
        return 0.0
    try:
        return float(values[index])
    except ValueError:
        return 0.0


def _str_at(values: list[str], index: int) -> str:
    if index >= len(values):
        return ""
    return values[index]


def _parse_timestamp(value: str) -> str:
    if len(value) == 14 and value.isdigit():
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"
    return value
