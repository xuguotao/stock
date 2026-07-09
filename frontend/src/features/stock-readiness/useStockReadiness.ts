import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type JobRecord, type StockReadinessItem, type StockReadinessResponse, type StockReadinessSummary } from '../../api/client'
import type { ReadinessDimensionKey, StockReadinessFilters } from './types'

const DEFAULT_DIMENSIONS: ReadinessDimensionKey[] = ['daily', 'minute5']
const REPAIR_POLL_INTERVAL_MS = 1500
const REPAIR_MAX_POLLS = 120

export function useStockReadiness() {
  const filters = ref<StockReadinessFilters>({
    range: defaultRange(),
    dimensions: [...DEFAULT_DIMENSIONS],
    status: 'all',
    market: 'all',
    board: 'all',
    q: '',
  })
  const loading = ref(false)
  const repairing = ref(false)
  const generatingSnapshot = ref(false)
  const error = ref('')
  const page = ref(1)
  const pageSize = ref(50)
  const summary = ref<StockReadinessSummary | null>(null)
  const response = ref<StockReadinessResponse | null>(null)
  const activeRepairJob = ref<JobRecord | null>(null)
  const activeSnapshotJob = ref<JobRecord | null>(null)

  const rows = computed<StockReadinessItem[]>(() => response.value?.items ?? [])
  const total = computed(() => response.value?.total ?? 0)
  const repairStatusText = computed(() => {
    const job = activeRepairJob.value
    if (!job) return ''
    if (job.status === 'success') {
      const result = job.result as { attempted_gaps?: number } | null
      return `回补完成，处理缺口 ${result?.attempted_gaps ?? 0} 个`
    }
    if (job.status === 'failed') return job.error || '回补失败'
    return job.progress?.message || '回补任务运行中'
  })
  const snapshotStatusText = computed(() => {
    const job = activeSnapshotJob.value
    if (!job) return ''
    if (job.status === 'success') {
      const result = job.result as { rows?: number; gaps?: number } | null
      return `快照完成，写入 ${result?.rows ?? 0} 条，缺口 ${result?.gaps ?? 0} 条`
    }
    if (job.status === 'failed') return job.error || '快照生成失败'
    return job.progress?.message || '快照任务运行中'
  })

  async function load() {
    loading.value = true
    error.value = ''
    try {
      const params = requestParams()
      const [summaryResult, listResult] = await Promise.all([
        api.getStockReadinessSummary(params),
        api.getStockReadiness({ ...params, page: page.value, page_size: pageSize.value }),
      ])
      summary.value = summaryResult
      response.value = listResult
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载策略数据就绪度失败'
      ElMessage.error(error.value)
    } finally {
      loading.value = false
    }
  }

  async function repair(row: StockReadinessItem) {
    const dimensions = filters.value.dimensions.filter((dimension) => row.dimensions[dimension]?.repairable)
    if (!dimensions.length) return
    repairing.value = true
    try {
      const created = await api.repairStockReadiness({
        symbols: [row.symbol],
        dimensions,
        start: filters.value.range[0],
        end: filters.value.range[1],
      })
      activeRepairJob.value = await pollRepairJob(created.job_id)
      if (activeRepairJob.value.status === 'failed') {
        ElMessage.error(activeRepairJob.value.error || '数据回补失败')
        return
      }
      ElMessage.success('数据回补完成')
      await load()
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '创建回补任务失败')
    } finally {
      repairing.value = false
    }
  }

  async function generateSnapshot() {
    generatingSnapshot.value = true
    try {
      const created = await api.generateStockReadinessSnapshot({
        dimensions: filters.value.dimensions,
        start: filters.value.range[0],
        end: filters.value.range[1],
      })
      activeSnapshotJob.value = await pollReadinessJob(created.job_id, '快照任务仍在运行，请稍后刷新任务状态')
      if (activeSnapshotJob.value.status === 'failed') {
        ElMessage.error(activeSnapshotJob.value.error || '快照生成失败')
        return
      }
      ElMessage.success('当前窗口快照生成完成')
      await load()
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '创建快照任务失败')
    } finally {
      generatingSnapshot.value = false
    }
  }

  function requestParams() {
    return {
      start: filters.value.range[0],
      end: filters.value.range[1],
      dimensions: filters.value.dimensions,
      status: filters.value.status,
      market: filters.value.market,
      board: filters.value.board,
      q: filters.value.q,
    }
  }

  function resetPageAndLoad() {
    page.value = 1
    void load()
  }

  return {
    error,
    activeRepairJob,
    activeSnapshotJob,
    filters,
    generatingSnapshot,
    loading,
    page,
    pageSize,
    repairing,
    response,
    repairStatusText,
    snapshotStatusText,
    rows,
    summary,
    total,
    load,
    generateSnapshot,
    repair,
    resetPageAndLoad,
  }
}

async function pollRepairJob(jobId: string): Promise<JobRecord> {
  return pollReadinessJob(jobId, '回补任务仍在运行，请稍后刷新任务状态')
}

async function pollReadinessJob(jobId: string, timeoutMessage: string): Promise<JobRecord> {
  let latest = await api.getJob(jobId)
  for (let index = 0; index < REPAIR_MAX_POLLS && ['pending', 'running'].includes(latest.status); index += 1) {
    await wait(REPAIR_POLL_INTERVAL_MS)
    latest = await api.getJob(jobId)
  }
  if (['pending', 'running'].includes(latest.status)) {
    throw new Error(timeoutMessage)
  }
  return latest
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function defaultRange(): [string, string] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - 180)
  return [formatDate(start), formatDate(end)]
}

function formatDate(value: Date) {
  return value.toISOString().slice(0, 10)
}
