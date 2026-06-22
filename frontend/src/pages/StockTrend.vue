<template>
  <section class="stock-trend-page">
    <div class="stock-trend-toolbar">
      <el-input v-model="symbolInput" placeholder="输入股票代码，如 601899.SH" style="width: 220px" @keyup.enter="loadTrend" />
      <el-date-picker v-model="tradeDate" type="date" value-format="YYYY-MM-DD" placeholder="交易日" />
      <el-button type="primary" :loading="loading" @click="loadTrend">分析</el-button>
    </div>

    <div v-if="trend" class="quote-strip">
      <div class="quote-identity">
        <div class="quote-name">{{ trend.name || '-' }}</div>
        <div class="quote-symbol">{{ stockCode }}</div>
      </div>
      <div class="quote-price" :class="changeClass">{{ formatPrice(trend.latest_price) }}</div>
      <div class="quote-change" :class="changeClass">{{ formatSignedPercent(quoteNumber('change_pct'), false) }}</div>
      <div v-for="item in quoteStats" :key="item.label" class="quote-stat">
        <div class="quote-stat-label">{{ item.label }}</div>
        <div class="quote-stat-value">{{ item.value }}</div>
      </div>
    </div>

    <div class="trend-terminal">
      <div class="terminal-header">
        <div>
          <h1>{{ trend ? `${trend.name || trend.symbol} 趋势` : '个股趋势分析' }}</h1>
          <p>{{ trend ? `日线 ${trend.daily.length} 根 / 5分钟 ${trend.intraday.length} 根 / 最新 ${trend.latest_intraday_time || quoteText('quote_time') || '-'}` : '输入股票后查看走势' }}</p>
        </div>
        <div class="legend-row">
          <span class="legend-item ma5">MA5</span>
          <span class="legend-item ma10">MA10</span>
          <span class="legend-item ma20">MA20</span>
          <span class="legend-item ma60">MA60</span>
        </div>
      </div>
      <div ref="dailyChartEl" class="stock-chart"></div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { api, type StockTrendResponse } from '../api/client'

const props = defineProps<{
  symbol?: string
}>()

const today = new Date().toISOString().slice(0, 10)
const symbolInput = ref(props.symbol || '')
const tradeDate = ref(today)
const loading = ref(false)
const trend = ref<StockTrendResponse | null>(null)
const dailyChartEl = ref<HTMLElement | null>(null)
let dailyChart: echarts.ECharts | null = null

const stockCode = computed(() => trend.value?.symbol.split('.')[0] ?? '-')
const changeClass = computed(() => {
  const value = quoteNumber('change_pct')
  if (value === null) return ''
  return value >= 0 ? 'quote-up' : 'quote-down'
})
const quoteStats = computed(() => [
  { label: 'PE(TTM)', value: formatMetric(quoteNumber('pe_ttm')) },
  { label: 'PB', value: formatMetric(quoteNumber('pb')) },
  { label: '市值', value: formatMoney(quoteNumber('mcap')) },
  { label: '成交量', value: formatVolume(quoteNumber('volume')) },
  { label: '成交额', value: formatMoney(quoteNumber('amount')) },
  { label: '换手', value: formatSignedPercent(quoteNumber('turnover_pct'), false) }
])

async function loadTrend() {
  const symbol = symbolInput.value.trim()
  if (!symbol) {
    ElMessage.warning('请输入股票代码')
    return
  }
  loading.value = true
  try {
    trend.value = await api.getStockTrend(symbol, tradeDate.value, 140)
    await nextTick()
    renderDailyChart()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载趋势失败')
  } finally {
    loading.value = false
  }
}

function renderDailyChart() {
  if (!dailyChartEl.value) return
  const rows = trend.value?.daily ?? []
  if (!dailyChart) dailyChart = echarts.init(dailyChartEl.value)
  const dates = rows.map((row) => row.date)
  const candles = rows.map((row) => [row.open, row.close, row.low, row.high])
  const volumes = rows.map((row, index) => ({
    value: [index, row.volume],
    itemStyle: { color: Number(row.close) >= Number(row.open) ? '#ef553f' : '#22c997' }
  }))
  dailyChart.setOption({
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    backgroundColor: '#fff',
    grid: [
      { left: 58, right: 44, top: 34, height: '60%' },
      { left: 58, right: 44, top: '75%', height: '14%' }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 55, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 22, start: 55, end: 100 }
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      borderWidth: 1,
      textStyle: { fontSize: 12 },
      formatter: (params: unknown) => tooltipText(params)
    },
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#505662' } }, axisLabel: { show: false }, splitLine: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true, axisLine: { lineStyle: { color: '#505662' } }, axisLabel: { color: '#4b5563' }, splitLine: { show: false } }
    ],
    yAxis: [
      { scale: true, splitLine: { lineStyle: { color: '#d8dde6' } }, axisLabel: { color: '#404751' } },
      { gridIndex: 1, splitLine: { lineStyle: { color: '#d8dde6' } }, axisLabel: { color: '#404751' } }
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: candles,
        itemStyle: {
          color: '#ef553f',
          color0: '#22c997',
          borderColor: '#ef553f',
          borderColor0: '#22c997'
        }
      },
      lineSeries('MA5', 'ma5', '#356bff'),
      lineSeries('MA10', 'ma10', '#9abb00'),
      lineSeries('MA20', 'ma20', '#1f2d5a'),
      lineSeries('MA60', 'ma60', '#ff7a30'),
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, barWidth: '58%' }
    ]
  }, true)
}

function lineSeries(name: string, field: string, color: string) {
  return {
    name,
    type: 'line',
    showSymbol: false,
    smooth: false,
    lineStyle: { width: 1, color },
    data: (trend.value?.daily ?? []).map((row) => row[field])
  }
}

function tooltipText(params: unknown) {
  if (!Array.isArray(params) || !params.length) return ''
  const candle = params.find((item) => item?.seriesName === 'K线')
  const date = candle?.axisValueLabel ?? ''
  const values = candle?.data ?? []
  const maText = params
    .filter((item) => typeof item?.seriesName === 'string' && item.seriesName.startsWith('MA'))
    .map((item) => `${item.marker}${item.seriesName}: ${formatPrice(item.data)}`)
    .join('<br/>')
  return [
    date,
    `开: ${formatPrice(values[1])}`,
    `收: ${formatPrice(values[2])}`,
    `低: ${formatPrice(values[3])}`,
    `高: ${formatPrice(values[4])}`,
    maText
  ].filter(Boolean).join('<br/>')
}

function quoteNumber(key: string) {
  const value = trend.value?.quote?.[key]
  return typeof value === 'number' ? value : null
}

function quoteText(key: string) {
  const value = trend.value?.quote?.[key]
  return typeof value === 'string' ? value : ''
}

function formatPrice(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '-'
}

function formatMetric(value: number | null) {
  return value === null ? '-' : value.toFixed(2)
}

function formatSignedPercent(value: number | null, ratio = true) {
  if (value === null) return '-'
  const percent = ratio ? value * 100 : value
  return `${percent >= 0 ? '+' : ''}${percent.toFixed(2)}%`
}

function formatMoney(value: number | null) {
  if (value === null) return '-'
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}亿`
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(1)}万`
  return value.toFixed(0)
}

function formatVolume(value: number | null) {
  if (value === null) return '-'
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿手`
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(0)}万手`
  return `${value.toFixed(0)}手`
}

function handleResize() {
  dailyChart?.resize()
}

watch(
  () => props.symbol,
  (symbol) => {
    if (!symbol) return
    symbolInput.value = symbol
    void loadTrend()
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('resize', handleResize)
  if (symbolInput.value) void loadTrend()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  dailyChart?.dispose()
  dailyChart = null
})
</script>

<style scoped>
.stock-trend-page {
  display: grid;
  gap: 14px;
}

.stock-trend-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.quote-strip,
.trend-terminal {
  background: #fff;
  border: 1px solid #e5e9f0;
  border-radius: 6px;
}

.quote-strip {
  align-items: center;
  display: flex;
  gap: 22px;
  min-height: 68px;
  overflow-x: auto;
  padding: 14px 16px;
}

.quote-identity {
  align-items: baseline;
  display: flex;
  gap: 10px;
  min-width: 140px;
}

.quote-name {
  color: #111827;
  font-size: 18px;
  font-weight: 700;
  white-space: nowrap;
}

.quote-symbol,
.quote-stat-label {
  color: #7a828f;
  font-size: 13px;
}

.quote-price {
  font-size: 25px;
  font-weight: 750;
}

.quote-change {
  font-size: 14px;
  font-weight: 650;
}

.quote-up {
  color: #ef553f;
}

.quote-down {
  color: #17a979;
}

.quote-stat {
  min-width: 64px;
}

.quote-stat-value {
  color: #111827;
  font-size: 14px;
  font-weight: 650;
  margin-top: 3px;
  white-space: nowrap;
}

.trend-terminal {
  padding: 18px 20px 14px;
}

.terminal-header {
  align-items: start;
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.terminal-header h1 {
  font-size: 18px;
  margin: 0 0 4px;
}

.terminal-header p {
  color: #667085;
  font-size: 12px;
  margin: 0;
}

.legend-row {
  display: flex;
  gap: 12px;
  padding-top: 3px;
}

.legend-item {
  font-size: 12px;
  font-weight: 650;
}

.ma5 {
  color: #356bff;
}

.ma10 {
  color: #8fac00;
}

.ma20 {
  color: #1f2d5a;
}

.ma60 {
  color: #ff7a30;
}

.stock-chart {
  height: calc(100vh - 250px);
  min-height: 560px;
  width: 100%;
}

@media (max-width: 900px) {
  .terminal-header {
    gap: 10px;
    flex-direction: column;
  }

  .stock-chart {
    min-height: 460px;
  }
}
</style>
