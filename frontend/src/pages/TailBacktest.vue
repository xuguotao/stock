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
            <el-form-item label="最小分数">
              <el-input-number v-model="form.min_score" :step="0.1" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="样例数据">
              <el-switch v-model="form.sample" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
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
      </el-form>
    </div>

    <div v-if="selectedDataset && !form.sample" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">当前数据集</div>
          <div class="summary-title">{{ selectedDataset.name }}</div>
        </div>
        <el-tag effect="plain">{{ selectedDataset.symbol_count }} 个标的</el-tag>
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

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">数据趋势</h2>
        <el-tag v-if="result" effect="plain">{{ equityCurve.length }} 个交易日</el-tag>
      </div>
      <div ref="equityEl" class="chart"></div>
      <div ref="drawdownEl" class="chart"></div>
    </div>

    <div v-if="result" class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">回测标的池</h2>
          <el-tag effect="plain">{{ universeSymbols.length }}</el-tag>
        </div>
        <div class="symbol-tags">
          <el-tag v-for="symbol in universeSymbols" :key="symbol" effect="plain">
            {{ symbol }}
          </el-tag>
        </div>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">最新调仓选股</h2>
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
        </el-table>
      </div>
    </div>

    <div v-if="result" class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">调仓选股记录</h2>
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
        <h2 class="page-title">交易明细</h2>
        <el-tag effect="plain">{{ trades.length }}</el-tag>
      </div>
      <el-table :data="trades" height="420">
        <el-table-column prop="date" label="日期" width="120" />
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
        <el-table-column label="金额" width="130" align="right">
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="手续费" width="110" align="right">
          <template #default="{ row }">{{ formatMoney(row.commission) }}</template>
        </el-table-column>
        <el-table-column label="已实现盈亏" width="130" align="right">
          <template #default="{ row }">{{ formatMoney(row.realized_pnl) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type DatasetSummary, type JobRecord, type JobStatus, type TailBacktestPayload } from '../api/client'

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
}

interface TradeRow {
  trade_id: string
  date: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  amount: number
  commission: number
  realized_pnl: number
}

const form = ref<TailBacktestPayload>({
  start: '2025-01-01',
  end: '2025-02-28',
  capital: 100000,
  top_n: 3,
  min_score: null,
  dataset_id: null,
  dataset_path: '',
  sample: true
})
const submitting = ref(false)
const isPolling = ref(false)
const datasetsLoading = ref(false)
const datasets = ref<DatasetSummary[]>([])
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const equityEl = ref<HTMLElement | null>(null)
const drawdownEl = ref<HTMLElement | null>(null)

const result = computed(() => job.value?.result ?? null)
const metrics = computed(() => (result.value?.metrics ?? {}) as Record<string, number | string>)
const equityCurve = computed(() => (result.value?.equity_curve ?? []) as unknown as SeriesPoint[])
const drawdownCurve = computed(() => (result.value?.drawdown_curve ?? []) as unknown as SeriesPoint[])
const universeSymbols = computed(() => (result.value?.universe_symbols ?? []) as string[])
const latestSelection = computed(() => (result.value?.latest_selection ?? []) as unknown as SelectionRow[])
const rebalanceSelections = computed(() => (result.value?.rebalance_selections ?? []) as unknown as SelectionRow[])
const trades = computed(() => (result.value?.trades ?? []) as unknown as TradeRow[])
const equityTradeMarkers = computed(() => buildTradeMarkers(equityCurve.value, trades.value))
const latestSelectionDate = computed(() => latestSelection.value[0]?.date ?? '-')
const selectedDataset = computed(() => datasets.value.find((dataset) => dataset.id === form.value.dataset_id) ?? null)
const metricItems = computed(() => [
  { label: '总收益', value: formatPercentMetric(metrics.value.total_return) },
  { label: '年化收益', value: formatPercentMetric(metrics.value.annualized_return) },
  { label: 'Sharpe', value: formatMetric(metrics.value.sharpe_ratio) },
  { label: '最大回撤', value: formatPercentMetric(metrics.value.max_drawdown) },
  { label: '成交数', value: String(result.value?.trade_count ?? '-') },
  { label: '股票数', value: String(result.value?.symbol_count ?? '-') }
])

async function submit() {
  submitting.value = true
  try {
    const payload = {
      ...form.value,
      dataset_id: form.value.sample ? null : form.value.dataset_id,
      dataset_path: form.value.sample ? null : form.value.dataset_path
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
    if (!form.value.sample && !form.value.dataset_id && datasets.value.length) {
      form.value.dataset_id = datasets.value[0].id
      applyDatasetDefaults()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据集失败')
  } finally {
    datasetsLoading.value = false
  }
}

function applyDatasetDefaults() {
  const dataset = selectedDataset.value
  if (!dataset) return
  form.value.dataset_path = dataset.path
  if (dataset.start) form.value.start = dataset.start
  if (dataset.end) form.value.end = dataset.end
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
  await nextTick()
  renderCharts()
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
      applyDatasetDefaults()
    }
  }
)

onMounted(loadDatasets)
</script>
