<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">尾盘回测</h1>
      <div class="toolbar">
        <el-button :loading="submitting" type="primary" @click="submit">运行</el-button>
        <el-button :disabled="!activeJobId" @click="refreshJob">刷新结果</el-button>
      </div>
    </div>

    <div class="panel">
      <el-form :model="form" label-width="120px">
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="开始日期">
              <el-date-picker
                v-model="form.start"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择开始日期"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="结束日期">
              <el-date-picker
                v-model="form.end"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择结束日期"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="初始资金">
              <el-input-number v-model="form.capital" :min="10000" :step="10000" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Top N">
              <el-input-number v-model="form.top_n" :min="1" :max="20" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="持有交易日">
              <el-input-number v-model="form.hold_days" :min="1" :max="20" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最小分数">
              <el-input-number v-model="form.min_score" :step="0.1" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="样例数据">
              <el-switch v-model="form.sample" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="股票池">
              <el-segmented
                v-model="universeMode"
                :disabled="form.sample"
                :options="universeModeOptions"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Dataset">
              <el-select
                v-model="form.dataset_id"
                :disabled="form.sample"
                :loading="datasetsLoading"
                filterable
                placeholder="选择本地 research dataset"
                @change="applyDatasetDefaults"
              >
                <el-option
                  v-for="dataset in datasets"
                  :key="dataset.id"
                  :label="dataset.name"
                  :value="dataset.id"
                >
                  <div class="dataset-option">
                    <span>{{ dataset.name }}</span>
                    <span>{{ dataset.start ?? '-' }} / {{ dataset.end ?? '-' }}</span>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="!form.sample && universeMode === 'custom'" :gutter="12">
          <el-col :span="24">
            <el-form-item label="自选股票">
              <el-select
                v-model="selectedSymbols"
                :loading="datasetDetailLoading"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                placeholder="从当前数据集选择股票"
              >
                <el-option
                  v-for="symbol in datasetSymbols"
                  :key="symbol"
                  :label="symbol"
                  :value="symbol"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div v-if="selectedDataset && !form.sample" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">当前数据集</div>
          <div class="summary-title">{{ selectedDataset.name }}</div>
        </div>
        <el-tag effect="plain">{{ selectedDataset.symbol_count }} 个标的</el-tag>
        <el-tag effect="plain">{{ universeMode === 'custom' ? `${selectedSymbols.length} 个自选` : '使用全部标的' }}</el-tag>
        <el-tag effect="plain">{{ formatNumber(selectedDataset.row_count) }} 行</el-tag>
        <el-tag effect="plain">{{ selectedDataset.start ?? '-' }} / {{ selectedDataset.end ?? '-' }}</el-tag>
      </div>
    </div>

    <div v-if="job" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">当前任务</div>
          <div class="summary-title">{{ job.id }}</div>
        </div>
        <el-tag :type="statusType(job.status)" effect="plain">{{ job.status }}</el-tag>
        <el-tag v-if="isPolling" type="warning" effect="plain">运行中</el-tag>
        <el-tag v-if="job.error" type="danger" effect="plain">{{ job.error }}</el-tag>
      </div>
    </div>

    <div v-if="job" class="metric-grid">
      <div class="metric-card" v-for="item in metricItems" :key="item.label">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
      </div>
    </div>

    <div v-if="experiment" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">实验设定</h2>
        <el-tag type="warning" effect="plain">{{ experiment.execution_assumption }}</el-tag>
      </div>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="模式">{{ experiment.mode === 'sample' ? '样例数据' : '本地数据集' }}</el-descriptions-item>
        <el-descriptions-item label="日期范围">{{ experiment.actual_start }} / {{ experiment.actual_end }}</el-descriptions-item>
        <el-descriptions-item label="Top N">{{ experiment.top_n }}</el-descriptions-item>
        <el-descriptions-item label="持有交易日">{{ experiment.hold_days }}</el-descriptions-item>
        <el-descriptions-item label="标的池来源">{{ universeSourceLabel(experiment.universe_source) }}</el-descriptions-item>
        <el-descriptions-item label="初始资金">{{ formatMoney(experiment.capital) }}</el-descriptions-item>
        <el-descriptions-item label="最小分数">{{ experiment.min_score ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="市场宽度">{{ experiment.min_market_breadth_above_ma20 ?? '-' }}</el-descriptions-item>
      </el-descriptions>
      <div class="assumption-list">
        <el-tag v-for="note in experiment.notes" :key="note" effect="plain">{{ note }}</el-tag>
      </div>
    </div>

    <div v-if="outcomeSummary" class="metric-grid">
      <div class="metric-card" v-for="item in outcomeItems" :key="item.label">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">结果判断</h2>
        <el-tag v-if="result" effect="plain">{{ equityCurve.length }} 个交易日</el-tag>
      </div>
      <div ref="equityEl" class="chart"></div>
      <div ref="drawdownEl" class="chart"></div>
      <div ref="dailyReturnEl" class="chart small-chart"></div>
    </div>

    <div v-if="result" class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">回测标的池</h2>
          <el-tag effect="plain">{{ universeSymbols.length }}</el-tag>
          <el-tag v-if="experiment" effect="plain">{{ universeSourceLabel(experiment.universe_source) }}</el-tag>
        </div>
        <div class="symbol-tags">
          <el-tag v-for="symbol in universeSymbols" :key="symbol" effect="plain">
            {{ symbol }}
          </el-tag>
        </div>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">信号验证：最新尾盘选股</h2>
          <el-tag effect="plain">{{ latestSelectionDate }}</el-tag>
        </div>
        <el-table :data="latestSelection" height="260">
          <el-table-column prop="rank" label="排名" width="72" />
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="分数" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.score) }}</template>
          </el-table-column>
          <el-table-column label="收盘价" width="110" align="right">
            <template #default="{ row }">{{ formatPrice(row.close) }}</template>
          </el-table-column>
          <el-table-column label="因子贡献" min-width="230">
            <template #default="{ row }">
              <div class="factor-tags">
                <el-tag v-for="item in factorTags(row)" :key="item" effect="plain">{{ item }}</el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div v-if="result" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">分钟级尾盘验证</h2>
        <el-tag :type="tailVerificationType" effect="plain">{{ confirmedTailCount }} / {{ tailVerifications.length }} 已确认</el-tag>
      </div>
      <el-table :data="tailVerifications" height="360">
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column prop="symbol" label="股票" min-width="120" />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="row.status === 'confirmed' ? 'success' : 'warning'" effect="plain">
              {{ row.status === 'confirmed' ? '已确认' : '缺分钟数据' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="signal_time" label="信号时间" width="100" />
        <el-table-column label="尾盘涨幅" width="110" align="right">
          <template #default="{ row }">{{ formatPercentMetric(row.tail_return_pct) }}</template>
        </el-table-column>
        <el-table-column label="尾盘量比" width="110" align="right">
          <template #default="{ row }">{{ formatMetric(row.volume_ratio) }}</template>
        </el-table-column>
        <el-table-column label="信号价" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.signal_price) }}</template>
        </el-table-column>
        <el-table-column label="收盘价" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.close_price) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="说明" min-width="260" show-overflow-tooltip />
      </el-table>
    </div>

    <div v-if="result" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">信号验证：每日尾盘选股记录</h2>
        <el-tag effect="plain">{{ rebalanceSelections.length }}</el-tag>
      </div>
      <el-table :data="rebalanceSelections" height="360">
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column prop="rank" label="排名" width="72" />
        <el-table-column prop="symbol" label="股票" min-width="120" />
        <el-table-column label="分数" width="110" align="right">
          <template #default="{ row }">{{ formatScore(row.score) }}</template>
        </el-table-column>
        <el-table-column label="收盘价" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.close) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="result" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">执行验证：交易明细</h2>
        <el-tag effect="plain">{{ trades.length }}</el-tag>
      </div>
      <el-table :data="trades" height="420">
        <el-table-column prop="signal_date" label="信号日" width="120" />
        <el-table-column prop="date" label="交易日" width="120" />
        <el-table-column prop="symbol" label="股票" min-width="120" />
        <el-table-column label="方向" width="90">
          <template #default="{ row }">
            <el-tag :type="row.side === 'buy' ? 'success' : 'danger'" effect="plain">
              {{ row.side === 'buy' ? '买入' : '卖出' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="110" align="right" />
        <el-table-column label="价格" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.price) }}</template>
        </el-table-column>
        <el-table-column prop="price_source" label="价格来源" width="120" />
        <el-table-column label="金额" width="130" align="right">
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="手续费" width="110" align="right">
          <template #default="{ row }">{{ formatMoney(row.commission) }}</template>
        </el-table-column>
        <el-table-column label="已实现盈亏" width="130" align="right">
          <template #default="{ row }">{{ formatMoney(row.realized_pnl) }}</template>
        </el-table-column>
        <el-table-column label="原因" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.reason }}</template>
        </el-table-column>
        <el-table-column label="选股分" width="100" align="right">
          <template #default="{ row }">{{ formatScore(row.selection_score) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="result" class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">执行验证：持仓收益</h2>
          <el-tag effect="plain">{{ positionOutcomes.length }}</el-tag>
        </div>
        <el-table :data="positionOutcomes" height="340">
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="signal_date" label="信号日" width="120" />
          <el-table-column prop="buy_date" label="买入日" width="120" />
          <el-table-column prop="sell_date" label="卖出日" width="120" />
          <el-table-column prop="holding_days" label="持有天数" width="100" align="right" />
          <el-table-column label="收益率" width="110" align="right">
            <template #default="{ row }">{{ formatPercentMetric(row.return_pct) }}</template>
          </el-table-column>
          <el-table-column label="盈亏" width="120" align="right">
            <template #default="{ row }">{{ formatMoney(row.realized_pnl ?? row.unrealized_pnl) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">结果判断：月度收益</h2>
          <el-tag effect="plain">{{ monthlyReturns.length }}</el-tag>
        </div>
        <el-table :data="monthlyReturns" height="340">
          <el-table-column prop="month" label="月份" min-width="120" />
          <el-table-column label="收益率" width="130" align="right">
            <template #default="{ row }">{{ formatPercentMetric(row.return_pct) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type DatasetDetail, type DatasetSummary, type JobRecord, type JobStatus, type TailBacktestPayload } from '../api/client'

interface SeriesPoint {
  date: string
  value: number
}

interface SelectionRow {
  date: string
  rank: number
  symbol: string
  score: number
  close: number | null
  factor_values: Record<string, number | null>
  factor_contributions: Record<string, number | null>
}

interface TradeRow {
  trade_id: string
  date: string
  signal_date?: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  price_source?: string
  signal_close?: number
  amount: number
  commission: number
  realized_pnl: number
  reason: string
  selection_score: number | null
  selection_rank: number | null
}

interface ExperimentSummary {
  mode: 'sample' | 'dataset'
  actual_start: string
  actual_end: string
  capital: number
  top_n: number
  hold_days: number
  universe_source: 'sample_fixed' | 'dataset_all' | 'custom_symbols'
  requested_symbols: string[]
  min_score: number | null
  min_market_breadth_above_ma20: number | null
  execution_assumption: string
  notes: string[]
}

interface MonthlyReturnRow {
  month: string
  return_pct: number
}

interface PositionOutcomeRow {
  symbol: string
  status: 'open' | 'closed'
  signal_date?: string
  buy_date: string
  sell_date: string | null
  holding_days: number
  return_pct: number
  realized_pnl?: number
  unrealized_pnl?: number
}

interface TailVerificationRow {
  symbol: string
  date: string
  status: 'confirmed' | 'missing_intraday_data'
  reason: string
  signal_time: string | null
  tail_return_pct: number | null
  volume_ratio: number | null
  signal_price: number | null
  close_price: number | null
  bars: Array<{ time: string; close: number; volume: number }>
}

interface OutcomeSummary {
  closed_positions: number
  open_positions: number
  realized_pnl: number
  unrealized_pnl: number
  total_commission: number
  avg_position_return_pct: number
  win_rate_pct: number
}

const props = defineProps<{
  jobId?: string
}>()

const form = ref<TailBacktestPayload>({
  start: '2025-01-01',
  end: '2025-02-28',
  capital: 100000,
  top_n: 3,
  hold_days: 1,
  min_score: null,
  dataset_id: null,
  dataset_path: '',
  symbols: null,
  sample: false
})
const submitting = ref(false)
const isPolling = ref(false)
const datasetsLoading = ref(false)
const datasetDetailLoading = ref(false)
const datasets = ref<DatasetSummary[]>([])
const datasetDetail = ref<DatasetDetail | null>(null)
const selectedSymbols = ref<string[]>([])
const universeMode = ref<'all' | 'custom'>('all')
const universeModeOptions = [
  { label: '全部', value: 'all' },
  { label: '自选', value: 'custom' }
]
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const equityEl = ref<HTMLElement | null>(null)
const drawdownEl = ref<HTMLElement | null>(null)
const dailyReturnEl = ref<HTMLElement | null>(null)

const result = computed(() => job.value?.result ?? null)
const experiment = computed(() => (result.value?.experiment ?? null) as unknown as ExperimentSummary | null)
const metrics = computed(() => (result.value?.metrics ?? {}) as Record<string, number | string>)
const equityCurve = computed(() => (result.value?.equity_curve ?? []) as unknown as SeriesPoint[])
const drawdownCurve = computed(() => (result.value?.drawdown_curve ?? []) as unknown as SeriesPoint[])
const dailyReturnCurve = computed(() => (result.value?.daily_return_curve ?? []) as unknown as SeriesPoint[])
const universeSymbols = computed(() => (result.value?.universe_symbols ?? []) as string[])
const latestSelection = computed(() => (result.value?.latest_selection ?? []) as unknown as SelectionRow[])
const rebalanceSelections = computed(() => (result.value?.rebalance_selections ?? []) as unknown as SelectionRow[])
const trades = computed(() => (result.value?.trades ?? []) as unknown as TradeRow[])
const monthlyReturns = computed(() => (result.value?.monthly_returns ?? []) as unknown as MonthlyReturnRow[])
const positionOutcomes = computed(() => (result.value?.position_outcomes ?? []) as unknown as PositionOutcomeRow[])
const tailVerifications = computed(() => (result.value?.tail_verifications ?? []) as unknown as TailVerificationRow[])
const outcomeSummary = computed(() => (result.value?.outcome_summary ?? null) as unknown as OutcomeSummary | null)
const equityTradeMarkers = computed(() => buildTradeMarkers(equityCurve.value, trades.value))
const latestSelectionDate = computed(() => latestSelection.value[0]?.date ?? '-')
const selectedDataset = computed(() => datasets.value.find((dataset) => dataset.id === form.value.dataset_id) ?? null)
const datasetSymbols = computed(() => datasetDetail.value?.symbols ?? [])
const metricItems = computed(() => [
  { label: '总收益', value: formatPercentMetric(metrics.value.total_return) },
  { label: '年化收益', value: formatPercentMetric(metrics.value.annualized_return) },
  { label: 'Sharpe', value: formatMetric(metrics.value.sharpe_ratio) },
  { label: '最大回撤', value: formatPercentMetric(metrics.value.max_drawdown) },
  { label: '成交数', value: String(result.value?.trade_count ?? '-') },
  { label: '股票数', value: String(result.value?.symbol_count ?? '-') }
])
const outcomeItems = computed(() => [
  { label: '已平仓', value: String(outcomeSummary.value?.closed_positions ?? '-') },
  { label: '持仓中', value: String(outcomeSummary.value?.open_positions ?? '-') },
  { label: '已实现盈亏', value: formatMoney(outcomeSummary.value?.realized_pnl) },
  { label: '浮动盈亏', value: formatMoney(outcomeSummary.value?.unrealized_pnl) },
  { label: '手续费', value: formatMoney(outcomeSummary.value?.total_commission) },
  { label: '持仓胜率', value: formatPercentMetric(outcomeSummary.value?.win_rate_pct) }
])
const confirmedTailCount = computed(() => tailVerifications.value.filter((row) => row.status === 'confirmed').length)
const tailVerificationType = computed(() => {
  if (!tailVerifications.value.length) return 'info'
  return confirmedTailCount.value === tailVerifications.value.length ? 'success' : 'warning'
})

async function submit() {
  submitting.value = true
  try {
    const payload = {
      ...form.value,
      dataset_id: form.value.sample ? null : form.value.dataset_id,
      dataset_path: form.value.sample ? null : form.value.dataset_path,
      symbols: form.value.sample || universeMode.value === 'all' ? null : selectedSymbols.value
    }
    if (!payload.sample && !payload.dataset_id) {
      ElMessage.warning('请先选择数据集')
      return
    }
    if (!payload.sample && selectedDataset.value && !dateRangeWithinDataset()) {
      ElMessage.warning(`日期范围超出当前数据集：${selectedDataset.value.start ?? '-'} / ${selectedDataset.value.end ?? '-'}`)
      return
    }
    if (!payload.sample && universeMode.value === 'custom' && !selectedSymbols.value.length) {
      ElMessage.warning('请至少选择一只股票')
      return
    }
    const response = await api.submitTailBacktest(payload)
    activeJobId.value = response.job_id
    const completed = await pollJobUntilDone(response.job_id)
    if (completed) ElMessage.success('回测完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadDatasets() {
  datasetsLoading.value = true
  try {
    datasets.value = (await api.listDatasets()).items
    if (datasets.value.length && !form.value.dataset_id) {
      form.value.sample = false
      form.value.dataset_id = datasets.value[0].id
      await applyDatasetDefaults()
    } else if (!datasets.value.length) {
      form.value.sample = true
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据集失败')
  } finally {
    datasetsLoading.value = false
  }
}

async function applyDatasetDefaults() {
  const dataset = selectedDataset.value
  if (!dataset) return
  form.value.dataset_path = dataset.path
  if (dataset.start) form.value.start = dataset.start
  if (dataset.end) form.value.end = dataset.end
  selectedSymbols.value = []
  await loadDatasetDetail(dataset.id)
}

async function loadDatasetDetail(datasetId: string) {
  datasetDetailLoading.value = true
  try {
    datasetDetail.value = await api.getDataset(datasetId)
  } catch (error) {
    datasetDetail.value = null
    ElMessage.error(error instanceof Error ? error.message : '加载数据集标的失败')
  } finally {
    datasetDetailLoading.value = false
  }
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
  await nextTick()
  renderCharts()
}

async function loadJob(jobId: string) {
  if (!jobId) return
  activeJobId.value = jobId
  await refreshJob()
}

async function pollJobUntilDone(jobId: string) {
  isPolling.value = true
  try {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      job.value = await api.getJob(jobId)
      await nextTick()
      renderCharts()
      if (job.value.status === 'success') return true
      if (job.value.status === 'failed') {
        ElMessage.error(job.value.error ?? '回测任务失败')
        return false
      }
      await sleep(500)
    }
    ElMessage.warning('回测仍在运行，请稍后刷新结果')
    return false
  } finally {
    isPolling.value = false
  }
}

function renderCharts() {
  renderLine(equityEl.value, '净值', equityCurve.value, equityTradeMarkers.value)
  renderLine(drawdownEl.value, '回撤', drawdownCurve.value)
  renderBar(dailyReturnEl.value, '日收益', dailyReturnCurve.value)
}

function renderLine(el: HTMLElement | null, name: string, points: SeriesPoint[], markers: TradeMarker[] = []) {
  if (!el) return
  const chart = echarts.init(el)
  chart.setOption({
    grid: { left: 48, right: 24, top: 32, bottom: 42 },
    tooltip: { trigger: 'axis' },
    title: { show: !points.length, text: '暂无数据', left: 'center', top: 'middle', textStyle: { color: '#8a94a6', fontSize: 14 } },
    legend: markers.length ? { top: 0, right: 20 } : undefined,
    xAxis: { type: 'category', data: points.map((point) => point.date) },
    yAxis: { type: 'value', scale: true },
    series: [
      { name, type: 'line', smooth: false, showSymbol: false, data: points.map((point) => point.value) },
      {
        name: '买入',
        type: 'scatter',
        symbolSize: 9,
        itemStyle: { color: '#16a34a' },
        data: markers.filter((marker) => marker.side === 'buy').map((marker) => [marker.date, marker.value, marker.label])
      },
      {
        name: '卖出',
        type: 'scatter',
        symbolSize: 9,
        itemStyle: { color: '#dc2626' },
        data: markers.filter((marker) => marker.side === 'sell').map((marker) => [marker.date, marker.value, marker.label])
      }
    ]
  })
}

function renderBar(el: HTMLElement | null, name: string, points: SeriesPoint[]) {
  if (!el) return
  const chart = echarts.init(el)
  chart.setOption({
    grid: { left: 48, right: 24, top: 32, bottom: 42 },
    tooltip: { trigger: 'axis' },
    title: { show: !points.length, text: '暂无数据', left: 'center', top: 'middle', textStyle: { color: '#8a94a6', fontSize: 14 } },
    xAxis: { type: 'category', data: points.map((point) => point.date) },
    yAxis: { type: 'value', scale: true },
    series: [{
      name,
      type: 'bar',
      data: points.map((point) => point.value),
      itemStyle: {
        color: (params: { value: number }) => (params.value >= 0 ? '#16a34a' : '#dc2626')
      }
    }]
  })
}

function formatMetric(value: unknown, suffix = '') {
  if (typeof value === 'number') return `${Number(value).toLocaleString('zh-CN')}${suffix}`
  if (typeof value === 'string') return value
  return '-'
}

function formatPercentMetric(value: unknown) {
  if (typeof value === 'number') return `${value.toFixed(2)}%`
  if (typeof value === 'string') return value
  return '-'
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatScore(value: unknown) {
  return typeof value === 'number' ? value.toFixed(4) : '-'
}

function formatPrice(value: unknown) {
  return typeof value === 'number' ? value.toFixed(2) : '-'
}

function formatMoney(value: unknown) {
  return typeof value === 'number' ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value) : '-'
}

function universeSourceLabel(value: unknown) {
  if (value === 'sample_fixed') return '样例固定标的'
  if (value === 'custom_symbols') return '自定义股票池'
  if (value === 'dataset_all') return '数据集全部标的'
  return '-'
}

function dateRangeWithinDataset() {
  const dataset = selectedDataset.value
  if (!dataset?.start || !dataset?.end) return true
  return form.value.start >= dataset.start && form.value.end <= dataset.end && form.value.start <= form.value.end
}

function factorTags(row: SelectionRow) {
  const values = row.factor_values ?? {}
  const contributions = row.factor_contributions ?? {}
  return Object.keys({ ...values, ...contributions }).map((name) => {
    const raw = values[name] == null ? '-' : formatScore(values[name])
    const contribution = contributions[name] == null ? '-' : formatScore(contributions[name])
    return `${name}: ${raw} / ${contribution}`
  })
}

interface TradeMarker {
  date: string
  value: number
  side: 'buy' | 'sell'
  label: string
}

function buildTradeMarkers(points: SeriesPoint[], rows: TradeRow[]): TradeMarker[] {
  const valueByDate = new Map(points.map((point) => [point.date, point.value]))
  return rows
    .map((trade) => {
      const date = trade.date.slice(0, 10)
      const value = valueByDate.get(date)
      if (value == null) return null
      return {
        date,
        value,
        side: trade.side,
        label: `${trade.symbol} ${trade.side === 'buy' ? '买入' : '卖出'} ${trade.quantity}`
      }
    })
    .filter((marker): marker is TradeMarker => marker !== null)
}

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

watch(
  () => form.value.sample,
  (sample) => {
    if (!sample && !form.value.dataset_id && datasets.value.length) {
      form.value.dataset_id = datasets.value[0].id
      void applyDatasetDefaults()
    }
  }
)

watch(
  () => form.value.dataset_id,
  (datasetId) => {
    if (datasetId && !form.value.sample) void applyDatasetDefaults()
  }
)

watch(universeMode, (mode) => {
  if (mode === 'all') selectedSymbols.value = []
})

watch(
  () => props.jobId,
  (jobId) => {
    if (jobId) void loadJob(jobId)
  },
  { immediate: true }
)

onMounted(loadDatasets)
</script>
