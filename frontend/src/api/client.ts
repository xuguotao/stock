export type JobStatus = 'pending' | 'running' | 'success' | 'failed'

export interface JobRecord {
  id: string
  kind: string
  status: JobStatus
  params: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
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
  min_score?: number | null
  min_market_breadth_above_ma20?: number | null
  dataset_path?: string | null
  symbols?: string[] | null
  sample: boolean
}

export interface BacktestSubmitResponse {
  job_id: string
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
