import { ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type JobRecord, type TailLiveSelectionPayload } from '../../api/client'

const JOB_POLL_INTERVAL_MS = 1000
const JOB_POLL_MAX_ATTEMPTS = 900

export function useTailLiveJob(
  form: Ref<TailLiveSelectionPayload>,
  manualSymbols: Ref<string[]>
) {
  const submitting = ref(false)
  const loadingHistory = ref(false)
  const activeJobId = ref('')
  const job = ref<JobRecord | null>(null)
  const runHistory = ref<JobRecord[]>([])

  async function submit() {
    submitting.value = true
    try {
      const response = await api.submitTailLiveSelection({
        ...form.value,
        symbols: manualSymbols.value.length ? manualSymbols.value : null
      })
      activeJobId.value = response.job_id
      const completed = await pollJobUntilDone(response.job_id)
      await loadRunHistory()
      if (completed) ElMessage.success('今日尾盘选股完成')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '提交失败')
    } finally {
      submitting.value = false
    }
  }

  async function loadRunHistory() {
    loadingHistory.value = true
    try {
      const response = await api.listJobs(100)
      runHistory.value = response.items.filter((item) => item.kind === 'tail_session_live_selection')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '加载运行记录失败')
    } finally {
      loadingHistory.value = false
    }
  }

  async function selectRunHistory(row: JobRecord) {
    await loadJob(row.id)
  }

  async function refreshJob() {
    if (!activeJobId.value) return
    job.value = await api.getJob(activeJobId.value)
  }

  async function loadJob(jobId: string) {
    activeJobId.value = jobId
    await refreshJob()
  }

  async function pollJobUntilDone(jobId: string) {
    for (let attempt = 0; attempt < JOB_POLL_MAX_ATTEMPTS; attempt += 1) {
      job.value = await api.getJob(jobId)
      if (job.value.status === 'success') return true
      if (job.value.status === 'failed') {
        ElMessage.error(job.value.error ?? '今日尾盘选股失败')
        return false
      }
      await sleep(JOB_POLL_INTERVAL_MS)
    }
    job.value = await api.getJob(jobId)
    if (job.value.status === 'success') return true
    ElMessage.warning('任务仍在运行，页面会保留当前任务，可稍后刷新运行记录')
    return false
  }

  return {
    activeJobId,
    job,
    loadingHistory,
    runHistory,
    submitting,
    loadJob,
    loadRunHistory,
    refreshJob,
    selectRunHistory,
    submit,
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}
