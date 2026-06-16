from __future__ import annotations

import sqlite3
from pathlib import Path

from src.data.market_enrichment_sync import resolve_symbols_from_database


def test_resolve_symbols_from_database_skips_st_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table stocks (symbol text, name text)")
        conn.execute("insert into stocks values ('000001', '平安银行')")
        conn.execute("insert into stocks values ('000004', '*ST国华')")
        conn.execute("insert into stocks values ('600519', '贵州茅台')")

    assert resolve_symbols_from_database(db_path, limit=10) == ["000001.SZ", "600519.SH"]
    assert resolve_symbols_from_database(db_path, limit=2, include_st=True) == [
        "000001.SZ",
        "000004.SZ",
    ]
