"""Tencent Finance quote source.

Tencent's quote endpoint is useful for low-frequency real-time quotes and
valuation fields such as PE, PB, market cap, turnover, and price limits.
"""

from __future__ import annotations

import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Callable

import pandas as pd
import requests

from src.core.constants import format_symbol, is_st
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

        symbol = _format_tencent_key_symbol(key, str(values[2]))
        price = _float_at(values, 3)
        prev_close = _float_at(values, 4)
        amount = _float_at(values, 37) * 10_000
        timestamp = _parse_timestamp(_str_at(values, 30))
        rows.append({
            "symbol": symbol,
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
            "float_mcap": _float_at(values, 44) * 100_000_000,
            "mcap": _float_at(values, 45) * 100_000_000,
            "pb": _float_at(values, 46),
            "limit_up": _float_at(values, 47),
            "limit_down": _float_at(values, 48),
            "vol_ratio": _float_at(values, 49),
            "pe_static": _float_at(values, 52),
            "timestamp": timestamp,
        })

    return pd.DataFrame(rows)


def parse_tencent_kline_json(payload: dict[str, Any], symbol: str, frequency: str = "5m") -> pd.DataFrame:
    """Parse Tencent appstock minute K-line JSON into intraday bars."""
    if payload.get("code") != 0:
        return pd.DataFrame()
    if frequency != "5m":
        return pd.DataFrame()

    query_symbol = _tencent_symbol(symbol)
    node = (payload.get("data") or {}).get(query_symbol) or {}
    raw_bars = node.get("m5") or []
    rows = []
    formatted_symbol = format_symbol(symbol)
    for raw in raw_bars:
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        timestamp = pd.to_datetime(str(raw[0]), format="%Y%m%d%H%M", errors="coerce")
        if pd.isna(timestamp):
            continue
        rows.append({
            "datetime": timestamp,
            "time": timestamp.time(),
            "symbol": formatted_symbol,
            "open": _float_at(raw, 1),
            "high": _float_at(raw, 3),
            "low": _float_at(raw, 4),
            "close": _float_at(raw, 2),
            "volume": _float_at(raw, 5),
            "amount": _float_at(raw, 2) * _float_at(raw, 5) * 100,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)


class TencentQuoteSource(DataSourceBase):
    """Tencent Finance adapter for real-time quotes and valuation fields."""

    name = "tencent"

    def __init__(
        self,
        rate_limit: float = 0.2,
        http_get: Callable[..., str] | None = None,
        intraday_workers: int = 80,
        realtime_chunk_size: int = 800,
        realtime_endpoint: str = "sqt_utf8",
        stock_list_page_size: int = 100,
    ):
        super().__init__(rate_limit=rate_limit)
        self._http_get = http_get or _requests_get_text
        self._intraday_workers = intraday_workers
        self._realtime_chunk_size = max(1, realtime_chunk_size)
        self._realtime_endpoint = realtime_endpoint
        self._stock_list_page_size = max(1, min(int(stock_list_page_size), 200))

    @property
    def realtime_endpoint(self) -> str:
        return self._realtime_endpoint

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_stock_list(self) -> list[StockInfo]:
        stocks: list[StockInfo] = []
        seen: set[str] = set()
        total: int | None = None
        offset = 0
        while total is None or offset < total:
            self._wait_for_rate_limit()
            params = {
                "_appver": "11.17.0",
                "board_code": "aStock",
                "sort_type": "priceRatio",
                "direct": "down",
                "offset": str(offset),
                "count": str(self._stock_list_page_size),
            }
            text = self._http_get(
                "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList?"
                + urllib.parse.urlencode(params),
                headers={"User-Agent": _UA, "Referer": "https://stockapp.finance.qq.com/mstats/"},
                timeout=10,
            )
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                break
            if payload.get("code") != 0:
                break
            data = payload.get("data") or {}
            raw_rows = data.get("rank_list") or []
            total = int(data.get("total") or 0)
            if not raw_rows:
                break
            for raw in raw_rows:
                item = _stock_info_from_rank_item(raw)
                if item is None or item.symbol in seen:
                    continue
                seen.add(item.symbol)
                stocks.append(item)
            offset += len(raw_rows)
        return stocks

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        frames = []
        for batch in _chunks(symbols, self._realtime_chunk_size):
            self._wait_for_rate_limit()
            query = ",".join(_tencent_symbol(symbol) for symbol in batch)
            text = self._fetch_realtime_quote_text(query)
            frame = parse_tencent_quote_text(text)
            if frame is not None and not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _fetch_realtime_quote_text(self, query: str) -> str:
        urls = _quote_endpoint_urls(query, self._realtime_endpoint)
        last_error: Exception | None = None
        for url in urls:
            try:
                return self._http_get(
                    url,
                    headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"},
                    timeout=10,
                )
            except Exception as exc:  # noqa: BLE001 - fallback endpoint is part of the data-source contract.
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return ""

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        if frequency != "5m":
            return pd.DataFrame()
        self._wait_for_rate_limit()
        query_symbol = _tencent_symbol(symbol)
        text = self._http_get(
            f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={query_symbol},m5,,320",
            headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/", "Accept": "application/json,*/*"},
            timeout=10,
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return pd.DataFrame()
        bars = parse_tencent_kline_json(payload, symbol, frequency)
        if bars.empty:
            return bars
        mask = bars["datetime"].dt.date == trade_date
        return bars.loc[mask].reset_index(drop=True)

    def fetch_intraday_bars_batch(
        self,
        symbols: list[str],
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        if not symbols or frequency != "5m":
            return pd.DataFrame()
        frames = []
        workers = max(1, min(self._intraday_workers, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(self.fetch_intraday_bars, symbol, trade_date, frequency)
                for symbol in symbols
            ]
            for future in as_completed(futures):
                try:
                    frame = future.result()
                except Exception:
                    continue
                if frame is not None and not frame.empty:
                    frames.append(frame)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values(["symbol", "datetime"]).reset_index(drop=True)

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        return []


def _requests_get_text(url: str, *, headers: dict[str, str], timeout: int) -> str:
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    encoding = "utf-8" if "sqt.gtimg.cn/utf8" in url or "proxy.finance.qq.com" in url else "gbk"
    return response.content.decode(encoding, errors="ignore")


def _quote_endpoint_urls(query: str, endpoint: str) -> list[str]:
    if endpoint == "qt":
        return [f"https://qt.gtimg.cn/q={query}", f"https://sqt.gtimg.cn/utf8/q={query}"]
    return [f"https://sqt.gtimg.cn/utf8/q={query}", f"https://qt.gtimg.cn/q={query}"]


def _stock_info_from_rank_item(raw: Any) -> StockInfo | None:
    if not isinstance(raw, dict):
        return None
    raw_code = str(raw.get("code") or "").lower()
    if len(raw_code) < 8:
        return None
    market = raw_code[:2]
    if market not in {"sh", "sz", "bj"}:
        return None
    stock_type = str(raw.get("stock_type") or "")
    if stock_type in {"ZS", "KJ"}:
        return None
    if market in {"sh", "sz"} and stock_type and not stock_type.startswith("GP-A") and stock_type != "GP":
        return None
    code = raw_code[2:].zfill(6)
    suffix = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[market]
    name = str(raw.get("name") or "")
    if not name:
        return None
    return StockInfo(
        symbol=f"{code}.{suffix}",
        code=code,
        name=name,
        is_st=is_st(name),
    )


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _tencent_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if "." in normalized:
        code, suffix = normalized.split(".", 1)
        code = code.zfill(6)
        if suffix == "SH":
            return f"sh{code}"
        if suffix == "SZ":
            return f"sz{code}"
        if suffix == "BJ":
            return f"bj{code}"
    code = normalized.split(".")[0].zfill(6)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("8", "4")):
        return f"bj{code}"
    return f"sz{code}"


def _format_tencent_key_symbol(key: str, fallback_code: str) -> str:
    lowered = key.lower()
    if lowered.startswith("sh") and len(key) >= 8:
        return f"{key[2:].zfill(6)}.SH"
    if lowered.startswith("sz") and len(key) >= 8:
        return f"{key[2:].zfill(6)}.SZ"
    if lowered.startswith("bj") and len(key) >= 8:
        return f"{key[2:].zfill(6)}.BJ"
    return format_symbol(fallback_code)


def _float_at(values: list[str], index: int) -> float:
    if index >= len(values) or values[index] == "":
        return 0.0
    try:
        return float(values[index])
    except ValueError:
        return 0.0


def _safe_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _is_regular_a_share_minute(value) -> bool:
    return (
        (value.hour == 9 and value.minute >= 30)
        or (value.hour == 10)
        or (value.hour == 11 and value.minute <= 30)
        or (value.hour == 13)
        or (value.hour == 14)
        or (value.hour == 15 and value.minute == 0)
    )


def _str_at(values: list[str], index: int) -> str:
    if index >= len(values):
        return ""
    return values[index]


def _parse_timestamp(value: str) -> str:
    if len(value) == 14 and value.isdigit():
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"
    return value
