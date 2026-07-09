from pathlib import Path


def test_watchlist_monitor_page_contains_status_sections() -> None:
    page = Path("frontend/src/pages/WatchlistMonitor.vue").read_text(encoding="utf-8")

    assert "观察池监控" in page
    assert "试仓区" in page
    assert "等待回踩" in page
    assert "行情源" in page
    assert "快照时间" in page
    assert "快照自动更新" in page
    assert "latestSnapshotTime" in page
    assert "snapshot_ok" in page
    assert "getWatchlistMonitorReport" in page


def test_watchlist_monitor_page_links_to_stock_trend() -> None:
    page = Path("frontend/src/pages/WatchlistMonitor.vue").read_text(encoding="utf-8")

    assert "openStockTrend(row.symbol)" in page
    assert "window.open(stockTrendUrl(symbol), '_blank'" in page
    assert "/stock-trend/" in page


def test_watchlist_monitor_page_auto_refreshes_from_snapshots() -> None:
    page = Path("frontend/src/pages/WatchlistMonitor.vue").read_text(encoding="utf-8")

    assert "REFRESH_INTERVAL_MS = 10_000" in page
    assert "refreshFromSnapshot" in page
    assert "window.setInterval(refreshFromSnapshot" in page
    assert "onBeforeUnmount(stopAutoRefresh)" in page
    assert "nextReport.items.find((item) => item.symbol === previousSymbol)" in page


def test_app_registers_watchlist_monitor_page() -> None:
    router = Path("frontend/src/router.ts").read_text(encoding="utf-8")

    assert "name: 'watchlist-monitor'" in router
    assert "WatchlistMonitor" in router
