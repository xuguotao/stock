"""Cninfo announcement source."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_ORG_MAP_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
_ANNOUNCEMENT_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"


class CninfoAnnouncementSource:
    """Cninfo announcements with dynamic stock orgId lookup."""

    name = "cninfo"

    def __init__(
        self,
        http_get: Callable[..., Any] | None = None,
        http_post: Callable[..., Any] | None = None,
    ):
        self._http_get = http_get or _requests_get
        self._http_post = http_post or _requests_post
        self._org_id_map: dict[str, str] | None = None

    def fetch_announcements(self, symbol: str, page_size: int = 30) -> list[dict[str, str]]:
        """Fetch recent announcement metadata for one stock."""
        code = _code(symbol)
        try:
            org_id = self._org_id(code)
            response = self._http_post(
                _ANNOUNCEMENT_URL,
                data={
                    "stock": f"{code},{org_id}",
                    "tabName": "fulltext",
                    "pageSize": str(page_size),
                    "pageNum": "1",
                    "column": "",
                    "category": "",
                    "plate": "",
                    "seDate": "",
                    "searchkey": "",
                    "secid": "",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                },
                headers={
                    "User-Agent": _UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://www.cninfo.com.cn/new/disclosure",
                    "Origin": "https://www.cninfo.com.cn",
                },
                timeout=15,
            )
            payload = response.json()
        except Exception as exc:
            logger.warning("Cninfo announcements failed for %s: %s", symbol, exc)
            return []

        rows = []
        for item in payload.get("announcements", []) or []:
            announcement_id = str(item.get("announcementId", ""))
            rows.append({
                "title": str(item.get("announcementTitle", "")),
                "type": str(item.get("announcementTypeName", "")),
                "date": _announcement_date(item.get("announcementTime")),
                "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={announcement_id}",
            })
        return rows

    def _org_id(self, code: str) -> str:
        if self._org_id_map is None:
            self._org_id_map = self._load_org_id_map()
        return self._org_id_map.get(code) or _fallback_org_id(code)

    def _load_org_id_map(self) -> dict[str, str]:
        try:
            response = self._http_get(
                _ORG_MAP_URL,
                headers={"User-Agent": _UA, "Referer": "https://www.cninfo.com.cn/"},
                timeout=15,
            )
            payload = response.json()
        except Exception as exc:
            logger.warning("Cninfo orgId map failed: %s", exc)
            return {}
        return {
            str(item.get("code", "")).zfill(6): str(item.get("orgId", ""))
            for item in payload.get("stockList", []) or []
            if item.get("code") and item.get("orgId")
        }


def _requests_get(url: str, *, headers: dict[str, str], timeout: int) -> requests.Response:
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


def _requests_post(
    url: str,
    *,
    data: dict[str, str],
    headers: dict[str, str],
    timeout: int,
) -> requests.Response:
    response = requests.post(url, data=data, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


def _code(symbol: str) -> str:
    return symbol.split(".")[0].zfill(6)


def _fallback_org_id(code: str) -> str:
    if code.startswith("6"):
        return f"gssh0{code}"
    if code.startswith(("8", "4")):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def _announcement_date(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
    return str(value)[:10] if value else ""
