<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">尾盘时段回放回测</h1>
      <div class="toolbar">
        <el-button :loading="submitting" type="primary" @click="submit">运行回放</el-button>
        <el-button :disabled="!activeJobId" @click="refreshJob">刷新结果</el-button>
      </div>
    </div>

    <div class="panel">
      <el-form :model="form" label-width="130px">
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="开始日期">
              <el-date-picker v-model="form.start" type="date" value-format="YYYY-MM-DD" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="结束日期">
              <el-date-picker v-model="form.end" type="date" value-format="YYYY-MM-DD" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="股票池">
              <el-select v-model="form.universe">
                <el-option label="全市场非ST" value="default" />
                <el-option label="流动性排序池" value="liquid-cache" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="扫描数量">
              <el-input-number v-model="form.limit" :min="0" :max="6000" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="Top N">
              <el-input-number v-model="form.top_n" :min="1" :max="50" />
            </el-form-item>
          </el-col>
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
            <el-form-item label="最少日线数">
              <el-input-number v-model="form.liquidity_min_bars" :min="1" :max="500" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="回放时间点">
              <el-select v-model="form.cutoff_times" multiple collapse-tags collapse-tags-tooltip>
                <el-option v-for="item in cutoffOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
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

    <div v-if="summary" class="metric-grid">
      <div class="metric-card" v-for="item in summaryItems" :key="item.label">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
      </div>
    </div>

    <div v-if="strategyRecommendation" class="panel compact-panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">策略建议</h2>
        <el-tag type="warning" effect="plain">样本统计</el-tag>
      </div>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="建议时间点">
          {{ strategyRecommendation.best_cutoff_time ?? '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="原因">
          {{ strategyRecommendation.best_cutoff_reason ?? '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="最佳组合">
          {{ bestPlanText }}
        </el-descriptions-item>
        <el-descriptions-item label="组合原因">
          {{ strategyRecommendation.best_plan_reason ?? '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="风险">
          {{ strategyRecommendation.risk_note ?? '-' }}
        </el-descriptions-item>
      </el-descriptions>
      <div class="diagnostic-tags">
        <el-tag
          v-for="item in strategyRecommendation.recommended_filters ?? []"
          :key="String(item.factor)"
          effect="plain"
        >
          {{ item.factor }}：{{ item.reason }}
        </el-tag>
      </div>
    </div>

    <div v-if="result" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">时间点收益对比</h2>
        <el-tag effect="plain">{{ byCutoff.length }}</el-tag>
      </div>
      <el-table :data="byCutoff" height="320" empty-text="暂无回放结果">
        <el-table-column prop="cutoff_time" label="时间点" width="100" />
        <el-table-column prop="run_count" label="运行" width="90" align="right" />
        <el-table-column prop="selected_count" label="入选" width="90" align="right" />
        <el-table-column label="平均入选" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.avg_selected_per_run) }}</template>
        </el-table-column>
        <el-table-column label="开盘胜率" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.win_rate_open) }}</template>
        </el-table-column>
        <el-table-column label="收盘胜率" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.win_rate_close) }}</template>
        </el-table-column>
        <el-table-column label="开盘收益" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
        </el-table-column>
        <el-table-column label="收盘收益" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
        </el-table-column>
        <el-table-column label="策略卖出收益" width="130" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_policy_return) }}</template>
        </el-table-column>
        <el-table-column label="策略胜率" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.win_rate_policy) }}</template>
        </el-table-column>
        <el-table-column label="最大冲高" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_max_return) }}</template>
        </el-table-column>
        <el-table-column label="最大回撤" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_min_return) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="optimizationGrid.length" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">参数组合优化</h2>
        <el-tag effect="plain">{{ optimizationGrid.length }}</el-tag>
      </div>
      <el-table :data="optimizationGrid" height="300" empty-text="暂无可优化样本">
        <el-table-column prop="cutoff_time" label="时间点" width="100" />
        <el-table-column prop="top_n" label="Top N" width="90" align="right" />
        <el-table-column prop="sample_count" label="样本" width="90" align="right" />
        <el-table-column label="策略收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_policy_return) }}</template>
        </el-table-column>
        <el-table-column label="策略胜率" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.win_rate_policy) }}</template>
        </el-table-column>
        <el-table-column label="收盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
        </el-table-column>
        <el-table-column label="最大亏损" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.max_loss) }}</template>
        </el-table-column>
        <el-table-column label="综合分" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.score) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="result" class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">因子诊断</h2>
          <el-tag effect="plain">{{ factorDiagnostics.length }}</el-tag>
        </div>
        <el-table :data="factorDiagnostics" height="300" empty-text="暂无因子样本">
          <el-table-column prop="factor" label="因子" min-width="150" />
          <el-table-column prop="sample_count" label="样本" width="90" align="right" />
          <el-table-column label="高分组收益" width="130" align="right">
            <template #default="{ row }">{{ formatPercent(row.top_avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="低分组收益" width="130" align="right">
            <template #default="{ row }">{{ formatPercent(row.bottom_avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="收益差" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.spread) }}</template>
          </el-table-column>
          <el-table-column prop="interpretation" label="判断" min-width="140" />
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">单票回放明细</h2>
          <el-tag effect="plain">{{ details.length }}</el-tag>
        </div>
        <el-table :data="details" height="300" empty-text="暂无入选明细">
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column prop="cutoff_time" label="时间" width="80" />
          <el-table-column label="股票" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
            </template>
          </el-table-column>
          <el-table-column label="强度" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.strength) }}</template>
          </el-table-column>
          <el-table-column label="量比" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column label="次日开盘" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.outcome?.open_return) }}</template>
          </el-table-column>
          <el-table-column label="次日收盘" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.outcome?.close_return) }}</template>
          </el-table-column>
          <el-table-column label="策略卖出收益" width="130" align="right">
            <template #default="{ row }">{{ formatPercent(row.outcome?.policy_return) }}</template>
          </el-table-column>
          <el-table-column label="卖出原因" width="130">
            <template #default="{ row }">{{ policyExitText(row.outcome?.policy_exit) }}</template>
          </el-table-column>
          <el-table-column label="最大冲高" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.outcome?.max_return) }}</template>
          </el-table-column>
          <el-table-column label="最大回撤" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.outcome?.min_return) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type JobRecord, type JobStatus, type TailReplayBacktestPayload } from '../api/client'

const props = defineProps<{ jobId?: string }>()

const cutoffOptions = ['14:30', '14:35', '14:40', '14:45', '14:50', '14:55']
const form = ref<TailReplayBacktestPayload>({
  start: defaultStartDate(),
  end: defaultEndDate(),
  cutoff_times: [...cutoffOptions],
  limit: 0,
  universe: 'default',
  top_n: 2,
  min_strength: null,
  confirmations: 1,
  preview_window_bars: 6,
  liquidity_min_bars: 60,
  output_dir: 'reports/tail_session/replay'
})
const manualSymbols = ref<string[]>([])
const activeJobId = ref(props.jobId || '')
const job = ref<JobRecord | null>(null)
const submitting = ref(false)
let pollTimer: number | undefined

const result = computed(() => job.value?.result as ReplayResult | null)
const summary = computed(() => result.value?.summary ?? null)
const byCutoff = computed(() => result.value?.by_cutoff ?? [])
const factorDiagnostics = computed(() => result.value?.factor_diagnostics ?? [])
const details = computed(() => result.value?.details ?? [])
const optimizationGrid = computed(() => result.value?.optimization_grid ?? [])
const strategyRecommendation = computed(() => result.value?.strategy_recommendation ?? null)
const bestPlanText = computed(() => {
  const plan = strategyRecommendation.value?.best_plan
  if (!plan) return '-'
  return `${plan.cutoff_time ?? '-'} / Top ${plan.top_n ?? '-'}`
})
const jobProgressPercent = computed(() => Math.max(0, Math.min(100, Number(job.value?.progress?.percent ?? 0))))
const jobProgressStatus = computed(() => job.value?.status === 'failed' ? 'exception' : job.value?.status === 'success' ? 'success' : undefined)
const summaryItems = computed(() => [
  { label: '运行次数', value: String(summary.value?.total_runs ?? 0) },
  { label: '入选样本', value: String(summary.value?.total_selected ?? 0) },
  { label: '可复核样本', value: String(summary.value?.outcome_count ?? 0) },
  { label: '开盘胜率', value: formatPercent(summary.value?.win_rate_open) },
  { label: '收盘胜率', value: formatPercent(summary.value?.win_rate_close) },
  { label: '平均收盘收益', value: formatPercent(summary.value?.avg_close_return) },
  { label: '策略卖出收益', value: formatPercent(summary.value?.avg_policy_return) },
  { label: '策略胜率', value: formatPercent(summary.value?.win_rate_policy) },
  { label: '平均最大冲高', value: formatPercent(summary.value?.avg_max_return) },
  { label: '最大亏损', value: formatPercent(summary.value?.max_loss) }
])

onMounted(() => {
  if (activeJobId.value) refreshJob()
})

onUnmounted(() => {
  stopPolling()
})

watch(() => props.jobId, (value) => {
  if (value) {
    activeJobId.value = value
    refreshJob()
  }
})

async function submit() {
  if (!form.value.start || !form.value.end) {
    ElMessage.error('请选择回测日期范围')
    return
  }
  if (!form.value.cutoff_times.length) {
    ElMessage.error('至少选择一个回放时间点')
    return
  }
  submitting.value = true
  try {
    const payload = {
      ...form.value,
      symbols: manualSymbols.value.length ? manualSymbols.value : null
    }
    const response = await api.submitTailReplayBacktest(payload)
    activeJobId.value = response.job_id
    await refreshJob()
    startPolling()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
  if (job.value.status === 'running' || job.value.status === 'pending') {
    startPolling()
  } else {
    stopPolling()
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(refreshJob, 2000)
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function openStockTrend(symbol: string) {
  if (!symbol) return
  window.open(`/stock-trend/${encodeURIComponent(symbol)}`, '_blank')
}

function statusType(status: JobStatus) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function formatPercent(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${(number * 100).toFixed(2)}%`
}

function formatNumber(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(4)
}

function policyExitText(value: unknown) {
  const key = String(value || '')
  const map: Record<string, string> = {
    take_profit: '触发止盈',
    gap_take_profit: '高开止盈',
    stop_loss: '触发止损',
    gap_stop: '低开止损',
    ambiguous_stop_first: '同K保守止损',
    close: '收盘卖出',
    missing: '缺数据'
  }
  return map[key] ?? '-'
}

function defaultEndDate() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  return d.toISOString().slice(0, 10)
}

function defaultStartDate() {
  const d = new Date()
  d.setDate(d.getDate() - 15)
  return d.toISOString().slice(0, 10)
}

interface ReplayResult {
  summary: Record<string, number | null>
  by_cutoff: Array<Record<string, unknown>>
  factor_diagnostics: Array<Record<string, unknown>>
  optimization_grid?: Array<Record<string, unknown>>
  strategy_recommendation?: StrategyRecommendation
  details: Array<Record<string, unknown>>
}

interface StrategyRecommendation {
  best_cutoff_time?: string | null
  best_cutoff_reason?: string | null
  best_plan?: Record<string, unknown> | null
  best_plan_reason?: string | null
  risk_note?: string | null
  recommended_filters?: Array<Record<string, unknown>>
}
</script>
