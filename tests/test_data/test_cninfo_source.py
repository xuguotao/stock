from __future__ import annotations

from src.data.cninfo_source import CninfoAnnouncementSource


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_cninfo_source_uses_dynamic_org_id_and_parses_announcements() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append(("GET", url, None))
        return FakeResponse({
            "stockList": [
                {"code": "601318", "orgId": "9900002221"},
                {"code": "000001", "orgId": "gssz0000001"},
            ]
        })

    def fake_post(url: str, *, data: dict[str, str], headers: dict[str, str], timeout: int):
        calls.append(("POST", url, data))
        return FakeResponse({
            "announcements": [
                {
                    "announcementTitle": "2025年年度报告",
                    "announcementTypeName": "年度报告",
                    "announcementTime": 1782662400000,
                    "announcementId": "1212345678",
                }
            ]
        })

    source = CninfoAnnouncementSource(http_get=fake_get, http_post=fake_post)

    result = source.fetch_announcements("601318.SH", page_size=10)

    assert calls[1][2]["stock"] == "601318,9900002221"
    assert result == [
            {
                "title": "2025年年度报告",
                "type": "年度报告",
                "date": "2026-06-29",
                "url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId=1212345678",
            }
    ]


def test_cninfo_source_falls_back_to_market_org_id_when_map_missing() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        return FakeResponse({"stockList": []})

    def fake_post(url: str, *, data: dict[str, str], headers: dict[str, str], timeout: int):
        calls.append(data)
        return FakeResponse({"announcements": []})

    source = CninfoAnnouncementSource(http_get=fake_get, http_post=fake_post)

    assert source.fetch_announcements("600519.SH") == []
    assert calls[0]["stock"] == "600519,gssh0600519"


def test_cninfo_source_returns_empty_on_request_failure() -> None:
    def failing_get(url: str, *, headers: dict[str, str], timeout: int):
        raise ConnectionError("blocked")

    def failing_post(url: str, *, data: dict[str, str], headers: dict[str, str], timeout: int):
        raise ConnectionError("blocked")

    source = CninfoAnnouncementSource(http_get=failing_get, http_post=failing_post)

    assert source.fetch_announcements("000001.SZ") == []
