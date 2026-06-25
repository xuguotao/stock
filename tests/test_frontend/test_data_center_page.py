from pathlib import Path


def test_data_center_page_shows_clickhouse_quality_summary() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")

    assert "数据质量" in source
    assert "快照覆盖" in source
    assert "快照标的" in source
    assert "stock_quote_snapshots" in source
    assert "quote_snapshot_symbol_count" in source
    assert "qualityTagType" in source
    assert "missing_symbols" in source
    assert "missing_samples" in source
    assert "missingSampleText" in source
    assert "coverage_ratio" in source
    assert "策略可交易池" in source
    assert "strategyTradableCount" in source
    assert "今日尾盘策略可用性" in source
    assert "ignored_issues" in source
    assert "已忽略" in source


def test_data_center_minute5_sync_uses_selected_trade_date() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    sync_minute5_body = source.split("async function syncMinute5()", 1)[1].split("async function runDailyMaintenance()", 1)[0]

    assert "minute5TradeDate" in source
    assert 'value-format="YYYY-MM-DD"' in source
    assert "trade_date: minute5TradeDate.value" in source
    assert "daily_latest_date" not in sync_minute5_body


def test_data_center_page_controls_minute5_monitor() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "分钟线持续更新" in source
    assert "startMinute5Monitor" in source
    assert "stopMinute5Monitor" in source
    assert "loadMinute5Monitor" in source
    assert "skip_reason" in source
    assert "skip_count" in client
    assert "started_count" in client
    assert "max_fetch_symbols" in client
    assert "完成 ${monitor.cycle_count} 次" in source
    assert "remaining_symbols" in source
    assert "剩余 ${remaining} 只待补" in source
    assert "minute5MonitorSessionText" in source
    assert "next_run_at" in source
    assert "session: {" in client
    assert "mode: string" in client
    assert "getMinute5Monitor" in client
    assert "startMinute5Monitor" in client
    assert "stopMinute5Monitor" in client


def test_data_center_page_shows_quote_snapshot_monitor() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "行情快照采集" in source
    assert "quoteSnapshotMonitorText" in source
    assert "getQuoteSnapshotMonitor" in client
    assert "QuoteSnapshotMonitorStatus" in client
    assert "quote-snapshot-monitor" in client


def test_data_center_page_shows_data_ops_scheduler() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "自动数据运维" in source
    assert "dataOpsSchedulerText" in source
    assert "getDataOpsScheduler" in source
    assert "DataOpsSchedulerStatus" in client
    assert "post_close_maintenance" in client
    assert "ops-scheduler" in client


def test_data_center_page_shows_quote_snapshot_pipeline_health() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "快照数据体系健康" in source
    assert "秒级原始" in source
    assert "1m 聚合" in source
    assert "5m 聚合" in source
    assert "quotePipelineRows" in source
    assert "actual_avg_interval_seconds" in source
    assert "missing_rate" in source
    assert "recent_windows" in client
    assert "quoteWindowText" in source
    assert "retention_days" in source
    assert "quote_snapshots" in client
    assert "raw_retention_days" in client
    assert "aggregate_retention_days" in client
    assert "quoteSnapshotMonitorCadenceText" in source
    assert "quoteSnapshotMonitorTimingText" in source
    assert "timeout_count" in client
    assert "effective_chunk_size" in client


def test_data_center_page_shows_scheduled_quality_checks() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "定时质量检查" in source
    assert "scheduledQualityRows" in source
    assert "completeness_30d" in source
    assert "today_anomalies" in source
    assert "historical_invalid_prices" in source
    assert "历史价格污染" in source
    assert "freshness" in source
    assert "scheduled_checks" in client
    assert "affected_symbols" in client
    assert "bad_rows" in client
    assert "historical_invalid_prices" in client
    assert "lag_days" in client


def test_data_center_page_uses_operations_console_layout() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")

    assert "今日尾盘策略可用性" in source
    assert "数据可靠性总控" in source
    assert "当前告警" in source
    assert "数据资产地图" in source
    assert "数据健康矩阵" in source
    assert "更新任务中心" in source
    assert "质量中心" in source
    assert "消费链路状态" in source
    assert "assetRows" in source
    assert "datasetHealthRows" in source
    assert "datasetHealthCoverageText" in source
    assert "datasetHealthRangeText" in source
    assert "update_mechanism" in source
    assert "consumer" in source
    assert "operationRows" in source
    assert "consumerReadinessRows" in source
    assert "overallReadiness" in source
    assert "可用于尾盘选股" in source


def test_data_center_client_exposes_dataset_health() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "datasets_health" in client
    assert "update_mechanism: string" in client
    assert "consumer: string" in client
    assert "coverage_ratio?: number | null" in client


def test_data_center_header_keeps_only_primary_actions() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    header = source.split('<div class="toolbar">', 1)[1].split('</div>', 1)[0]

    assert "日常维护" in header
    assert "刷新" in header
    assert "构建回测数据集" not in header
    assert "更新 5分钟线" not in header
    assert "停止持续更新" not in header
    assert "同步旧 Stock DB" not in header
    assert "高级维护" in source
    assert "manual-minute5-control" in source
    assert "dataset-build-control" not in source
    assert "本地 Research Datasets" not in source


def test_data_center_page_auto_refreshes_background_status() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")

    assert "startAutoRefresh" in source
    assert "stopAutoRefresh" in source
    assert "window.setInterval(refreshOperationalStatus" in source
    assert "window.setInterval(refreshDataStatus" in source
    assert "onBeforeUnmount(stopAutoRefresh)" in source


def test_data_center_page_exposes_health_repair_plan_actions() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "告警修复计划" in source
    assert "自动修复可处理项" in source
    assert "repairDataHealth" in source
    assert "pollHealthRepairJob" in source
    assert "getDataHealthRepairPlan" in client
    assert "repairDataHealth" in client


def test_data_center_page_uses_combined_reliability_status_endpoint() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    load_data_body = source.split("async function loadData()", 1)[1].split("async function loadRepairPlan()", 1)[0]
    refresh_body = source.split("async function refreshDataStatus()", 1)[1].split("async function loadMinute5Monitor()", 1)[0]

    assert "getDataReliability" in client
    assert "DataReliabilityReport" in client
    assert "data_status: DataStatusResponse" in client
    assert "repair_plan: DataHealthRepairPlan" in client
    assert "dataStatus.value = reliabilityResponse.data_status" in load_data_body
    assert "repairPlan.value = reliabilityResponse.repair_plan" in load_data_body
    assert "api.getDataStatus()" not in load_data_body
    assert "api.getDataHealthRepairPlan()" not in load_data_body
    assert "api.getDataReliability()" in refresh_body
    assert "api.getDataStatus()" not in refresh_body


def test_data_center_page_shows_tail_ml_training_data_audit() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "尾盘模型训练数据" in source
    assert "tailMlAudit" in source
    assert "getTailMlAudit" in source
    assert "minute5_usable_days" in source
    assert "joinable_label_days" in source
    assert "TailMlAuditResponse" in client
    assert "/api/ml/tail/audit" in client


def test_data_center_page_does_not_let_tail_ml_audit_failure_blank_core_data() -> None:
    source = Path("frontend/src/pages/DataCenter.vue").read_text(encoding="utf-8")
    load_data_body = source.split("async function loadData()", 1)[1].split("async function loadRepairPlan()", 1)[0]

    assert "Promise.allSettled" in load_data_body
    assert "tailMlAuditResult" in load_data_body
    assert "reliabilityReport.value = reliabilityResponse" in load_data_body
    assert "tailMlAudit.value = null" in load_data_body
