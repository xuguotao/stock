export type JobStatus = 'pending' | 'running' | 'success' | 'failed'

export interface JobRecord {
  id: string
  kind: string
  status: JobStatus
  params: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  progress: {
    percent: number
    stage: string
    message: string
  }
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
    minute5_latest_datetime?: string | null
    minute5_symbol_count?: number
  }
  quality?: {
    status: string
    expected_non_st_symbols: number
    daily: {
      latest_date?: string | null
      covered_symbols: number
      missing_symbols: number
      coverage_ratio: number
      status: string
      missing_samples?: Array<{ symbol: string; name: string }>
    }
    minute5: {
      latest_datetime?: string | null
      covered_symbols: number
      missing_symbols: number
      coverage_ratio: number
      status: string
      missing_samples?: Array<{ symbol: string; name: string }>
    }
    issues: string[]
  }
  tables: Record<string, {
    row_count: number
    symbol_count?: number
    date_range?: {
      start: string | null
      end: string | null
    }
  }>
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
}

export interface FundTailReportResponse {
  rows: Record<string, string>[]
  markdown: string
  data_refreshed?: boolean
  data_status?: FundTailDataStatusItem[]
  report_path: string
  markdown_path: string
  report_updated_at?: string | null
  markdown_updated_at?: string | null
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
  note: string
}

export type FundWatchlistPayload = FundWatchlistItem

export interface FundWatchlistResponse {
  items: FundWatchlistItem[]
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
  output_dir: string
}

export interface TailSignalStatsRow {
  group: string
  count: number
  win_count: number
  win_rate: number
  avg_open_return: number
  avg_close_return: number
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
    avg_open_return: number
    avg_close_return: number
    avg_max_return: number
    avg_min_return: number
  }
  selected_overall: {
    count: number
    win_count: number
    win_rate: number
    avg_open_return: number
    avg_close_return: number
    avg_max_return: number
    avg_min_return: number
  }
  by_status: TailSignalStatsRow[]
  by_layer: TailSignalStatsRow[]
  by_filter_reason: TailSignalStatsRow[]
  by_signal_date: Array<{
    date: string
    count: number
    win_count: number
    win_rate: number
    avg_open_return: number
    avg_close_return: number
  }>
  recent: Array<{
    date: string
    count: number
    win_count: number
    win_rate: number
    avg_open_return: number
    avg_close_return: number
  }>
  selected_recent: Array<{
    date: string
    count: number
    win_count: number
    win_rate: number
    avg_open_return: number
    avg_close_return: number
  }>
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
  }
}
