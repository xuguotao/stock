from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.data.market_enrichment_sync import sync_market_enrichment


class FakeQuoteSource:
    def fetch_realtime_quotes(self, symbols):
        return pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "price": 11.06,
                    "change_pct": -1.6,
                    "volume": 100000,
                    "amount": 110600000.0,
                    "turnover_pct": 1.2,
                    "pe_ttm": 4.98,
                    "pb": 0.47,
                    "mcap": 220000000000.0,
                    "float_mcap": 210000000000.0,
                    "limit_up": 12.36,
                    "limit_down": 10.12,
                    "timestamp": "2026-06-15 15:00:00",
                }
            ]
        )


class FakeSignalSource:
    def fetch_concept_blocks(self, symbol):
        return {
            "total": 2,
            "boards": [
                {"code": "BK0475", "name": "银行Ⅱ", "change_pct": -1.08, "lead_stock": "厦门银行"},
                {"code": "BK0428", "name": "广东板块", "change_pct": 0.1, "lead_stock": "平安银行"},
            ],
        }

    def fetch_minute_fund_flow(self, symbol):
        return [{"time": "14:30", "main_net": 1.0}]


class FakeCninfoSource:
    def fetch_announcements(self, symbol, page_size=10):
        return [
            {
                "title": "2025年年度权益分派实施公告",
                "type": "权益分派",
                "date": "2026-06-05",
                "url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId=1",
            }
        ]


def test_sync_market_enrichment_creates_tables_and_upserts_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.db"

    result = sync_market_enrichment(
        db_path=db_path,
        symbols=["000001.SZ"],
        quote_source=FakeQuoteSource(),
        signal_source=FakeSignalSource(),
        cninfo_source=FakeCninfoSource(),
        checked_at="2026-06-15 15:01:00",
        announcement_page_size=10,
    )

    assert result == {
        "symbols": 1,
        "quote_rows": 1,
        "concept_rows": 2,
        "announcement_rows": 1,
        "health_rows": 4,
    }

    with sqlite3.connect(db_path) as conn:
        quote = conn.execute(
            "select symbol, price, pe_ttm, pb, limit_up from stock_quote_snapshots"
        ).fetchone()
        concepts = conn.execute(
            "select symbol, block_code, block_name from stock_concept_blocks order by block_code"
        ).fetchall()
        announcement = conn.execute(
            "select symbol, title, date from stock_announcements"
        ).fetchone()
        health = conn.execute(
            "select source, ok, detail from data_source_health order by source"
        ).fetchall()

    assert quote == ("000001.SZ", 11.06, 4.98, 0.47, 12.36)
    assert concepts == [
        ("000001.SZ", "BK0428", "广东板块"),
        ("000001.SZ", "BK0475", "银行Ⅱ"),
    ]
    assert announcement == ("000001.SZ", "2025年年度权益分派实施公告", "2026-06-05")
    assert health == [
        ("cninfo", 1, "announcements=1"),
        ("eastmoney_concepts", 1, "blocks=2"),
        ("eastmoney_fund_flow", 1, "rows=1"),
        ("tencent", 1, "quotes=1"),
    ]


def test_sync_market_enrichment_replaces_concepts_for_symbol(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.db"
    sync_market_enrichment(
        db_path=db_path,
        symbols=["000001.SZ"],
        quote_source=FakeQuoteSource(),
        signal_source=FakeSignalSource(),
        cninfo_source=FakeCninfoSource(),
        checked_at="2026-06-15 15:01:00",
    )

    class NewSignalSource(FakeSignalSource):
        def fetch_concept_blocks(self, symbol):
            return {
                "total": 1,
                "boards": [
                    {"code": "BK9999", "name": "测试板块", "change_pct": 1.0, "lead_stock": "平安银行"},
                ],
            }

    sync_market_enrichment(
        db_path=db_path,
        symbols=["000001.SZ"],
        quote_source=FakeQuoteSource(),
        signal_source=NewSignalSource(),
        cninfo_source=FakeCninfoSource(),
        checked_at="2026-06-15 15:02:00",
    )

    with sqlite3.connect(db_path) as conn:
        concepts = conn.execute(
            "select block_code, block_name from stock_concept_blocks"
        ).fetchall()

    assert concepts == [("BK9999", "测试板块")]
