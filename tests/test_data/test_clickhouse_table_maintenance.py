from __future__ import annotations

from src.data.clickhouse_table_maintenance import (
    daily_duplicate_stats,
    deduplicate_daily_kline,
    deduplicate_minute5_kline,
    minute5_duplicate_stats,
)


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, object | None]] = []
        self.duplicate_rows = [(15331, 15331)]
        self.table_exists = False

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from system.tables" in normalized:
            return [(1 if self.table_exists else 0,)]
        if "from (" in normalized and "having count() > 1" in normalized:
            return self.duplicate_rows
        return []


def test_minute5_duplicate_stats_counts_duplicate_groups_and_extra_rows() -> None:
    client = FakeClickHouseClient()

    result = minute5_duplicate_stats(client=client)

    assert result == {"duplicate_groups": 15331, "extra_rows": 15331}


def test_daily_duplicate_stats_counts_duplicate_groups_and_extra_rows() -> None:
    client = FakeClickHouseClient()

    result = daily_duplicate_stats(client=client)

    assert result == {"duplicate_groups": 15331, "extra_rows": 15331}


def test_deduplicate_minute5_kline_dry_run_only_reports_plan() -> None:
    client = FakeClickHouseClient()

    result = deduplicate_minute5_kline(client=client, dry_run=True, suffix="test")

    assert result["dry_run"] is True
    assert result["before"] == {"duplicate_groups": 15331, "extra_rows": 15331}
    assert result["replacement_table"] == "minute5_kline_dedup_test"
    assert not any("rename table" in query.lower() for query, _ in client.commands)


def test_deduplicate_minute5_kline_rebuilds_replacing_merge_tree_and_swaps_tables() -> None:
    client = FakeClickHouseClient()

    result = deduplicate_minute5_kline(client=client, dry_run=False, suffix="test")

    executed = [" ".join(query.lower().split()) for query, _ in client.commands]
    assert result["dry_run"] is False
    assert result["backup_table"] == "minute5_kline_backup_test"
    assert any("create table minute5_kline_dedup_test" in query for query in executed)
    assert any("replacingmergetree(updated_at)" in query for query in executed)
    assert any("group by symbol, datetime" in query for query in executed)
    assert any("rename table minute5_kline to minute5_kline_backup_test, minute5_kline_dedup_test to minute5_kline" in query for query in executed)


def test_deduplicate_daily_kline_rebuilds_merge_tree_and_swaps_tables() -> None:
    client = FakeClickHouseClient()

    result = deduplicate_daily_kline(client=client, dry_run=False, suffix="test")

    executed = [" ".join(query.lower().split()) for query, _ in client.commands]
    assert result["dry_run"] is False
    assert result["backup_table"] == "daily_kline_backup_test"
    assert any("create table daily_kline_dedup_test" in query for query in executed)
    assert any("engine = mergetree" in query for query in executed)
    assert any("group by symbol, date" in query for query in executed)
    assert any("rename table daily_kline to daily_kline_backup_test, daily_kline_dedup_test to daily_kline" in query for query in executed)
