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
        ("000001.SZ", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-30", 1, 1, "[]", "[]", 0, 0),
        ("000004.SZ", "*ST国华", "软件", "SZ", "1990-12-01", "2026-06-17", 0, 0, '["st_stock"]', "[]", 0, 0),
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
            "research_eligible": True,
            "data_ready": True,
            "excluded_reasons": [],
            "data_gap_reasons": [],
            "daily_missing": False,
            "minute5_missing": False,
        },
        {
            "symbol": "000004.SZ",
            "name": "*ST国华",
            "industry": "软件",
            "market": "SZ",
            "list_date": "1990-12-01",
            "last_daily_date": "2026-06-17",
            "is_st": True,
            "research_eligible": False,
            "data_ready": False,
            "excluded_reasons": ["st_stock"],
            "data_gap_reasons": [],
            "daily_missing": False,
            "minute5_missing": False,
        },
    ]


def test_fetch_stock_list_keeps_stocks_without_daily_via_left_join() -> None:
    # 000005 无任何日线,last_daily_date 应为 None 但仍出现在结果里
    rows = [
        ("000001.SZ", "平安银行", "银行", "SZ", "1991-04-03", "2026-06-30", 1, 1, "[]", "[]", 0, 0),
        ("000005.SZ", "best科技", "软件", "SZ", "1991-01-01", None, None, None, None, None, None, None),
    ]
    client = _FakeClickHouseClient(rows)

    result = fetch_stock_list(client)

    assert result["total"] == 2
    no_daily = next(item for item in result["items"] if item["symbol"] == "000005.SZ")
    assert no_daily["last_daily_date"] is None
    assert no_daily["research_eligible"] is None
    assert no_daily["data_ready"] is None
    assert no_daily["excluded_reasons"] == []
    assert no_daily["data_gap_reasons"] == []
    assert "countif(d.symbol != '')" in (client.last_query or "").lower()


from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_stocks_api_returns_items(tmp_path) -> None:
    def _runner() -> dict:
        return {
            "items": [
                {
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "industry": "银行",
                    "market": "SZ",
                    "list_date": "1991-04-03",
                    "last_daily_date": "2026-06-30",
                    "is_st": False,
                }
            ],
            "total": 1,
        }

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        stock_list_runner=_runner,
    )
    client = TestClient(app)

    response = client.get("/api/stocks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["symbol"] == "000001.SZ"


def test_stocks_api_returns_500_when_clickhouse_unavailable(tmp_path) -> None:
    def _runner() -> dict:
        raise RuntimeError("ClickHouse 未配置")

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        stock_list_runner=_runner,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/stocks")

    assert response.status_code == 500
