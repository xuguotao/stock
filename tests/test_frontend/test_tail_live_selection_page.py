from pathlib import Path


def test_tail_live_selection_page_shows_run_history() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "运行记录" in source
    assert "tail_session_live_selection" in source
    assert "loadRunHistory" in source
    assert "selectRunHistory" in source
    assert "@row-click=\"selectRunHistory\"" in source


def test_tail_live_selection_page_defaults_to_full_market_and_auto_sync() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "limit: 0" in source
    assert "universe: 'default'" in source
    assert "auto_sync_minute5: true" in source
    assert "运行前补数据" in source
    assert "全市场非ST" in source
    assert "抽样分钟" in source


def test_tail_live_selection_links_symbols_to_stock_trend() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    app_source = Path("frontend/src/App.vue").read_text(encoding="utf-8")

    assert "openStockTrend" in source
    assert "@click=\"openStockTrend(row.symbol)\"" in source
    assert "window.open(stockTrendUrl(symbol), '_blank', 'noopener,noreferrer')" in source
    assert "page: 'stock-trend'" in source
    assert "granularity: '5m'" in source
    assert "initialPage" in app_source
    assert "URLSearchParams" in app_source
    assert "StockTrend" in app_source


def test_tail_live_selection_page_explains_new_filter_reasons() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "涨停/近涨停，无法买入" in source
    assert "尾盘冲高回落" in source
    assert "pullback_from_high" in source


def test_tail_live_selection_page_shows_executability_fields() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "可执行性" in source
    assert "涨停距离" in source
    assert "次日卖出" in source
    assert "executionFlagText" in source
    assert "limit_up_distance" in source
    assert "sell_policy" in source


def test_tail_live_selection_page_shows_data_quality_and_timing_diagnostics() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "数据新鲜度" in source
    assert "实时行情" in source
    assert "阶段耗时" in source
    assert "data_freshness" in source
    assert "quote_status" in source
    assert "stage_timings" in source
    assert "score_breakdown" in source
    assert "持久化" in source


def test_tail_live_selection_page_shows_source_data_health_panel() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "选股数据健康度" in source
    assert "刷新健康度" in source
    assert "loadDataHealth" in source
    assert "getDataStatus" in source
    assert "分钟线覆盖" in source
    assert "分钟线最新" in source
    assert "行情快照" in source
    assert "日线质量" in source


def test_tail_live_selection_page_labels_full_market_limit_clearly() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "scanLimitDisplayText" in source
    assert "全市场非ST" in source
    assert "扫描数量" in source


def test_tail_live_selection_page_shows_current_minute5_bucket_separately() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "分钟线写入中" in source
    assert "current_latest_datetime" in source
    assert "current_covered_symbols" in source


def test_tail_live_selection_data_health_panel_uses_compact_status_layout() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    styles = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "health-status-grid" in source
    assert "health-status-item" in source
    assert "health-status-value" in source
    assert "formatCompactDateTime" in source
    assert "dedupeIssues" in source
    assert ".health-status-value" in styles
    assert "font-size: 14px" in styles


def test_tail_live_selection_result_summary_uses_compact_status_layout() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert "result-status-grid" in source
    assert "result-status-item" in source
    assert "result-status-value" in source
    assert "compactDataFreshnessText" in source
    assert "compactQuoteStatusText" in source
    assert "compactSyncSummaryText" in source
