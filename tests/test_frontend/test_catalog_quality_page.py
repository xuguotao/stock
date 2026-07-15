from pathlib import Path


def test_catalog_quality_page_shows_universe_filters_and_profile_details() -> None:
    source = Path("frontend/src/pages/CatalogQuality.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "股票池快照" in source
    assert "selectedFilters" in source
    assert "getMootdxUniverseProfiles" in source
    assert "MootdxUniverseProfilesResponse" in client
    assert "当前命中" in source
    assert "清空筛选" in source
    assert "规则：{{ ruleSummary }}" in source
    assert "近 20 日至少 15 个成交日" in source
    assert "liquidityLabel" in source
    assert "watch(activeFilters" in source
    assert "displayProfile" in source
    assert "toFixed(2)} 亿" not in source
    assert "universe_eligible:1" in source
    assert "Promise.allSettled" in source
    assert "maximumFractionDigits: 2" in source
    assert "el-tree" in source
    assert "排除原因" in source
    assert "el-pagination" in source
    assert "selectedProfile" in source
    assert "profileTotal" in source
    assert "满足成交规则，不以最新日线为前提" in source
    assert "较上一步减少" not in source
    assert "change-workspace" in source
    assert "发现日期" in source
    assert "selectedChangeDate" in source
    assert "selectedChangeType" in source
    assert "getMootdxCatalogChangeEvents" in source
