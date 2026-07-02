from __future__ import annotations

from datetime import date, datetime

from src.data.models import StockInfo
from src.data.clickhouse_stock_master_sync import sync_clickhouse_stock_master


class FakeClient:
    def __init__(self):
        self.commands = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if normalized.startswith("select symbol, name, industry, market, list_date"):
            return [
                ("000001", "旧平安", "银行", "SZ", date(1991, 4, 3)),
            ]
        return []


class FakeSource:
    def fetch_stock_list(self):
        return [
            StockInfo(symbol="000001.SZ", code="000001", name="平安银行"),
            StockInfo(symbol="920699.BJ", code="920699", name="海达尔"),
        ]


def test_sync_clickhouse_stock_master_preserves_existing_enrichment_fields() -> None:
    client = FakeClient()

    result = sync_clickhouse_stock_master(client=client, source=FakeSource(), checked_at="2026-07-02 10:30:00")

    assert result == {
        "source": "tencent",
        "fetched_rows": 2,
        "inserted_rows": 2,
        "preserved_enrichment_rows": 1,
    }
    insert_query, rows = client.commands[-1]
    assert "insert into stocks" in insert_query.lower()
    assert rows == [
        ("000001", "平安银行", "银行", "SZ", "1991-04-03", datetime(2026, 7, 2, 10, 30, 0)),
        ("920699", "海达尔", "", "BJ", "", datetime(2026, 7, 2, 10, 30, 0)),
    ]
