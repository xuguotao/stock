from pathlib import Path


def test_tail_live_selection_page_shows_run_history() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    job_source = Path("frontend/src/features/tail-live/useTailLiveJob.ts").read_text(encoding="utf-8")

    assert "运行记录" in source
    assert "tail_session_live_selection" in job_source
    assert "loadRunHistory" in source
    assert "selectRunHistory" in source
    assert "@row-click=\"selectRunHistory\"" in source


def test_tail_live_selection_page_defaults_to_full_market_and_fast_refresh_mode() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "limit: 0" in source
    assert "universe: 'default'" in source
    assert "data_refresh_mode: 'auto'" in source
    assert "strategy_mode: 'rule'" in source
    assert "策略模式" in source
    assert "规则优先" in source
    assert "模型排序" in source
    assert "混合模式" in source
    assert "数据刷新模式" in source
    assert "快照优先" in source
    assert "standard_minute5" in source
    assert "data_refresh_mode?: 'auto' | 'snapshot' | 'standard_minute5' | 'none'" in client
    assert "strategy_mode?: 'rule' | 'model' | 'hybrid'" in client
    assert "全市场非ST" in source
    assert "抽样分钟" in source


def test_tail_live_selection_links_symbols_to_stock_trend() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    links_source = Path("frontend/src/features/tail-live/links.ts").read_text(encoding="utf-8")
    router_source = Path("frontend/src/router.ts").read_text(encoding="utf-8")

    assert "openStockTrend" in source
    assert "@click=\"openStockTrend(row.symbol)\"" in source
    assert "window.open(stockTrendUrl(symbol), '_blank', 'noopener,noreferrer')" in source
    assert "/stock-trend/" in links_source
    assert "granularity: '5m'" in links_source
    assert "normalizeLegacyPageQuery" in router_source
    assert "StockTrend" in router_source


def test_tail_live_selection_page_explains_new_filter_reasons() -> None:
    source = tail_live_sources()

    assert "涨停/近涨停，无法买入" in source
    assert "尾盘冲高回落" in source
    assert "历史校准排名超出 Top N" in source
    assert "pullback_from_high" in source


def test_tail_live_selection_page_labels_signal_quality_and_rank_context() -> None:
    source = tail_live_sources()

    assert "规则分" in source
    assert "校准概率" in source
    assert "历史胜率" in source
    assert "历史平均收益" in source
    assert "原始排名" in source
    assert "候选排名" in source
    assert "raw_rank" in source
    assert "final_candidate_rank" in source
    assert "V2分" in source


def test_tail_live_selection_page_shows_model_feature_snapshot() -> None:
    source = tail_live_sources()

    assert "模型因子" in source
    assert "feature_snapshot" in source
    assert "modelFeatureText" in source
    assert "行业5日" in source
    assert "相对行业5日" in source


def test_tail_live_selection_page_explains_model_enhanced_selection() -> None:
    source = tail_live_sources()

    assert "模型增强状态" in source
    assert "modelEnhancementItems" in source
    assert "modelDecisionText" in source
    assert "模型提权" in source
    assert "规则+模型一致" in source
    assert "模型淘汰" in source
    assert "规则候选→最终" in source
    assert "outside_model_top_n" in source
    assert "模型未进 Top N" in source


def test_tail_live_selection_page_shows_executability_fields() -> None:
    source = tail_live_sources()

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
    source = tail_live_sources()

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
    source = tail_live_sources()
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


def test_tail_live_selection_limits_large_result_tables() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    styles = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "RESULT_TABLE_RENDER_BATCH_SIZE" in source
    assert ":data=\"displayedRankedSignals\"" in source
    assert ":data=\"displayedWatchlistSignals\"" in source
    assert ":data=\"displayedWeakSignals\"" in source
    assert "slice(0, strategyRenderLimit.value)" in source
    assert "showMoreStrategyRows" in source
    assert "仅展示前" in source
    assert ".table-footer-actions" in styles


def test_tail_live_selection_polls_long_running_full_market_jobs() -> None:
    source = Path("frontend/src/features/tail-live/useTailLiveJob.ts").read_text(encoding="utf-8")

    assert "JOB_POLL_INTERVAL_MS = 1000" in source
    assert "JOB_POLL_MAX_ATTEMPTS = 900" in source
    assert "attempt < JOB_POLL_MAX_ATTEMPTS" in source
    assert "sleep(JOB_POLL_INTERVAL_MS)" in source
    assert "任务仍在运行，页面会保留当前任务" in source


def test_tail_live_selection_uses_dedicated_final_selection_table_component() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    component_path = Path("frontend/src/pages/tail-live/TailSelectionTable.vue")

    assert component_path.exists()
    component = component_path.read_text(encoding="utf-8")
    assert "import TailSelectionTable" in source
    assert "<TailSelectionTable" in source
    assert ":rows=\"selections\"" in source
    assert "@open-stock-trend=\"openStockTrend\"" in source
    assert "credibility-detail" in component
    assert "模型因子" in component
    assert "defineEmits" in component


def test_tail_live_selection_uses_dedicated_data_health_panel_component() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    component_path = Path("frontend/src/pages/tail-live/TailDataHealthPanel.vue")

    assert component_path.exists()
    component = component_path.read_text(encoding="utf-8")
    assert "import TailDataHealthPanel" in source
    assert "<TailDataHealthPanel" in source
    assert ":items=\"dataHealthItems\"" in source
    assert ":issues=\"dataHealthIssues\"" in source
    assert "选股数据健康度" in component
    assert "health-status-grid" in component


def test_tail_live_selection_precheck_data_status_column_has_single_slot_template() -> None:
    source = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")

    assert '<el-table-column label="数据状态" width="130">' in source
    assert '<template #default="{ row }">\n            <template #default="{ row }">' not in source


def tail_live_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            Path("frontend/src/pages/TailLiveSelection.vue"),
            Path("frontend/src/pages/tail-live/TailSelectionTable.vue"),
            Path("frontend/src/pages/tail-live/TailDataHealthPanel.vue"),
            Path("frontend/src/features/tail-live/formatters.ts"),
            Path("frontend/src/features/tail-live/useTailLiveDataHealth.ts"),
            Path("frontend/src/features/tail-live/useTailLiveJob.ts"),
        ]
        if path.exists()
    )
