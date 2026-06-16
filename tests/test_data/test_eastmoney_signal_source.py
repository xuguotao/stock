from __future__ import annotations

from src.data.eastmoney_source import EastmoneyClient, EastmoneySignalSource


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_eastmoney_client_serializes_requests_with_rate_limit() -> None:
    calls: list[tuple[str, dict | None, dict | None, int]] = []
    sleeps: list[float] = []
    now = [100.0]

    def fake_get(url: str, params=None, headers=None, timeout=15):
        calls.append((url, params, headers, timeout))
        return FakeResponse({"data": {"diff": {}}})

    def fake_time() -> float:
        return now[0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = EastmoneyClient(
        min_interval=1.0,
        jitter=(0.0, 0.0),
        http_get=fake_get,
        monotonic=fake_time,
        sleep=fake_sleep,
    )

    client.get("https://example.test/a")
    client.get("https://example.test/b")

    assert len(calls) == 2
    assert sleeps == [1.0]


def test_eastmoney_signal_source_parses_concept_blocks_dict_diff() -> None:
    def fake_get(url: str, params=None, headers=None, timeout=15):
        assert params["secid"] == "1.600519"
        return FakeResponse({
            "data": {
                "diff": {
                    "0": {"f14": "食品饮料", "f12": "BK0438", "f3": -0.06, "f128": "金字火腿"},
                    "1": {"f14": "白酒", "f12": "BK0896", "f3": 0.18, "f128": "贵州茅台"},
                }
            }
        })

    source = EastmoneySignalSource(
        client=EastmoneyClient(min_interval=0.0, http_get=fake_get)
    )

    result = source.fetch_concept_blocks("600519.SH")

    assert result["total"] == 2
    assert result["concept_tags"] == ["食品饮料", "白酒"]
    assert result["boards"][0] == {
        "name": "食品饮料",
        "code": "BK0438",
        "change_pct": -0.06,
        "lead_stock": "金字火腿",
    }


def test_eastmoney_signal_source_parses_minute_fund_flow() -> None:
    def fake_get(url: str, params=None, headers=None, timeout=15):
        assert params["secid"] == "0.000001"
        assert params["klt"] == 1
        return FakeResponse({
            "data": {
                "klines": [
                    "2026-06-15 14:30,100,10,20,30,40,0",
                    "2026-06-15 14:31,-50,5,6,7,8,0",
                ]
            }
        })

    source = EastmoneySignalSource(
        client=EastmoneyClient(min_interval=0.0, http_get=fake_get)
    )

    result = source.fetch_minute_fund_flow("000001.SZ")

    assert result == [
        {
            "time": "2026-06-15 14:30",
            "main_net": 100.0,
            "small_net": 10.0,
            "mid_net": 20.0,
            "large_net": 30.0,
            "super_net": 40.0,
        },
        {
            "time": "2026-06-15 14:31",
            "main_net": -50.0,
            "small_net": 5.0,
            "mid_net": 6.0,
            "large_net": 7.0,
            "super_net": 8.0,
        },
    ]


def test_eastmoney_signal_source_returns_empty_on_request_failure() -> None:
    def failing_get(url: str, params=None, headers=None, timeout=15):
        raise ConnectionError("remote closed")

    source = EastmoneySignalSource(
        client=EastmoneyClient(min_interval=0.0, http_get=failing_get)
    )

    assert source.fetch_concept_blocks("600519.SH") == {
        "total": 0,
        "boards": [],
        "concept_tags": [],
    }
    assert source.fetch_minute_fund_flow("600519.SH") == []
