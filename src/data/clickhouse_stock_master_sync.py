"""Sync stock master data into ClickHouse."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data.models import StockInfo


def sync_clickhouse_stock_master(
    *,
    source: Any | None = None,
    client: Any | None = None,
    checked_at: str | None = None,
    research_status_sync: Any | None = None,
) -> dict[str, Any]:
    """Sync Tencent stock universe into the ClickHouse stocks table.

    Tencent does not provide industry or list date in the tested universe endpoint,
    so existing enrichment fields are preserved when present.
    """
    clickhouse = client or _default_client()
    data_source = source or _default_source()
    updated_at = _datetime_value(checked_at) if checked_at else datetime.now().replace(microsecond=0)
    _ensure_table(clickhouse)
    existing = _existing_enrichment(clickhouse)
    stocks = data_source.fetch_stock_list()
    rows = _stock_rows(stocks, existing, updated_at)
    if rows:
        clickhouse.execute(
            """
            insert into stocks (symbol, name, industry, market, list_date, updated_at)
            values
            """,
            rows,
        )
    if research_status_sync is None:
        from src.data.stock_research_status_sync import sync_stock_research_status

        research_status_sync = sync_stock_research_status
    research_status = research_status_sync(client=clickhouse, checked_at=updated_at, quote_source=data_source)
    return {
        "source": getattr(data_source, "name", "tencent"),
        "fetched_rows": len(stocks),
        "inserted_rows": len(rows),
        "preserved_enrichment_rows": sum(1 for row in rows if row[2] or row[4]),
        "research_status": research_status,
    }


def _ensure_table(client: Any) -> None:
    client.execute(
        """
        create table if not exists stocks (
            symbol String,
            name String,
            industry String,
            market LowCardinality(String),
            list_date String,
            updated_at DateTime
        )
        engine = ReplacingMergeTree(updated_at)
        order by symbol
        """
    )


def _existing_enrichment(client: Any) -> dict[str, dict[str, Any]]:
    try:
        rows = client.execute(
            """
            select symbol, name, industry, market, list_date
            from stocks
            """
        )
    except Exception:  # noqa: BLE001 - table may not exist before ensure on fake/old clients.
        return {}
    result: dict[str, dict[str, Any]] = {}
    for symbol, name, industry, market, list_date in rows:
        code = str(symbol).zfill(6)
        result[code] = {
            "name": str(name or ""),
            "industry": str(industry or ""),
            "market": str(market or ""),
            "list_date": list_date,
        }
    return result


def _stock_rows(stocks: list[StockInfo], existing: dict[str, dict[str, Any]], updated_at: str) -> list[tuple[Any, ...]]:
    rows = []
    seen: set[str] = set()
    for stock in stocks:
        code = str(stock.code or stock.symbol.split(".")[0]).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        current = existing.get(code, {})
        rows.append(
            (
                code,
                str(stock.name or ""),
                stock.industry or current.get("industry", ""),
                _market_from_symbol(stock.symbol) or current.get("market", ""),
                _list_date_text(stock.list_date or current.get("list_date")),
                updated_at,
            )
        )
    return rows


def _list_date_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value or "")


def _datetime_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" ", "T"))


def _market_from_symbol(symbol: str) -> str:
    if "." not in symbol:
        return ""
    return symbol.rsplit(".", 1)[1].upper()


def _default_source() -> Any:
    from src.data.tencent_source import TencentQuoteSource

    return TencentQuoteSource(rate_limit=0.0)


def _default_client() -> Any:
    from src.data.clickhouse_source import ClickHouseStockDataSource

    return ClickHouseStockDataSource()._client_instance()
