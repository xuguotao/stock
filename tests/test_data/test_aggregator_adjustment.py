"""Tests for DataAggregator with adjustment support."""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pandas as pd

from src.data.aggregator import DataAggregator


class FakeDataSource:
    """Fake data source for testing."""

    name = "fake"

    def fetch_bars(self, symbol: str, start: date, end: date, frequency: str) -> pd.DataFrame:
        """Return fake bars data."""
        if symbol == "000001.SZ":
            data = [
                {"date": date(2024, 1, 8), "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.2, "volume": 1000, "amount": 10200.0, "symbol": "000001.SZ"},
                {"date": date(2024, 1, 9), "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6, "volume": 1200, "amount": 12720.0, "symbol": "000001.SZ"},
                {"date": date(2024, 1, 10), "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3, "volume": 1500, "amount": 15450.0, "symbol": "000001.SZ"},
            ]
            return pd.DataFrame(data)
        return pd.DataFrame()

    def fetch_stock_list(self) -> list:
        return []


def test_get_bars_without_adjustment():
    """Test get_bars without adjustment (backward compatibility)."""
    source = FakeDataSource()
    aggregator = DataAggregator(sources=[source])

    df = aggregator.get_bars("000001.SZ", date(2024, 1, 8), date(2024, 1, 10))

    assert not df.empty
    assert len(df) == 3
    assert "close" in df.columns
    assert "adjusted_close" not in df.columns  # No adjustment by default


def test_get_bars_with_forward_adjustment():
    """Test get_bars with forward adjustment."""
    source = FakeDataSource()
    aggregator = DataAggregator(sources=[source])

    # Mock the adjustment service
    mock_service = Mock()
    mock_service.get_adjusted_bars.return_value = pd.DataFrame([
        {"date": date(2024, 1, 8), "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.2, "volume": 1000, "amount": 10200.0, "symbol": "000001.SZ", "adjusted_close": 10.0},
        {"date": date(2024, 1, 9), "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6, "volume": 1200, "amount": 12720.0, "symbol": "000001.SZ", "adjusted_close": 10.4},
        {"date": date(2024, 1, 10), "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3, "volume": 1500, "amount": 15450.0, "symbol": "000001.SZ", "adjusted_close": 10.3},
    ])
    aggregator._adjustment_service = mock_service

    df = aggregator.get_bars("000001.SZ", date(2024, 1, 8), date(2024, 1, 10), adjusted=True)

    assert not df.empty
    assert "adjusted_close" in df.columns
    mock_service.get_adjusted_bars.assert_called_once()


def test_get_bars_with_backward_adjustment():
    """Test get_bars with backward adjustment."""
    source = FakeDataSource()
    aggregator = DataAggregator(sources=[source])

    # Mock the adjustment service
    mock_service = Mock()
    mock_service.get_adjusted_bars.return_value = pd.DataFrame([
        {"date": date(2024, 1, 8), "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.2, "volume": 1000, "amount": 10200.0, "symbol": "000001.SZ", "adjusted_close": 10.2},
        {"date": date(2024, 1, 9), "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6, "volume": 1200, "amount": 12720.0, "symbol": "000001.SZ", "adjusted_close": 10.6},
        {"date": date(2024, 1, 10), "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3, "volume": 1500, "amount": 15450.0, "symbol": "000001.SZ", "adjusted_close": 10.3},
    ])
    aggregator._adjustment_service = mock_service

    df = aggregator.get_bars("000001.SZ", date(2024, 1, 8), date(2024, 1, 10), adjusted=True, adjust_type="backward")

    assert not df.empty
    assert "adjusted_close" in df.columns
    mock_service.get_adjusted_bars.assert_called_once_with("000001.SZ", date(2024, 1, 8), date(2024, 1, 10), "backward")


def test_get_bars_adjustment_failure_returns_raw_bars():
    """Test that adjustment failure returns raw bars with warning."""
    source = FakeDataSource()
    aggregator = DataAggregator(sources=[source])

    # Mock the adjustment service to raise an exception
    mock_service = Mock()
    mock_service.get_adjusted_bars.side_effect = Exception("Adjustment failed")
    aggregator._adjustment_service = mock_service

    df = aggregator.get_bars("000001.SZ", date(2024, 1, 8), date(2024, 1, 10), adjusted=True)

    assert not df.empty
    assert "adjusted_close" in df.columns
    # Should fall back to raw close
    assert (df["adjusted_close"] == df["close"]).all()


def test_get_bars_batch_with_adjustment():
    """Test get_bars_batch with adjustment."""
    source = FakeDataSource()
    aggregator = DataAggregator(sources=[source])

    # Mock the adjustment service
    mock_service = Mock()
    mock_service.get_adjusted_bars.return_value = pd.DataFrame([
        {"date": date(2024, 1, 8), "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.2, "volume": 1000, "amount": 10200.0, "symbol": "000001.SZ", "adjusted_close": 10.0},
        {"date": date(2024, 1, 9), "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6, "volume": 1200, "amount": 12720.0, "symbol": "000001.SZ", "adjusted_close": 10.4},
    ])
    aggregator._adjustment_service = mock_service

    df = aggregator.get_bars_batch(["000001.SZ"], date(2024, 1, 8), date(2024, 1, 9), adjusted=True)

    assert not df.empty
    assert "adjusted_close" in df.columns
    assert df.index.names == ["date", "symbol"]


def test_adjustment_service_lazy_initialization():
    """Test that AdjustmentService is lazily initialized."""
    source = FakeDataSource()
    aggregator = DataAggregator(sources=[source])

    # Should be None initially
    assert aggregator._adjustment_service is None

    # Should be initialized when needed
    service = aggregator._get_adjustment_service()
    assert service is not None
    assert aggregator._adjustment_service is service

    # Should return the same instance on subsequent calls
    service2 = aggregator._get_adjustment_service()
    assert service2 is service
