"""Tests for tdxrs sync utilities."""
from __future__ import annotations

from src.data.tdxrs_sync import is_tdxrs_available, fetch_xdxr_info


def test_is_tdxrs_available():
    """Check if tdxrs is available (may be False if not installed)."""
    result = is_tdxrs_available()
    assert isinstance(result, bool)


def test_fetch_xdxr_info_returns_list():
    """fetch_xdxr_info should return a list of xdxr events."""
    if not is_tdxrs_available():
        return  # Skip if not installed
    result = fetch_xdxr_info("000001.SZ")
    assert isinstance(result, list)
    if result:
        assert "year" in result[0]
        assert "month" in result[0]
        assert "day" in result[0]
        assert "category" in result[0]
