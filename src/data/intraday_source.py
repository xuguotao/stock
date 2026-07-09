"""Intraday (5m, 30m) K-line data source.

Extends SinaSource with intraday bar fetching.
Sina API scale values: 5=5min, 15=15min, 30=30min, 60=60min
"""

from __future__ import annotations

import json
import logging
import ssl
from datetime import date, datetime

import pandas as pd

logger = logging.getLogger(__name__)

_SSL_CTX = ssl.create_default_context()

_FREQUENCY_TO_SCALE = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
}


def _sina_symbol(symbol: str) -> str:
    """Convert '600519.SH' to 'sh600519'."""
    code = symbol.split(".")[0].zfill(6)
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_intraday_bars(
    symbol: str,
    trade_date: date,
    frequency: str = "5m",
    datalen: int = 1000,
) -> pd.DataFrame:
    """Fetch intraday bars from Sina Finance API."""
    sina_sym = _sina_symbol(symbol)
    scale = _FREQUENCY_TO_SCALE.get(frequency, 5)

    path = (
        f"/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={sina_sym}&scale={scale}&ma=no&datalen={datalen}"
    )

    try:
        import http.client
        conn = http.client.HTTPSConnection("money.finance.sina.com.cn", timeout=15, context=_SSL_CTX)
        conn.request("GET", path, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.sina.com.cn",
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()

        if resp.status != 200:
            logger.warning(f"Sina intraday HTTP {resp.status} for {symbol}")
            return pd.DataFrame()

        data = json.loads(body)
        if not isinstance(data, list):
            return pd.DataFrame()

        rows = []
        target_date_str = trade_date.isoformat()

        for item in data:
            dt_str = item.get("day", "")
            if not dt_str.startswith(target_date_str):
                continue

            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            rows.append({
                "time": dt.time(),
                "datetime": dt,
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(float(item.get("volume", 0))),
                "amount": float(item.get("close", 0)) * int(float(item.get("volume", 0))) * 100,
                "symbol": symbol,
            })

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)

    except Exception as e:
        logger.warning(f"Sina intraday failed for {symbol}: {e}")
        return pd.DataFrame()


def fetch_intraday_bars_range(
    symbol: str,
    start: date,
    end: date,
    frequency: str = "5m",
    datalen: int = 10000,
) -> pd.DataFrame:
    """Fetch recent intraday bars from Sina and keep rows within a date window."""
    sina_sym = _sina_symbol(symbol)
    scale = _FREQUENCY_TO_SCALE.get(frequency, 5)

    path = (
        f"/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={sina_sym}&scale={scale}&ma=no&datalen={datalen}"
    )

    try:
        import http.client
        conn = http.client.HTTPSConnection("money.finance.sina.com.cn", timeout=15, context=_SSL_CTX)
        conn.request("GET", path, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.sina.com.cn",
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()

        if resp.status != 200:
            logger.warning(f"Sina intraday HTTP {resp.status} for {symbol}")
            return pd.DataFrame()

        data = json.loads(body)
        if not isinstance(data, list):
            return pd.DataFrame()

        rows = []
        for item in data:
            dt_str = item.get("day", "")
            if not dt_str:
                continue
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            if dt.date() < start or dt.date() > end:
                continue
            rows.append({
                "time": dt.time(),
                "datetime": dt,
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(float(item.get("volume", 0))),
                "amount": float(item.get("close", 0)) * int(float(item.get("volume", 0))) * 100,
                "symbol": symbol,
            })

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)

    except Exception as e:
        logger.warning(f"Sina intraday range failed for {symbol}: {e}")
        return pd.DataFrame()
