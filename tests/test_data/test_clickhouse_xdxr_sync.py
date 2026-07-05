"""Tests for ClickHouse xdxr sync."""
from __future__ import annotations

from src.data.clickhouse_xdxr_sync import sync_clickhouse_xdxr_info


class FakeClient:
    def __init__(self):
        self.commands = []

    def execute(self, query, params=None):
        self.commands.append((query, params))


def fake_fetch_xdxr(symbol):
    if symbol == "000001.SZ":
        return [
            {
                "year": 2023,
                "month": 6,
                "day": 15,
                "category": 1,
                "bonus_amount": 0.5,
                "ratening_amount": 0.0,
                "increased_amount": 0.0,
                "ignore": False,
            }
        ]
    return []


def test_sync_xdxr_info_inserts_data():
    """sync_clickhouse_xdxr_info should insert xdxr data into ClickHouse."""
    fake_client = FakeClient()
    result = sync_clickhouse_xdxr_info(
        client=fake_client,
        fetch_fn=fake_fetch_xdxr,
        symbols=["000001.SZ"],
    )
    assert result["inserted"] == 1
    assert len(fake_client.commands) > 0
