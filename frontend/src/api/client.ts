export type JobStatus = 'pending' | 'running' | 'success' | 'failed'

export interface JobRecord {
  id: string
  kind: string
  status: JobStatus
  health: 'pending' | 'running' | 'stale' | 'completed' | 'failed' | string
  params: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  progress: {
    percent: number
    stage: string
    message: string
  }
  heartbeat_at: string | null
  created_at: string
  updated_at: string
}

export interface JobsResponse {
  items: JobRecord[]
}

export interface TailBacktestPayload {
  start: string
  end: string
  capital: number
  top_n: number
  hold_days: number
  min_score?: number | null
  min_market_breadth_above_ma20?: number | null
  dataset_id?: string | null
  dataset_path?: string | null
  symbols?: string[] | null
  sample: boolean
  source?: 'clickhouse' | 'dataset'
}

export interface TailReplayBacktestPayload {
  start: string
  end: string
  cutoff_times: string[]
  symbols?: string[] | null
  limit?: number
  universe?: 'default' | 'liquid-cache'
  top_n?: number
  min_strength?: number | null
  confirmations?: number
  preview_window_bars?: number
  min_market_breadth_above_ma20?: number | null
  liquidity_min_bars?: number
  output_dir?: string
}

export interface BacktestSubmitResponse {
  job_id: string
}

export interface DatasetSummary {
  id: string
  name: string
  path: string
  manifest_path: string | null
  row_count: number
  symbol_count: number
  start: string | null
  end: string | null
  built_at: string | null
  size_bytes: number
}

export interface DatasetDetail extends DatasetSummary {
  symbols: string[]
}

export interface DatasetsResponse {
  items: DatasetSummary[]
}

export interface DataStatusResponse {
  database: {
    type?: string
    path?: string
    host?: string
    database?: string
    exists: boolean
    size_bytes: number
  }
  stock_summary: {
    stock_count: number
    non_st_stock_count: number
    st_stock_count: number
  }
  health: {
    status: string
    daily_latest_date?: string | null
    daily_symbol_count?: number
    minute1_latest_datetime?: string | null
    minute1_symbol_count?: number
    minute5_latest_datetime?: string | null
    minute5_symbol_count?: number
    quote_snapshot_latest_datetime?: string | null
    quote_snapshot_symbol_count?: number
  }
  quality?: {
    status: string
    expected_non_st_symbols: number
    expected_strategy_tradable_symbols?: number
    daily: {
      latest_date?: string | null
      covered_symbols: number
      missing_symbols: number
      coverage_ratio: number
      expected_symbols?: number
      status: string
      missing_samples?: Array<{ symbol: string; name: string }>
    }
    minute5: {
      latest_datetime?: string | null
      covered_symbols: number
      missing_symbols: number
      coverage_ratio: number
      current_latest_datetime?: string | null
      current_covered_symbols?: number
      current_coverage_ratio?: number
      expected_symbols?: number
      duplicate_groups?: number
      extra_rows?: number
      status: string
      missing_samples?: Array<{ symbol: string; name: string }>
    }
    quote_snapshots?: {
      status: string
      expected_symbols: number
      expected_interval_seconds: number
      raw_retention_days: number
      aggregate_retention_days: number
      raw: {
        table: string
        latest_datetime?: string | null
        row_count: number
        symbol_count: number
        latest_symbol_count: number
        missing_symbols: number
        coverage_ratio: number
        retention_days: number
        expected_interval_seconds: number
        observed_rounds: number
        expected_rounds: number
        missing_rounds: number
        missing_rate: number
        actual_avg_interval_seconds?: number | null
        recent_windows?: Record<string, {
          observed_rounds: number
          expected_rounds: number
          missing_rounds: number
          missing_rate: number
          actual_avg_interval_seconds?: number | null
        }>
        status: string
      }
      rollups: Record<string, {
        table: string
        latest_bucket?: string | null
        row_count: number
        symbol_count: number
        latest_symbol_count: number
        missing_symbols: number
        coverage_ratio: number
        retention_days: number
        bucket_seconds: number
        status: string
      }>
      issues: string[]
    }
    scheduled_checks?: {
      status: string
      completeness_30d: {
        status: string
        window_days: number
        min_required_days: number
        affected_symbols: number
        samples: Array<{ symbol: string; name: string; data_days: number }>
      }
      today_anomalies: {
        status: string
        latest_date?: string | null
        bad_rows: number
        samples: Array<{
          symbol: string
          date: string
          open: number
          high: number
          low: number
          close: number
          volume: number
        }>
      }
      historical_invalid_prices?: {
        status: string
        bad_rows: number
        affected_symbols: number
        start_date?: string | null
        end_date?: string | null
        samples: Array<{
          symbol: string
          name: string
          bad_rows: number
          start_date?: string | null
          end_date?: string | null
        }>
      }
      freshness: {
        status: string
        latest_date?: string | null
        as_of_date: string
        lag_days?: number | null
        expected_latest_date?: string | null
        trading_lag_days?: number | null
        max_lag_days: number
      }
      issues: string[]
      ignored_issues?: string[]
    }
    issues: string[]
    ignored_issues?: string[]
  }
  datasets_health?: Array<{
    key: string
    name: string
    category: string
    table: string
    source: string
    update_mechanism: string
    consumer: string
    latest?: string | null
    range?: {
      start: string | null
      end: string | null
    } | null
    rows: number
    symbols: number
    expected_symbols?: number | null
    coverage_ratio?: number | null
    status: string
    issues: string[]
  }>
  tables: Record<string, {
    row_count: number
    symbol_count?: number
    date_range?: {
      start: string | null
      end: string | null
    }
  }>
}

export interface DataHealthRepairAction {
  key: string
  title: string
  status: string
  auto_repair: boolean
  reason: string
  trade_date?: string | null
  symbols?: string[]
  samples?: Array<Record<string, unknown>>
  runner?: string | null
}

export interface DataHealthRepairPlan {
  status: string
  summary: {
    quality_status: string
    issue_count: number
    auto_repair_count: number
    manual_count: number
  }
  issues: string[]
  actions: DataHealthRepairAction[]
}

export interface DataHealthRepairPayload {
  action_keys?: string[] | null
}

export interface DataReliabilityRow {
  key: string
  name: string
  source: string
  update_mechanism: string
  automation: string
  health: string
  latest?: string | null
  coverage: string
  repair: string
  issues: string[]
}

export interface DataReliabilityReport {
  status: string
  summary: {
    rows: number
    warning_rows: number
    automation_gaps: number
    auto_repair_count: number
    manual_count: number
  }
  rows: DataReliabilityRow[]
  data_status: DataStatusResponse
  repair_plan: DataHealthRepairPlan
}

export interface TailMlAuditResponse {
  status: string
  as_of: string
  summary: {
    daily_rows: number
    daily_symbols: number
    minute5_rows: number
    minute5_symbols: number
    minute5_usable_days: number
    joinable_label_days: number
    tradable_pool: number
  }
  stocks?: Record<string, number>
  daily: {
    status: string
    start?: string | null
    end?: string | null
    symbol_count: number
    row_count: number
    invalid_ohlc_rows: number
  }
  minute5: {
    status: string
    start?: string | null
    end?: string | null
    symbol_count: number
    row_count: number
    usable_days: number
    minimum_usable_days: number
  }
  snapshots: {
    status: string
    start?: string | null
    latest_datetime?: string | null
    symbol_count: number
    row_count: number
    training_role: string
  }
  strategy_signals: {
    status: string
    start?: string | null
    end?: string | null
    row_count: number
    signal_days: number
    selected_rows: number
    symbol_count: number
    outcome_rows: number
    training_role: string
  }
  labels: {
    status: string
    start?: string | null
    end?: string | null
    outcome_rows: number
    outcome_days: number
    symbol_count: number
    joinable_days: number
    minimum_joinable_days: number
  }
  tradable_pool: {
    status: string
    symbol_count: number
  }
  issues: string[]
}

export interface TailMlModelManifest {
  version: string
  status: string
  reason?: string | null
  created_at?: string
  artifact_dir?: string
  sample_count?: number
  fold_count?: number
  top_n?: number
  sample_window?: {
    start?: string | null
    end?: string | null
  }
  training_config?: {
    train_days?: number
    validation_days?: number
    top_n?: number
  }
  feature_importance?: Array<{
    feature: string
    importance: number
  }>
  feature_columns?: string[]
  metrics?: Record<string, number | string | null>
  promotion_decision?: {
    eligible: boolean
    status: string
    reasons: string[]
  }
  baseline_metrics?: Record<string, number | string | null>
}

export interface TailMlModelsResponse {
  model_root: string
  items: TailMlModelManifest[]
}

export interface TailMlTrainPayload {
  start: string
  end: string
  version?: string
  train_days?: number
  validation_days?: number
  top_n?: number
  symbols?: string[]
}

export interface StockDbSyncPayload {
  remote?: string
  backup?: boolean
}

export interface Minute5SyncPayload {
  trade_date: string
  limit?: number
  symbols?: string[] | null
  include_st?: boolean
}

export interface Minute5MonitorPayload {
  trade_date?: string | null
  interval_seconds?: number
  limit?: number
  include_st?: boolean
}

export interface Minute5MonitorStatus {
  running: boolean
  mode: string
  config: {
    trade_date: string | null
    interval_seconds: number | null
    limit: number | null
    include_st: boolean | null
    max_fetch_symbols: number | null
  }
  session: {
    open: boolean
    reason: string
    message: string
  }
  started_count: number
  cycle_count: number
  skip_count: number
  next_run_at: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_progress: { percent: number; stage: string; message: string } | null
  last_result: Record<string, unknown> | null
  last_error: string | null
}

export interface QuoteSnapshotMonitorStatus {
  running: boolean
  mode: string
  config: {
    interval_seconds: number | null
    limit: number | null
    include_st: boolean | null
    chunk_size: number | null
    timeout_seconds: number | null
    min_chunk_size: number | null
    max_chunk_size: number | null
  }
  session: {
    open: boolean
    reason: string
    message: string
  }
  cycle_count: number
  skip_count: number
  failure_count: number
  timeout_count: number
  effective_chunk_size: number | null
  last_cycle_duration_seconds: number | null
  next_run_at: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_progress: { percent: number; stage: string; message: string } | null
  last_result: Record<string, unknown> | null
  last_error: string | null
}

export interface QuoteSnapshotMonitorPayload {
  interval_seconds?: number
  limit?: number
  include_st?: boolean
  chunk_size?: number
  timeout_seconds?: number
}

export interface DataOpsSchedulerStatus {
  running: boolean
  phase: string
  config: {
    interval_seconds: number
    post_close_time: string
  }
  tasks: {
    post_close_maintenance: {
      enabled: boolean
      phase: string
      last_run_date: string | null
    }
  }
  cycle_count: number
  skip_count: number
  maintenance_count: number
  next_run_at: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_result: Record<string, unknown> | null
  last_error: string | null
}

export interface DailyMaintenancePayload {
  trade_date?: string | null
  retry_no_data?: boolean
  run_strategy_review?: boolean
  strategy_limit?: number
  strategy_top_n?: number
}

export interface BuildClickHouseDatasetPayload {
  start: string
  end: string
  name?: string
  symbols?: string[] | null
  limit?: number
}

export interface FundTailUniverseItem {
  code: string
  name: string
  proxy_provider: string
  proxy_code: string
  has_nav: boolean
  has_proxy: boolean
  latest_nav_date: string | null
  latest_proxy_date: string | null
}

export interface FundTailUniverseResponse {
  items: FundTailUniverseItem[]
  status?: string
  error?: string
}

export interface FundTailProxyRefreshResponse {
  proxy_refresh: Record<string, unknown> | null
  items: FundWatchlistItem[]
  universe: FundTailUniverseItem[]
}

export interface FundTailReportResponse {
  rows: Record<string, string>[]
  markdown: string
  data_refreshed?: boolean
  proxy_refresh?: Record<string, unknown> | null
  data_status?: FundTailDataStatusItem[]
  report_path: string
  markdown_path: string
  report_updated_at?: string | null
  markdown_updated_at?: string | null
  status?: string
  error?: string
}

export interface FundTailDataStatusItem {
  code: string
  name: string
  has_nav: boolean
  has_proxy: boolean
  latest_nav_date: string | null
  latest_proxy_date: string | null
}

export interface FundTailAdvicePayload {
  trade_date: string
  fund_codes?: string[] | null
  refresh_data?: boolean
  download_start_date?: string
}

export interface FundTailOpportunityPayload {
  trade_date: string
}

export interface FundTailOpportunityResponse {
  rows: Record<string, string>[]
  markdown: string
  report_path: string
  markdown_path: string
  report_updated_at?: string | null
  markdown_updated_at?: string | null
}

export type FundWatchlistStatus = 'holding' | 'candidate' | 'watching' | 'paused'
export type FundWatchlistPriority = 'core' | 'normal' | 'low'
export type FundWatchlistType = 'broad_index' | 'consumer' | 'medical' | 'overseas' | 'bond' | 'sector' | 'other'

export interface FundWatchlistItem {
  fund_code: string
  fund_name: string
  status: FundWatchlistStatus
  priority: FundWatchlistPriority
  fund_type: FundWatchlistType
  enabled: boolean
  include_in_advice: boolean
  position_cost: number | null
  position_amount: number | null
  position_return_pct: number | null
  latest_nav_date?: string | null
  latest_nav?: number | null
  latest_proxy_date?: string | null
  latest_proxy_close?: number | null
  proxy_return_pct?: number | null
  estimated_change_pct?: number | null
  note: string
}

export type FundWatchlistPayload = FundWatchlistItem

export interface FundWatchlistResponse {
  items: FundWatchlistItem[]
  status?: string
  error?: string
}

export interface FundWatchlistItemResponse {
  item: FundWatchlistItem
}

export interface TailLiveSelectionPayload {
  trade_date: string
  symbols?: string[] | null
  limit: number
  universe: 'default' | 'liquid-cache'
  bars_cache_dir: string
  liquidity_min_bars: number
  min_market_breadth_above_ma20?: number | null
  confirmations: number
  top_n: number
  min_strength?: number | null
  ignore_session: boolean
  auto_sync_minute5?: boolean
  data_refresh_mode?: 'auto' | 'snapshot' | 'standard_minute5' | 'none'
  strategy_mode?: 'rule' | 'model' | 'hybrid'
  output_dir: string
}

export interface TailSignalStatsRow {
  group: string
  count: number
  win_count: number
  win_rate: number
  open_win_count?: number
  open_win_rate?: number
  max_win_count?: number
  max_win_rate?: number
  avg_open_return: number
  avg_close_return: number
  avg_max_return?: number
  avg_min_return?: number
}

export interface TailSignalStatsResponse {
  range: {
    start: string
    end: string
  }
  overall: {
    count: number
    win_count: number
    win_rate: number
    open_win_count?: number
    open_win_rate?: number
    max_win_count?: number
    max_win_rate?: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return: number
    avg_min_return: number
    payoff_ratio?: number
  }
  selected_overall: {
    count: number
    win_count: number
    win_rate: number
    open_win_count?: number
    open_win_rate?: number
    max_win_count?: number
    max_win_rate?: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return: number
    avg_min_return: number
    payoff_ratio?: number
  }
  execution_summary?: {
    sample_count: number
    open_win_rate: number
    close_win_rate: number
    max_win_rate: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return: number
    avg_min_return: number
    payoff_ratio: number
  }
  tracking_summary?: {
    total: number
    completed: number
    live_tracking: number
    pending_outcome: number
  }
  review_plan?: {
    pending_dates: Array<{
      signal_date: string
      selected_count: number
      outcome_count: number
      missing_count: number
    }>
    pending_date_count: number
    pending_signal_count: number
  }
  by_status: TailSignalStatsRow[]
  by_mode?: TailSignalStatsRow[]
  by_layer: TailSignalStatsRow[]
  by_confidence?: TailSignalStatsRow[]
  by_volume_ratio?: TailSignalStatsRow[]
  by_tail_return?: TailSignalStatsRow[]
  by_filter_reason: TailSignalStatsRow[]
  by_signal_date: Array<{
    date: string
    count: number
    win_count: number
    win_rate: number
    open_win_rate?: number
    max_win_rate?: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return?: number
    avg_min_return?: number
  }>
  recent: Array<{
    date: string
    count: number
    win_count: number
    win_rate: number
    open_win_rate?: number
    max_win_rate?: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return?: number
    avg_min_return?: number
  }>
  selected_recent: Array<{
    date: string
    count: number
    win_count: number
    win_rate: number
    open_win_rate?: number
    max_win_rate?: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return?: number
    avg_min_return?: number
  }>
  details?: Array<{
    trade_date: string
    outcome_date: string | null
    symbol: string
    mode: string
    rank: number
    status: string
    review_status: string
    filter_reason: string
    v2_layer: string
    v2_action: string
    strength: number | null
    v2_score: number | null
    volume_ratio: number | null
    tail_return: number | null
    confidence_bucket?: string
    execution_label?: string
    risk_label?: string
    signal_close: number
    next_open: number
    next_high: number
    next_low: number
    next_close: number
    open_return: number
    close_return: number
    max_return: number
    min_return: number
    current_price: number
    current_return: number
    latest_snapshot_at: string | null
  }>
}

export interface TailSignalOutcomeReviewResponse {
  mode?: 'single_date' | 'pending'
  signal_date?: string
  start?: string
  end?: string
  date_count?: number
  outcome_count: number
  missing_symbols: string[]
  dates?: Array<{
    signal_date: string
    outcome_count: number
    missing_symbols: string[]
  }>
}

export interface TailSignalOutcomeReviewPayload {
  mode?: 'single_date' | 'pending'
  signal_date?: string | null
  start?: string | null
  end?: string | null
}

export interface StockTrendResponse {
  symbol: string
  name: string
  trade_date: string
  granularity: string
  latest_price: number | null
  latest_intraday_time: string | null
  quote?: Record<string, number | string | null>
  metrics: Record<string, number | null>
  tail_evidence?: Record<string, number | string | null>
  daily: Array<Record<string, number | string | null>>
  intraday: Array<Record<string, number | string | null>>
}

export type WatchlistStatus =
  | 'hot_wait'
  | 'watch_pullback'
  | 'entry_zone'
  | 'add_zone'
  | 'breakout_confirm'
  | 'risk_off'
  | 'neutral'

export interface WatchlistLevels {
  observe: number[]
  entry: number[]
  add: number[]
  invalid: number
  breakout: number | null
}

export interface WatchlistMonitorItem {
  symbol: string
  name: string
  theme: string
  notes: string
  latest_price: number | null
  daily_change_pct: number | null
  return_5d: number | null
  return_20d: number | null
  ma5: number | null
  ma20: number | null
  volume_ratio: number | null
  status: WatchlistStatus
  reasons: string[]
  levels: WatchlistLevels
  data_status: string
  quote_snapshot_at: string | null
  quote_time: string | null
}

export interface WatchlistMonitorReport {
  trade_date: string
  summary: Record<string, number>
  items: WatchlistMonitorItem[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || response.statusText)
  }
  return response.json() as Promise<T>
}

export const api = {
  listDatasets() {
    return request<DatasetsResponse>('/api/datasets')
  },
  getDataset(datasetId: string) {
    return request<DatasetDetail>(`/api/datasets/${encodeURIComponent(datasetId)}`)
  },
  getDataStatus() {
    return request<DataStatusResponse>('/api/data/status')
  },
  getTailMlAudit() {
    return request<TailMlAuditResponse>('/api/ml/tail/audit')
  },
  getTailMlModels() {
    return request<TailMlModelsResponse>('/api/ml/tail/models')
  },
  trainTailMlModel(payload: TailMlTrainPayload) {
    return request<BacktestSubmitResponse>('/api/ml/tail/train', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  promoteTailMlModel(version: string) {
    return request<TailMlModelManifest>(`/api/ml/tail/models/${encodeURIComponent(version)}/promote`, {
      method: 'POST'
    })
  },
  getStockTrend(symbol: string, tradeDate?: string, dailyWindow = 90, granularity = '5m') {
    const params = new URLSearchParams({ daily_window: String(dailyWindow) })
    if (tradeDate) params.set('trade_date', tradeDate)
    params.set('granularity', granularity)
    return request<StockTrendResponse>(`/api/stocks/${encodeURIComponent(symbol)}/trend?${params.toString()}`)
  },
  getWatchlistMonitorReport(tradeDate?: string) {
    const params = new URLSearchParams()
    if (tradeDate) params.set('trade_date', tradeDate)
    const suffix = params.toString() ? `?${params.toString()}` : ''
    return request<WatchlistMonitorReport>(`/api/watchlist-monitor/report${suffix}`)
  },
  syncStockDb(payload: StockDbSyncPayload = {}) {
    return request<BacktestSubmitResponse>('/api/data/sync-stock-db', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  syncMinute5(payload: Minute5SyncPayload) {
    return request<BacktestSubmitResponse>('/api/data/sync-minute5', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getMinute5Monitor() {
    return request<Minute5MonitorStatus>('/api/data/minute5-monitor')
  },
  startMinute5Monitor(payload: Minute5MonitorPayload) {
    return request<Minute5MonitorStatus>('/api/data/minute5-monitor/start', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  stopMinute5Monitor() {
    return request<Minute5MonitorStatus>('/api/data/minute5-monitor/stop', { method: 'POST' })
  },
  getQuoteSnapshotMonitor() {
    return request<QuoteSnapshotMonitorStatus>('/api/data/quote-snapshot-monitor')
  },
  getDataOpsScheduler() {
    return request<DataOpsSchedulerStatus>('/api/data/ops-scheduler')
  },
  getDataHealthRepairPlan() {
    return request<DataHealthRepairPlan>('/api/data/health-repair-plan')
  },
  getDataReliability() {
    return request<DataReliabilityReport>('/api/data/reliability')
  },
  repairDataHealth(payload: DataHealthRepairPayload = {}) {
    return request<BacktestSubmitResponse>('/api/data/health-repair', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  startDataOpsScheduler() {
    return request<DataOpsSchedulerStatus>('/api/data/ops-scheduler/start', { method: 'POST' })
  },
  stopDataOpsScheduler() {
    return request<DataOpsSchedulerStatus>('/api/data/ops-scheduler/stop', { method: 'POST' })
  },
  runDataOpsSchedulerOnce() {
    return request<DataOpsSchedulerStatus>('/api/data/ops-scheduler/run-once', { method: 'POST' })
  },
  runDailyMaintenance(payload: DailyMaintenancePayload = {}) {
    return request<BacktestSubmitResponse>('/api/data/daily-maintenance', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  buildClickHouseDataset(payload: BuildClickHouseDatasetPayload) {
    return request<BacktestSubmitResponse>('/api/datasets/build-clickhouse', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  listFundTailUniverse() {
    return request<FundTailUniverseResponse>('/api/fund-tail/universe')
  },
  getFundTailReport() {
    return request<FundTailReportResponse>('/api/fund-tail/report')
  },
  getFundTailOpportunities() {
    return request<FundTailOpportunityResponse>('/api/fund-tail/opportunities/latest')
  },
  submitFundTailAdvice(payload: FundTailAdvicePayload) {
    return request<BacktestSubmitResponse>('/api/fund-tail/advice', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  refreshFundTailProxy(payload: { trade_date: string }) {
    return request<FundTailProxyRefreshResponse>('/api/fund-tail/refresh-proxy', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  submitFundTailOpportunities(payload: FundTailOpportunityPayload) {
    return request<BacktestSubmitResponse>('/api/fund-tail/opportunities', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  listFundTailWatchlist() {
    return request<FundWatchlistResponse>('/api/fund-tail/watchlist')
  },
  upsertFundTailWatchlistItem(code: string, payload: FundWatchlistPayload) {
    return request<FundWatchlistItemResponse>(`/api/fund-tail/watchlist/${code}`, {
      method: 'PUT',
      body: JSON.stringify(payload)
    })
  },
  deleteFundTailWatchlistItem(code: string) {
    return request<{ deleted: number }>(`/api/fund-tail/watchlist/${code}`, {
      method: 'DELETE'
    })
  },
  listJobs(limit = 20) {
    return request<JobsResponse>(`/api/jobs?limit=${limit}`)
  },
  getJob(jobId: string) {
    return request<JobRecord>(`/api/jobs/${jobId}`)
  },
  submitTailBacktest(payload: TailBacktestPayload) {
    return request<BacktestSubmitResponse>('/api/backtests/tail-session', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  submitTailReplayBacktest(payload: TailReplayBacktestPayload) {
    return request<BacktestSubmitResponse>('/api/tail-session/replay-backtest', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  submitTailLiveSelection(payload: TailLiveSelectionPayload) {
    return request<BacktestSubmitResponse>('/api/tail-session/live-selection', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getTailSignalStats(start?: string, end?: string) {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    const suffix = params.toString() ? `?${params.toString()}` : ''
    return request<TailSignalStatsResponse>(`/api/tail-session/signal-stats${suffix}`)
  },
  reviewTailSignalOutcomes(payload: TailSignalOutcomeReviewPayload) {
    return request<TailSignalOutcomeReviewResponse>('/api/tail-session/review-outcomes', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  }
}
