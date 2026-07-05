"""Tests for DataAggregator SQLite removal."""
from __future__ import annotations

from src.data.aggregator import DataAggregator


def test_aggregator_no_sqlite_source():
    """SQLite should not be in the default source chain."""
    agg = DataAggregator()
    source_names = [s.name for s in agg.sources]
    assert "sqlite" not in source_names, f"SQLite should be removed, found: {source_names}"


def test_prefer_source_over_cache_no_sqlite():
    """_prefer_source_over_cache should not check for sqlite."""
    agg = DataAggregator()
    from src.data.clickhouse_source import ClickHouseStockDataSource
    agg.sources = [ClickHouseStockDataSource()]
    assert agg._prefer_source_over_cache() is True
