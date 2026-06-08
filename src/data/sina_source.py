"""Sina Finance data source adapter.

Uses Sina Finance HTTP API directly (bypasses East Money).
Works reliably behind proxy/Clash environments.

API: https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/
     CN_MarketData.getKLineData?symbol=sh600519&scale=240&ma=no&datalen=100

Scale values: 5=5min, 15=15min, 30=30min, 60=60min, 240=daily
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
from datetime import date, datetime

import pandas as pd

from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo
from src.core.constants import format_symbol

logger = logging.getLogger(__name__)

_SINA_HOST = "money.finance.sina.com.cn"
_SSL_CTX = ssl.create_default_context()


def _sina_symbol(symbol: str) -> str:
    """Convert '600519.SH' to 'sh600519'."""
    code = symbol.split(".")[0].zfill(6)
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_sina_kline(code: str, datalen: int = 1000) -> list[dict]:
    """Fetch K-line data from Sina Finance API.

    Returns list of dicts: day, open, high, low, close, volume.
    """
    sina_sym = _sina_symbol(code)
    path = (
        f"/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={sina_sym}&scale=240&ma=no&datalen={datalen}"
    )

    try:
        conn = http.client.HTTPSConnection(_SINA_HOST, timeout=15, context=_SSL_CTX)
        conn.request("GET", path, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.sina.com.cn",
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()

        if resp.status != 200:
            logger.warning(f"Sina K-line HTTP {resp.status} for {code}")
            return []

        data = json.loads(body)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning(f"Sina K-line failed for {code}: {e}")
        return []


def fetch_sina_realtime(symbols: list[str]) -> pd.DataFrame:
    """Fetch real-time quotes from Sina hq API."""
    import requests

    session = requests.Session()
    session.trust_env = False

    sina_syms = ",".join(_sina_symbol(s) for s in symbols)
    url = f"https://hq.sinajs.cn/list={sina_syms}"

    try:
        resp = session.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        lines = resp.text.strip().split("\n")
    except Exception as e:
        logger.warning(f"Sina realtime failed: {e}")
        return pd.DataFrame()

    rows = []
    for line in lines:
        if "=" not in line:
            continue
        parts = line.split("=", 1)
        code_part = parts[0]
        values = parts[1].strip("\";\n").split(",")

        if len(values) < 32:
            continue

        # Extract 6-digit code from var name like "hq_str_sh600519"
        code = code_part[-6:]

        price = float(values[3]) if values[3] else 0
        # During non-market hours, current price may be 0; use prev_close as fallback
        prev_close = float(values[2]) if values[2] else 0
        if price == 0 and prev_close > 0:
            price = prev_close

        # Calculate change_pct
        change_pct = 0
        if prev_close > 0 and price > 0:
            change_pct = (price - prev_close) / prev_close * 100

        rows.append({
            "symbol": format_symbol(code),
            "name": values[0],
            "open": float(values[1]) if values[1] else 0,
            "prev_close": prev_close,
            "price": price,
            "high": float(values[4]) if values[4] else price,
            "low": float(values[5]) if values[5] else price,
            "volume": int(float(values[8])) if values[8] else 0,
            "amount": float(values[9]) if values[9] else 0,
            "change_pct": round(change_pct, 2),
            "timestamp": values[30] if len(values) > 30 else "",
        })

    return pd.DataFrame(rows)


class SinaSource(DataSourceBase):
    """Sina Finance data source.

    Note: Sina doesn't support date range filtering server-side.
    We fetch the most recent N bars and filter client-side.
    """

    name = "sina"

    def __init__(self, rate_limit: float = 0.2):
        super().__init__(rate_limit=rate_limit)

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        """Fetch daily bars from Sina Finance.

        Fetches recent bars and filters by date range.
        """
        self._wait_for_rate_limit()
        code = symbol.split(".")[0]

        # Fetch enough bars to cover the date range
        datalen = 1000
        raw_data = _fetch_sina_kline(code, datalen)

        if not raw_data:
            return pd.DataFrame()

        # Parse into DataFrame
        rows = []
        for item in raw_data:
            d = datetime.strptime(item["day"], "%Y-%m-%d").date()
            if d < start or d > end:
                continue
            rows.append({
                "date": d,
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": int(float(item["volume"])),
                "amount": 0.0,
                "adjusted_close": float(item["close"]),
                "symbol": symbol,
            })

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    def fetch_stock_list(self) -> list[StockInfo]:
        """Fetch all A-share stock list.

        Tries Sina first, falls back to AKShare.
        """
        self._wait_for_rate_limit()

        # Try Sina stock list
        try:
            conn = http.client.HTTPSConnection(_SINA_HOST, timeout=15, context=_SSL_CTX)
            conn.request("GET", "/quotes_service/api/json_v2.php/CN_MarketData.getStockList?page=1&num=6000", headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn",
            })
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            conn.close()

            if resp.status == 200:
                data = json.loads(body)
                if isinstance(data, list) and data:
                    stocks = []
                    for item in data:
                        code = str(item.get("code", "") or item.get("symbol", ""))
                        code = code[-6:] if len(code) >= 6 else code.zfill(6)
                        if code and code.isdigit():
                            stocks.append(StockInfo(
                                symbol=format_symbol(code),
                                code=code,
                                name=str(item.get("name", "")),
                            ))
                    if stocks:
                        return stocks
        except Exception:
            pass

        # Fallback: try AKShare
        logger.info("Falling back to AKShare for stock list")
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            stocks = []
            for _, row in df.iterrows():
                code = str(row["code"]).zfill(6)
                stocks.append(StockInfo(
                    symbol=format_symbol(code),
                    code=code,
                    name=str(row["name"]),
                ))
            return stocks
        except Exception as e:
            logger.warning(f"AKShare stock list also failed: {e}")
            return []

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch real-time quotes."""
        return fetch_sina_realtime(symbols)

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        """Sina doesn't provide financial statements directly."""
        return []
