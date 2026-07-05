from __future__ import annotations

from scripts.check_data_sources import run_source_checks


def test_run_source_checks_reports_source_statuses() -> None:
    class FakeTencent:
        name = "tencent"

        def fetch_realtime_quotes(self, symbols):
            import pandas as pd

            return pd.DataFrame([{"symbol": "000001.SZ", "price": 11.0}])

    class FakeEastmoney:
        name = "eastmoney_signal"

        def fetch_concept_blocks(self, symbol):
            return {"total": 2, "concept_tags": ["银行", "中特估"], "boards": []}

        def fetch_minute_fund_flow(self, symbol):
            return [{"time": "14:30", "main_net": 1.0}]

    class FakeCninfo:
        name = "cninfo"

        def fetch_announcements(self, symbol, page_size=3):
            return [{"title": "公告"}]

    rows = run_source_checks(
        symbol="000001.SZ",
        tencent_source=FakeTencent(),
        eastmoney_source=FakeEastmoney(),
        cninfo_source=FakeCninfo(),
    )

    assert rows == [
        {"source": "tencent", "ok": True, "detail": "quotes=1"},
        {"source": "eastmoney_concepts", "ok": True, "detail": "blocks=2"},
        {"source": "eastmoney_fund_flow", "ok": True, "detail": "rows=1"},
        {"source": "cninfo", "ok": True, "detail": "announcements=1"},
    ]
