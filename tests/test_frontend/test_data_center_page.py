from pathlib import Path


def test_data_center_page_shows_clickhouse_quality_summary() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")

    assert "数据质量" in source
    assert "qualityTagType" in source
    assert "missing_symbols" in source
    assert "missing_samples" in source
    assert "missingSampleText" in source
    assert "coverage_ratio" in source


def test_data_center_minute5_sync_uses_selected_trade_date() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    sync_minute5_body = source.split("async function syncMinute5()", 1)[1].split("async function runDailyMaintenance()", 1)[0]

    assert "minute5TradeDate" in source
    assert 'value-format="YYYY-MM-DD"' in source
    assert "trade_date: minute5TradeDate.value" in source
    assert "daily_latest_date" not in sync_minute5_body
