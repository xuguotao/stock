"""Eastmoney signal data source with centralized throttling."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable

import requests

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
logger = logging.getLogger(__name__)


class EastmoneyClient:
    """Small HTTP client that serializes Eastmoney requests."""

    def __init__(
        self,
        min_interval: float = 1.0,
        jitter: tuple[float, float] = (0.1, 0.5),
        http_get: Callable[..., Any] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.min_interval = min_interval
        self.jitter = jitter
        self._http_get = http_get
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA})
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_call: float | None = None

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 15,
    ) -> Any:
        self._wait()
        if self._http_get is not None:
            return self._http_get(url, params=params, headers=headers, timeout=timeout)
        request_headers = {"User-Agent": _UA}
        if headers:
            request_headers.update(headers)
        response = self._session.get(url, params=params, headers=request_headers, timeout=timeout)
        response.raise_for_status()
        return response

    def _wait(self) -> None:
        now = self._monotonic()
        if self._last_call is not None:
            wait = self.min_interval - (now - self._last_call)
            if wait > 0:
                low, high = self.jitter
                self._sleep(wait + random.uniform(low, high))
        self._last_call = self._monotonic()


class EastmoneySignalSource:
    """Eastmoney-only signal endpoints.

    This source intentionally does not implement the generic DataSource protocol.
    It is for signal/enrichment endpoints that should not be called in bulk
    without explicit rate control.
    """

    name = "eastmoney_signal"

    def __init__(self, client: EastmoneyClient | None = None):
        self.client = client or EastmoneyClient()

    def fetch_concept_blocks(self, symbol: str) -> dict[str, Any]:
        """Fetch all Eastmoney board/concept memberships for one stock."""
        code = _code(symbol)
        params = {
            "fltt": "2",
            "invt": "2",
            "secid": _secid(code),
            "spt": "3",
            "pi": "0",
            "pz": "200",
            "po": "1",
            "fields": "f12,f14,f3,f128",
        }
        try:
            response = self.client.get(
                "https://push2.eastmoney.com/api/qt/slist/get",
                params=params,
                headers={"Referer": "https://quote.eastmoney.com/"},
                timeout=15,
            )
            data = response.json()
        except Exception as exc:
            logger.warning("Eastmoney concept blocks failed for %s: %s", symbol, exc)
            return {"total": 0, "boards": [], "concept_tags": []}
        items = _diff_items((data.get("data") or {}).get("diff"))
        boards = [
            {
                "name": str(item.get("f14", "")),
                "code": str(item.get("f12", "")),
                "change_pct": _to_float(item.get("f3")),
                "lead_stock": str(item.get("f128", "")),
            }
            for item in items
        ]
        return {
            "total": len(boards),
            "boards": boards,
            "concept_tags": [row["name"] for row in boards if row["name"]],
        }

    def fetch_minute_fund_flow(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch intraday minute-level fund flow for one stock."""
        code = _code(symbol)
        params = {
            "secid": _secid(code),
            "klt": 1,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        try:
            response = self.client.get(
                "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                params=params,
                headers={
                    "Referer": "https://quote.eastmoney.com/",
                    "Origin": "https://quote.eastmoney.com",
                },
                timeout=10,
            )
            data = response.json()
        except Exception as exc:
            logger.warning("Eastmoney minute fund flow failed for %s: %s", symbol, exc)
            return []
        rows = []
        for line in (data.get("data") or {}).get("klines", []) or []:
            parts = str(line).split(",")
            if len(parts) < 6:
                continue
            rows.append({
                "time": parts[0],
                "main_net": _to_float(parts[1]),
                "small_net": _to_float(parts[2]),
                "mid_net": _to_float(parts[3]),
                "large_net": _to_float(parts[4]),
                "super_net": _to_float(parts[5]),
            })
        return rows


def _code(symbol: str) -> str:
    return symbol.split(".")[0].zfill(6)


def _secid(code: str) -> str:
    market = "1" if code.startswith(("6", "9")) else "0"
    return f"{market}.{code}"


def _diff_items(diff: Any) -> list[dict[str, Any]]:
    if isinstance(diff, dict):
        return [item for item in diff.values() if isinstance(item, dict)]
    if isinstance(diff, list):
        return [item for item in diff if isinstance(item, dict)]
    return []


def _to_float(value: Any) -> float:
    if value in (None, "", "-"):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
