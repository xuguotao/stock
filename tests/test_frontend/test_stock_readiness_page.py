from pathlib import Path


def test_stock_readiness_feature_files_and_api_exist() -> None:
    types = Path("frontend/src/features/stock-readiness/types.ts").read_text(encoding="utf-8")
    composable = Path("frontend/src/features/stock-readiness/useStockReadiness.ts").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "export interface StockReadinessItem" in types
    assert "export function useStockReadiness" in composable
    assert "api.getStockReadiness" in composable
    assert "api.getJob" in composable
    assert "activeRepairJob" in composable
    assert "activeSnapshotJob" in composable
    assert "repairStatusText" in composable
    assert "snapshotStatusText" in composable
    assert "generateSnapshot" in composable
    assert "const DEFAULT_DIMENSIONS: ReadinessDimensionKey[] = ['daily', 'minute5']" in composable
    assert "getStockReadinessSummary" in client
    assert "generateStockReadinessSnapshot" in client
    assert "repairStockReadiness" in client


def test_stock_readiness_page_and_router_are_registered() -> None:
    router = Path("frontend/src/router.ts").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/StockReadiness.vue").read_text(encoding="utf-8")

    assert "name: 'stock-readiness'" in router
    assert "策略数据就绪度" in router
    assert "StockReadiness" in router
    assert "策略数据就绪度" in page
    assert "useStockReadiness" in page
    assert "activeRepairJob" in page
    assert "activeSnapshotJob" in page
    assert "repairStatusText" in page
    assert "snapshotStatusText" in page
    assert "生成当前窗口快照" in page
    assert "已建档股票" in page
    assert "仅展示已生成就绪度快照的股票" in page
    assert "快照不足维度" in page
    assert "快照不足" in page
    assert "查询窗口交易日" in page
    assert "快照检查交易日" in page
    assert "就绪维度" in page
    assert "无数据维度" in page
    assert "筛选按所选维度同时满足计算" in page
    assert "可回补维度" in page
    for text in ["回补", "覆盖率", "缺失天数", "日线", "5m"]:
        assert text in page


def test_stock_readiness_formatters_explain_snapshot_insufficient() -> None:
    formatter = Path("frontend/src/features/stock-readiness/formatters.ts").read_text(encoding="utf-8")

    assert "snapshot_insufficient" in formatter
    assert "快照不足" in formatter
