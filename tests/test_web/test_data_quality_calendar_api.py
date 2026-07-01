from __future__ import annotations

import json
from datetime import date, datetime

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.data_quality_calendar import (
    QUALITY_SOURCE_KEYS,
    DataQualityCalendarService,
)


class FakeCalendarClient:
    def __init__(self):
        self.commands: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from data_quality_calendar final" in normalized:
            return []
        if "from trade_calendar" in normalized:
            return [(date(2026, 7, 1),)]
        return []


class FakeQualityCalendarClient(FakeCalendarClient):
    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "create table if not exists data_quality_calendar" in normalized:
            return []
        if "insert into data_quality_calendar" in normalized:
            return []
        if "from trade_calendar" in normalized:
            return [(date(2026, 7, 1),)]
        if "from stocks" in normalized and "count()" in normalized:
            return [(2,)]
        if "from daily_kline" in normalized and "count()" in normalized:
            return [(2, datetime(2026, 7, 1), 2, 1, 0)]
        if "from minute5_kline" in normalized and "count()" in normalized:
            return [(80, datetime(2026, 7, 1, 15, 0), 2, 40, 0)]
        if "from stock_quote_snapshots_1m" in normalized:
            return [(400, datetime(2026, 7, 1, 15, 0), 2, 200, 0)]
        if "from stock_quote_snapshots_5m" in normalized:
            return [(80, datetime(2026, 7, 1, 15, 0), 2, 40, 0)]
        if "from stock_quote_snapshots" in normalized and "group by snapshot_at" in normalized:
            return [
                (datetime(2026, 7, 1, 9, 30, 0),),
                (datetime(2026, 7, 1, 9, 30, 10),),
                (datetime(2026, 7, 1, 9, 30, 40),),
                (datetime(2026, 7, 1, 11, 30, 0),),
                (datetime(2026, 7, 1, 13, 0, 0),),
            ]
        if "from stock_quote_snapshots" in normalized:
            return [(2000, datetime(2026, 7, 1, 15, 0), 2, 1000, 0)]
        if "from data_source_health" in normalized:
            return [(6, datetime(2026, 7, 1, 15, 10), 5, 1)]
        return []


class StoredQualityCalendarClient(FakeCalendarClient):
    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "create table if not exists data_quality_calendar" in normalized:
            return []
        if "from trade_calendar" in normalized:
            return [(date(2026, 7, 1),), (date(2026, 7, 2),)]
        if "from data_quality_calendar final" in normalized:
            return [
                (
                    date(2026, 7, 1),
                    "daily_kline",
                    "股票日线",
                    "ok",
                    datetime(2026, 7, 1),
                    2,
                    2,
                    1.0,
                    1,
                    1,
                    0,
                    0,
                    0,
                    "可修复",
                    "覆盖 2/2",
                    json.dumps({"table": "daily_kline"}, ensure_ascii=False),
                    datetime(2026, 7, 1, 15, 10),
                ),
                (
                    date(2026, 7, 1),
                    "minute5_kline",
                    "5m 分钟线",
                    "warning",
                    datetime(2026, 7, 1, 15, 0),
                    2,
                    2,
                    1.0,
                    48,
                    40,
                    8,
                    0,
                    0,
                    "可修复",
                    "覆盖 2/2，缺桶 8",
                    json.dumps({"table": "minute5_kline"}, ensure_ascii=False),
                    datetime(2026, 7, 1, 15, 10),
                ),
            ]
        return []


class FakeQualityCalendarService:
    def list(self, *, start, end, source_keys=None):
        return {
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "source_keys": source_keys or ["daily_kline"],
            "sources": [{"key": "daily_kline", "name": "股票日线", "table": "daily_kline"}],
            "dates": [{"trade_date": start.isoformat(), "overall_status": "unchecked", "checked_at": None, "sources": []}],
        }

    def generate(self, *, start, end, source_keys=None):
        return {"generated_dates": 1, "rows": 1}


def test_data_quality_calendar_ensure_table_creates_replacing_table() -> None:
    client = FakeCalendarClient()
    service = DataQualityCalendarService(client=client)

    service.ensure_table()

    executed = [" ".join(query.lower().split()) for query, _ in client.commands]
    assert any("create table if not exists data_quality_calendar" in query for query in executed)
    assert any("replacingmergetree(checked_at)" in query for query in executed)
    assert any("order by (trade_date, source_key)" in query for query in executed)


def test_generate_day_writes_core_quality_sources() -> None:
    client = FakeQualityCalendarClient()
    service = DataQualityCalendarService(client=client)

    result = service.generate(start=date(2026, 7, 1), end=date(2026, 7, 1))

    assert result == {"generated_dates": 1, "rows": 6}
    inserts = [
        params
        for query, params in client.commands
        if "insert into data_quality_calendar" in " ".join(query.lower().split())
    ]
    assert len(inserts) == 1
    rows = inserts[0]
    assert [row[1] for row in rows] == list(QUALITY_SOURCE_KEYS)
    minute5 = next(row for row in rows if row[1] == "minute5_kline")
    assert minute5[3] == "warning"
    assert minute5[10] > 0


def test_list_quality_calendar_returns_matrix_rows() -> None:
    client = StoredQualityCalendarClient()
    service = DataQualityCalendarService(client=client)

    payload = service.list(start=date(2026, 7, 1), end=date(2026, 7, 2))

    assert payload["range"] == {"start": "2026-07-01", "end": "2026-07-02"}
    assert payload["source_keys"] == list(QUALITY_SOURCE_KEYS)
    assert payload["dates"][0]["trade_date"] == "2026-07-02"
    assert payload["dates"][0]["overall_status"] == "unchecked"
    assert payload["dates"][1]["trade_date"] == "2026-07-01"
    assert payload["dates"][1]["overall_status"] == "warning"
    assert payload["dates"][1]["sources"][0]["source_key"] == "daily_kline"


def test_data_quality_calendar_api_lists_and_generates(tmp_path) -> None:
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        stock_db_path=tmp_path / "stock.db",
        data_quality_calendar_service=FakeQualityCalendarService(),
    )
    client = TestClient(app)

    listed = client.get("/api/data/quality-calendar?start=2026-07-01&end=2026-07-01")
    generated = client.post("/api/data/quality-calendar/generate", json={"start": "2026-07-01", "end": "2026-07-01"})

    assert listed.status_code == 200
    assert listed.json()["dates"][0]["overall_status"] == "unchecked"
    assert generated.status_code == 200
    assert generated.json() == {"generated_dates": 1, "rows": 1}
