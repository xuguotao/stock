<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">今日尾盘选股</h1>
      <div class="toolbar">
        <el-button :loading="submitting" type="primary" @click="submit">运行选股</el-button>
        <el-button :disabled="!activeJobId" @click="refreshJob">刷新结果</el-button>
      </div>
    </div>

    <div class="panel">
      <el-form :model="form" label-width="130px">
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="交易日">
              <el-date-picker
                v-model="form.trade_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择交易日"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="股票池">
              <el-select v-model="form.universe">
                <el-option label="本地流动性池" value="liquid-cache" />
                <el-option label="默认池" value="default" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="扫描数量">
              <el-input-number v-model="form.limit" :min="1" :max="500" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Top N">
              <el-input-number v-model="form.top_n" :min="1" :max="50" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="确认次数">
              <el-input-number v-model="form.confirmations" :min="1" :max="10" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最小强度">
              <el-input-number v-model="form.min_strength" :min="0" :max="1" :step="0.05" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="市场宽度阈值">
              <el-input-number
                v-model="form.min_market_breadth_above_ma20"
                :min="0"
                :max="1"
                :step="0.05"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="允许盘外试跑">
              <el-switch v-model="form.ignore_session" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="手动股票">
              <el-select
                v-model="manualSymbols"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="可选，输入 000001 或 000001.SZ"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最少日线数">
              <el-input-number v-model="form.liquidity_min_bars" :min="1" :max="500" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="输出目录">
              <el-input v-model="form.output_dir" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div v-if="job" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">当前任务</div>
          <div class="summary-title">{{ job.id }}</div>
        </div>
        <el-tag :type="statusType(job.status)" effect="plain">{{ job.status }}</el-tag>
        <el-tag v-if="job.error" type="danger" effect="plain">{{ job.error }}</el-tag>
      </div>
      <div class="job-progress-panel">
        <el-progress :percentage="jobProgressPercent" :status="jobProgressStatus" :stroke-width="10" />
        <div class="progress-message">{{ job.progress?.message ?? '-' }}</div>
      </div>
    </div>

    <div v-if="result" class="metric-grid">
      <div class="metric-card" v-for="item in summaryItems" :key="item.label">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
      </div>
    </div>

    <div v-if="diagnostics" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">空结果诊断</div>
          <div class="summary-title">{{ emptyReasonText }}</div>
        </div>
        <el-tag effect="plain">分钟数据 {{ diagnostics.has_intraday_data_count ?? 0 }} / {{ diagnostics.checked_intraday_count ?? 0 }}</el-tag>
        <el-tag effect="plain">候选 {{ diagnostics.candidate_count }}</el-tag>
        <el-tag effect="plain">确认 {{ diagnostics.confirmed_count }}</el-tag>
      </div>
      <div v-if="diagnostics.empty_message" class="diagnostic-message">
        {{ diagnostics.empty_message }}
      </div>
      <div class="diagnostic-tags">
        <el-tag
          v-for="symbol in diagnostics.scan_universe_preview"
          :key="symbol"
          effect="plain"
        >
          {{ symbol }}
        </el-tag>
      </div>
      <div v-if="diagnostics.missing_intraday_symbols?.length" class="diagnostic-message muted">
        缺分钟数据：{{ diagnostics.missing_intraday_symbols.join(', ') }}
      </div>
    </div>

    <div v-if="result" class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">策略排序池</h2>
          <el-tag effect="plain">{{ rankedSignals.length }}</el-tag>
        </div>
        <el-table :data="rankedSignals" height="420">
          <el-table-column prop="rank" label="排名" width="72" />
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row.status === 'selected' ? 'success' : 'info'" effect="plain">
                {{ row.status === 'selected' ? '入选' : '过滤' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="强度" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.strength) }}</template>
          </el-table-column>
          <el-table-column label="量比" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column label="过滤原因" min-width="150">
            <template #default="{ row }">{{ filterReasonText(row.filter_reason) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">最终选股</h2>
          <el-tag effect="plain">{{ selections.length }}</el-tag>
        </div>
        <el-table :data="selections" height="420">
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="强度" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.strength) }}</template>
          </el-table-column>
          <el-table-column label="最新价" width="110" align="right">
            <template #default="{ row }">{{ formatPrice(row.last_price) }}</template>
          </el-table-column>
          <el-table-column label="量比" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">输出文件</h2>
          <el-tag effect="plain">{{ result.trade_date }}</el-tag>
        </div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="JSON">{{ result.files?.json ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="CSV">{{ result.files?.csv ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="日报">{{ result.files?.report ?? '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type JobRecord, type JobStatus, type TailLiveSelectionPayload } from '../api/client'

interface SelectionRow {
  rank?: number
  symbol: string
  trade_date: string
  strength: number
  last_price: number
  volume_ratio: number
  tail_return: number
  reason: string
  status?: 'selected' | 'filtered'
  filter_reason?: string | null
}

interface TailLiveResult {
  trade_date: string
  scanned_count: number
  candidate_count: number
  confirmed_count: number
  selected_count: number
  selections: SelectionRow[]
  ranked_signals?: SelectionRow[]
  files: Record<string, string>
  market_breadth: { breadth: number; above_count: number; symbol_count: number } | null
  diagnostics?: {
    empty_reason: string | null
    empty_message: string | null
    scan_universe_preview: string[]
    has_intraday_data_count: number
    checked_intraday_count: number
    missing_intraday_symbols: string[]
    candidate_count: number
    confirmed_count: number
    selected_count: number
    blocked_by_market_breadth: boolean
  }
}

const props = defineProps<{
  jobId?: string
}>()

const today = new Date().toISOString().slice(0, 10)
const form = ref<TailLiveSelectionPayload>({
  trade_date: today,
  symbols: null,
  limit: 50,
  universe: 'liquid-cache',
  bars_cache_dir: 'data/cache/bars',
  liquidity_min_bars: 120,
  min_market_breadth_above_ma20: null,
  confirmations: 1,
  top_n: 5,
  min_strength: null,
  ignore_session: true,
  output_dir: 'reports/tail_session'
})

const manualSymbols = ref<string[]>([])
const submitting = ref(false)
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const result = computed(() => (job.value?.result ?? null) as unknown as TailLiveResult | null)
const selections = computed(() => result.value?.selections ?? [])
const rankedSignals = computed(() => result.value?.ranked_signals ?? [])
const diagnostics = computed(() => result.value?.diagnostics ?? null)
const emptyReasonText = computed(() => {
  const reason = diagnostics.value?.empty_reason
  if (!reason) return selections.value.length ? '已选出信号' : '未发现异常'
  if (reason === 'scan_universe_empty') return '股票池为空'
  if (reason === 'blocked_by_market_breadth') return '市场宽度拦截'
  if (reason === 'no_intraday_candidates') return '没有尾盘候选信号'
  if (reason === 'no_confirmed_signals') return '候选未连续确认'
  if (reason === 'filtered_by_selection_rules') return '被强度/Top N 过滤'
  return reason
})
const jobProgressPercent = computed(() => Math.max(0, Math.min(100, Number(job.value?.progress?.percent ?? 0))))
const jobProgressStatus = computed(() => {
  if (job.value?.status === 'success') return 'success'
  if (job.value?.status === 'failed') return 'exception'
  return undefined
})
const summaryItems = computed(() => [
  { label: '扫描数', value: String(result.value?.scanned_count ?? '-') },
  { label: '候选数', value: String(result.value?.candidate_count ?? '-') },
  { label: '确认数', value: String(result.value?.confirmed_count ?? '-') },
  { label: '最终选股', value: String(result.value?.selected_count ?? '-') },
  { label: '市场宽度', value: result.value?.market_breadth ? formatPercent(result.value.market_breadth.breadth) : '-' },
  { label: '交易日', value: result.value?.trade_date ?? '-' }
])

async function submit() {
  submitting.value = true
  try {
    const response = await api.submitTailLiveSelection({
      ...form.value,
      symbols: manualSymbols.value.length ? manualSymbols.value : null
    })
    activeJobId.value = response.job_id
    const completed = await pollJobUntilDone(response.job_id)
    if (completed) ElMessage.success('今日尾盘选股完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
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
  for (let attempt = 0; attempt < 120; attempt += 1) {
    job.value = await api.getJob(jobId)
    if (job.value.status === 'success') return true
    if (job.value.status === 'failed') {
      ElMessage.error(job.value.error ?? '今日尾盘选股失败')
      return false
    }
    await sleep(500)
  }
  ElMessage.warning('任务仍在运行，请稍后刷新')
  return false
}

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function formatScore(value: unknown) {
  return typeof value === 'number' ? value.toFixed(4) : '-'
}

function formatPrice(value: unknown) {
  return typeof value === 'number' ? value.toFixed(2) : '-'
}

function formatPercent(value: unknown) {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-'
}

function filterReasonText(value: unknown) {
  if (value === 'below_min_strength') return '低于最小强度'
  if (value === 'outside_top_n') return '排名超出 Top N'
  if (value === 'not_selected') return '未入选'
  return '-'
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

watch(
  () => props.jobId,
  (jobId) => {
    if (jobId) void loadJob(jobId)
  },
  { immediate: true }
)
</script>
