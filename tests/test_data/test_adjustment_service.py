"""Tests for AdjustmentService."""
from __future__ import annotations

from datetime import date

from src.data.adjustment_service import AdjustmentService


class FakeClickHouseClient:
    """Fake ClickHouse client for testing."""

    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.lower().split())

        if "from daily_kline" in normalized:
            symbol = params.get("symbol") if params else None
            if symbol == "000001":
                return [
                    ("000001", date(2024, 1, 8), 10.0, 10.5, 9.9, 10.2, 1000, 10200.0),
                    ("000001", date(2024, 1, 9), 10.2, 10.8, 10.1, 10.6, 1200, 12720.0),
                    ("000001", date(2024, 1, 10), 10.0, 10.5, 9.8, 10.3, 1500, 15450.0),
                    ("000001", date(2024, 1, 11), 10.3, 10.9, 10.2, 10.7, 1300, 13910.0),
                    ("000001", date(2024, 1, 12), 10.7, 11.2, 10.6, 11.0, 1400, 15400.0),
                ]
            elif symbol == "600519":
                return [
                    ("600519", date(2024, 1, 8), 1800.0, 1850.0, 1790.0, 1820.0, 500, 910000.0),
                    ("600519", date(2024, 1, 9), 1820.0, 1870.0, 1810.0, 1850.0, 600, 1110000.0),
                    ("600519", date(2024, 1, 10), 1780.0, 1830.0, 1770.0, 1800.0, 700, 1260000.0),
                    ("600519", date(2024, 1, 11), 1800.0, 1850.0, 1790.0, 1830.0, 550, 1006500.0),
                    ("600519", date(2024, 1, 12), 1830.0, 1880.0, 1820.0, 1860.0, 650, 1209000.0),
                ]
        elif "from xdxr_info" in normalized:
            symbol = params.get("symbol") if params else None
            if symbol == "000001":
                return [
                    (date(2024, 1, 10), 0.5, 0.0, 0.0, 0.0),
                ]
            elif symbol == "600519":
                return [
                    (date(2024, 1, 10), 10.0, 0.0, 0.0, 0.0),
                ]
        elif "order by date desc limit 1" in normalized:
            # pre_close query
            return [(10.0,)]

        return []


def test_get_adjusted_bars_forward():
    """Test forward adjustment."""
    client = FakeClickHouseClient()
    service = AdjustmentService(client=client)

    result = service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    # Latest date should have adjusted_close = close
    latest = result[result["date"] == date(2024, 1, 12)]
    assert abs(latest.iloc[0]["adjusted_close"] - latest.iloc[0]["close"]) < 1e-6


def test_get_adjusted_bars_backward():
    """Test backward adjustment."""
    client = FakeClickHouseClient()
    service = AdjustmentService(client=client)

    result = service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="backward",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    # Earliest date should have adjusted_close = close
    earliest = result[result["date"] == date(2024, 1, 8)]
    assert abs(earliest.iloc[0]["adjusted_close"] - earliest.iloc[0]["close"]) < 1e-6


def test_get_adjusted_bars_none():
    """Test no adjustment."""
    client = FakeClickHouseClient()
    service = AdjustmentService(client=client)

    result = service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="none",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    # adjusted_close should equal close
    assert (result["adjusted_close"] == result["close"]).all()


def test_cache_xdxr_ratios():
    """Test that xdxr ratios are cached."""
    client = FakeClickHouseClient()
    service = AdjustmentService(client=client)

    # First call
    service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    # Count xdxr_info queries
    xdxr_queries_first = sum(1 for q, _ in client.calls if "from xdxr_info" in q.lower())

    # Second call should use cache
    service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    # Count xdxr_info queries again
    xdxr_queries_second = sum(1 for q, _ in client.calls if "from xdxr_info" in q.lower())

    # Second call should not query xdxr_info again
    assert xdxr_queries_second == xdxr_queries_first


def test_clear_cache():
    """Test cache clearing."""
    client = FakeClickHouseClient()
    service = AdjustmentService(client=client)

    # Populate cache
    service.get_adjusted_bars(
        symbol="000001.SZ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )
    assert "000001.SZ" in service._xdxr_cache

    # Clear cache
    service.clear_cache()
    assert len(service._xdxr_cache) == 0


def test_get_adjusted_bars_batch():
    """Test batch adjustment for multiple symbols."""
    client = FakeClickHouseClient()
    service = AdjustmentService(client=client)

    result = service.get_adjusted_bars_batch(
        symbols=["000001.SZ", "600519.SH"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        adjust_type="forward",
    )

    assert not result.empty
    assert "adjusted_close" in result.columns
    assert len(result["symbol"].unique()) == 2
