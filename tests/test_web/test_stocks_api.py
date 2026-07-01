from __future__ import annotations

from typing import Any

from src.web.backend.data_status import fetch_stock_list


class _FakeClickHouseClient:
    """记录最后一次查询并返回预设行。"""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.last_query: str | None = None

    def execute(self, query: str, params: dict[str, Any] | None = None) -> list[tuple]:
        self.last_query = query
        return self._rows


def test_fetch_stock_list_returns_full_fields_and_is_st_derivation() -> None:
    rows = [
        ("000001.SZ", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-30"),
        ("000004.SZ", "*ST国华", "软件", "SZ", "1990-12-01", "2026-06-17"),
    ]
    client = _FakeClickHouseClient(rows)

    result = fetch_stock_list(client)

    assert result["total"] == 2
    assert result["items"] == [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "industry": "银行",
            "market": "SZ",
            "list_date": "1991-04-03",
            "last_daily_date": "2026-06-30",
            "is_st": False,
        },
        {
            "symbol": "000004.SZ",
            "name": "*ST国华",
            "industry": "软件",
            "market": "SZ",
            "list_date": "1990-12-01",
            "last_daily_date": "2026-06-17",
            "is_st": True,
        },
    ]


def test_fetch_stock_list_keeps_stocks_without_daily_via_left_join() -> None:
    # 000005 无任何日线,last_daily_date 应为 None 但仍出现在结果里
    rows = [
        ("000001.SZ", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-30"),
        ("000005.SZ", "best科技", "软件", "SZ", "1991-01-01", None),
    ]
    client = _FakeClickHouseClient(rows)

    result = fetch_stock_list(client)

    assert result["total"] == 2
    no_daily = next(item for item in result["items"] if item["symbol"] == "000005.SZ")
    assert no_daily["last_daily_date"] is None
