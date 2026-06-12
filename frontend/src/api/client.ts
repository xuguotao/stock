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
  report_path: string
  markdown_path: string
}

export interface FundTailAdvicePayload {
  trade_date: string
  fund_codes?: string[] | null
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
  listFundTailUniverse() {
    return request<FundTailUniverseResponse>('/api/fund-tail/universe')
  },
  getFundTailReport() {
    return request<FundTailReportResponse>('/api/fund-tail/report')
  },
  submitFundTailAdvice(payload: FundTailAdvicePayload) {
    return request<BacktestSubmitResponse>('/api/fund-tail/advice', {
      method: 'POST',
      body: JSON.stringify(payload)
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
  }
}
