from pathlib import Path


def test_stock_list_page_shows_research_universe_status_and_exclusion_reasons() -> None:
    source = Path("frontend/src/pages/StockList.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "research_eligible" in client
    assert "data_ready" in client
    assert "excluded_reasons" in client
    assert "data_gap_reasons" in client
    assert "daily_missing" in client
    assert "minute5_missing" in client
    assert "研究池" in source
    assert "数据就绪" in source
    assert "数据待补" in source
    assert "未纳入原因" in source
    assert "excludedReasonText" in source
    assert "delisting_period" in source
    assert "日线待补" in source
    assert "5m待补" in source
