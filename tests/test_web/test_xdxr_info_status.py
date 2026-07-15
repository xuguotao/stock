"""Tests for xdxr_info in data status."""
from __future__ import annotations


def test_inspect_includes_xdxr_info():
    """inspect_clickhouse_database should include xdxr_info checks."""
    from src.web.backend.data_status import inspect_clickhouse_database

    class FakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "xdxr_info" in normalized:
                if "count" in normalized:
                    return [(100,)]
                return []
            return []

    result = inspect_clickhouse_database(client=FakeClient())
    datasets_health = result.get("datasets_health", [])
    xdxr_rows = [row for row in datasets_health if row.get("key") == "xdxr_info"]
    assert len(xdxr_rows) == 1, f"xdxr_info not found in datasets_health"
    xdxr_row = xdxr_rows[0]
    assert xdxr_row["name"] == "除权除息数据"
    assert xdxr_row["category"] == "参考数据"
    assert xdxr_row["repair_action_keys"] == []
