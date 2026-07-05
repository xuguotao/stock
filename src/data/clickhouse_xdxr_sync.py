"""Sync 除权除息 data from tdxrs to ClickHouse."""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def sync_clickhouse_xdxr_info(
    client: Any,
    fetch_fn: Callable[[str], list[dict]],
    symbols: list[str],
) -> dict[str, int]:
    """Sync xdxr info for given symbols into ClickHouse xdxr_info table.

    Args:
        client: ClickHouse client
        fetch_fn: Function that fetches xdxr data for a symbol (e.g., fetch_xdxr_info)
        symbols: List of stock symbols like ["000001.SZ", "600000.SH"]

    Returns dict with counts: {"inserted": N, "failed": K}
    """
    _ensure_table(client)
    inserted = 0
    failed = 0

    for symbol in symbols:
        try:
            xdxr_list = fetch_fn(symbol)
            if not xdxr_list:
                continue

            for xdxr in xdxr_list:
                query = """
                INSERT INTO xdxr_info (
                    symbol, year, month, day, category,
                    fenhong, songzhuangu, peigu, suogu
                ) VALUES
                """
                values = (
                    symbol,
                    xdxr.get("year", 0),
                    xdxr.get("month", 0),
                    xdxr.get("day", 0),
                    xdxr.get("category", 0),
                    float(xdxr.get("fenhong", 0.0) or 0.0),
                    float(xdxr.get("songzhuangu", 0.0) or 0.0),
                    float(xdxr.get("peigu", 0.0) or 0.0),
                    float(xdxr.get("suogu", 0.0) or 0.0),
                )
                client.execute(query, [values])
                inserted += 1

        except Exception as e:
            logger.warning(f"Failed to sync xdxr for {symbol}: {e}")
            failed += 1

    return {"inserted": inserted, "failed": failed}


def _ensure_table(client: Any) -> None:
    """Create xdxr_info table if it doesn't exist."""
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS xdxr_info (
            symbol String,
            year UInt16,
            month UInt8,
            day UInt8,
            category UInt8 COMMENT '1=除权除息, 2=送配股上市, 5=股本变化',
            fenhong Float64 COMMENT '每股分红（元）',
            songzhuangu Float64 COMMENT '每股送转股（股）',
            peigu Float64 COMMENT '每股配股（股）',
            suogu Float64 COMMENT '每股缩股（股）',
            ex_date Date MATERIALIZED toDate(concat(toString(year), '-', lpad(toString(month), 2, '0'), '-', lpad(toString(day), 2, '0'))),
            updated_at DateTime DEFAULT now()
        ) ENGINE = ReplacingMergeTree(updated_at)
        ORDER BY (symbol, ex_date)
        """
    )
