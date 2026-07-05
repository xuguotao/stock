"""Tdxrs sync utilities for data not available via HTTP APIs."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_tdxrs_available() -> bool:
    """Check if tdxrs library is installed."""
    try:
        import tdxrs
        return True
    except ImportError:
        return False


def fetch_xdxr_info(symbol: str, client: Any | None = None) -> list[dict]:
    """Fetch 除权除息 information for a symbol from 通达信.

    Args:
        symbol: Stock symbol like "000001.SZ"
        client: Optional pre-connected TdxHqClient. If None, creates a new connection.

    Returns:
        List of xdxr events with fields: year, month, day, category, bonus_amount, etc.
    """
    if not is_tdxrs_available():
        logger.warning("tdxrs is not installed")
        return []

    import tdxrs

    # Parse symbol
    parts = symbol.split(".")
    code = parts[0]
    market_suffix = parts[1] if len(parts) > 1 else "SZ"
    market = 0 if market_suffix == "SZ" else 1

    # Connect if needed
    should_disconnect = client is None
    if client is None:
        client = tdxrs.TdxHqClient()
        # Use a known stable server
        client.connect("58.63.254.191", 7709)

    try:
        xdxr_list = client.get_xdxr_info(market, code)
        return xdxr_list if xdxr_list else []
    except Exception as e:
        logger.warning(f"fetch_xdxr_info failed for {symbol}: {e}")
        return []
    finally:
        if should_disconnect:
            client.disconnect()
