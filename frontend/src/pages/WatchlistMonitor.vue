<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1>观察池监控</h1>
        <p>展示关注标的的买点状态、趋势强弱和触发原因。</p>
      </div>
      <div class="watchlist-actions">
        <el-tag :type="refreshing ? 'warning' : 'success'" effect="plain">
          {{ refreshing ? '快照刷新中' : '快照自动更新' }}
        </el-tag>
        <span class="refresh-meta">最近刷新：{{ lastRefreshAt || '-' }}</span>
        <el-button :loading="loading || refreshing" type="primary" @click="manualRefresh">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon />

    <div class="summary-grid">
      <el-card v-for="card in summaryCards" :key="card.key" shadow="never">
        <div class="summary-value">{{ card.value }}</div>
        <div class="summary-label">{{ card.label }}</div>
      </el-card>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>标的状态</span>
          <div class="card-header-meta">
            <span>最新快照：{{ latestSnapshotTime }}</span>
            <el-tag effect="plain">{{ report?.trade_date || '未加载' }}</el-tag>
          </div>
        </div>
      </template>
      <el-table :data="report?.items || []" stripe @row-click="selectItem">
        <el-table-column label="代码" width="96">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="名称" width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openStockTrend(row.symbol)">{{ row.name }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="theme" label="主题" min-width="160" />
        <el-table-column label="行情源" width="112">
          <template #default="{ row }">
            <el-tag :type="row.data_status === 'snapshot_ok' ? 'success' : 'info'" effect="plain">
              {{ dataStatusLabel(row.data_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="现价" width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.latest_price) }}</template>
        </el-table-column>
        <el-table-column label="日涨跌" width="100" align="right">
          <template #default="{ row }">{{ formatPctValue(row.daily_change_pct) }}</template>
        </el-table-column>
        <el-table-column label="5日" width="90" align="right">
          <template #default="{ row }">{{ formatRatio(row.return_5d) }}</template>
        </el-table-column>
        <el-table-column label="20日" width="90" align="right">
          <template #default="{ row }">{{ formatRatio(row.return_20d) }}</template>
        </el-table-column>
        <el-table-column label="量能" width="90" align="right">
          <template #default="{ row }">{{ formatTimes(row.volume_ratio) }}</template>
        </el-table-column>
        <el-table-column label="快照时间" width="170">
          <template #default="{ row }">{{ row.quote_time || row.quote_snapshot_at || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="selected" shadow="never" class="detail-card">
      <template #header>
        <div class="card-header">
          <span>{{ selected.name }} 分析</span>
          <el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag>
        </div>
      </template>
      <div class="detail-grid">
        <div>
          <h3>买点区间</h3>
          <p>观察区：{{ levelText(selected.levels.observe) }}</p>
          <p>试仓区：{{ levelText(selected.levels.entry) }}</p>
          <p>加仓区：{{ levelText(selected.levels.add) }}</p>
          <p>失效位：{{ formatNumber(selected.levels.invalid) }}</p>
          <p>突破位：{{ formatNumber(selected.levels.breakout) }}</p>
          <p>行情源：{{ dataStatusLabel(selected.data_status) }}</p>
          <p>快照时间：{{ selected.quote_time || selected.quote_snapshot_at || '-' }}</p>
        </div>
        <div>
          <h3>触发原因</h3>
          <ul>
            <li v-for="reason in selected.reasons" :key="reason">{{ reason }}</li>
          </ul>
          <p class="notes">{{ selected.notes }}</p>
        </div>
      </div>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type WatchlistMonitorItem, type WatchlistMonitorReport, type WatchlistStatus } from '../api/client'

const REFRESH_INTERVAL_MS = 10_000
const report = ref<WatchlistMonitorReport | null>(null)
const selected = ref<WatchlistMonitorItem | null>(null)
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const lastRefreshAt = ref('')
let refreshTimer: number | null = null

const summaryCards = computed(() => {
  const summary = report.value?.summary || {}
  return [
    { key: 'entry_zone', label: '进入试仓区', value: summary.entry_zone || 0 },
    { key: 'watch_pullback', label: '等待回踩', value: summary.watch_pullback || 0 },
    { key: 'hot_wait', label: '短线过热', value: summary.hot_wait || 0 },
    { key: 'risk_off', label: '风险回避', value: summary.risk_off || 0 },
  ]
})
const latestSnapshotTime = computed(() => {
  const times = (report.value?.items ?? [])
    .map((item) => item.quote_time || item.quote_snapshot_at)
    .filter((value): value is string => Boolean(value))
    .sort()
  return times.at(-1) ?? '-'
})

async function loadReport() {
  loading.value = true
  error.value = ''
  try {
    await fetchReport()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载观察池报告失败'
  } finally {
    loading.value = false
  }
}

async function manualRefresh() {
  loading.value = true
  error.value = ''
  try {
    await fetchReport()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '刷新观察池报告失败'
  } finally {
    loading.value = false
  }
}

async function refreshFromSnapshot() {
  if (loading.value || refreshing.value) return
  refreshing.value = true
  try {
    await fetchReport()
    error.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '快照自动刷新失败'
  } finally {
    refreshing.value = false
  }
}

async function fetchReport() {
  const previousSymbol = selected.value?.symbol
  const nextReport = await api.getWatchlistMonitorReport()
  report.value = nextReport
  selected.value = nextReport.items.find((item) => item.symbol === previousSymbol) || nextReport.items[0] || null
  lastRefreshAt.value = currentTimeText()
}

function selectItem(row: WatchlistMonitorItem) {
  selected.value = row
}

function openStockTrend(symbol: string) {
  window.open(stockTrendUrl(symbol), '_blank', 'noopener,noreferrer')
}

function stockTrendUrl(symbol: string) {
  return `/stock-trend/${encodeURIComponent(symbol)}`
}

function statusLabel(status: WatchlistStatus) {
  return {
    hot_wait: '等待回踩',
    watch_pullback: '接近观察',
    entry_zone: '试仓区',
    add_zone: '加仓区',
    breakout_confirm: '突破确认',
    risk_off: '风险回避',
    neutral: '中性',
  }[status]
}

function statusType(status: WatchlistStatus) {
  if (status === 'entry_zone' || status === 'add_zone') return 'success'
  if (status === 'watch_pullback' || status === 'breakout_confirm') return 'warning'
  if (status === 'risk_off') return 'danger'
  return 'info'
}

function dataStatusLabel(status: string) {
  if (status === 'snapshot_ok') return '快照'
  if (status === 'ok') return '日线'
  if (status === 'quote_unavailable') return '缺行情'
  return status || '-'
}

function formatNumber(value: number | null) {
  return value === null || value === undefined ? 'n/a' : value.toFixed(2)
}

function formatRatio(value: number | null) {
  return value === null || value === undefined ? 'n/a' : `${(value * 100).toFixed(2)}%`
}

function formatPctValue(value: number | null) {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(2)}%`
}

function formatTimes(value: number | null) {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(2)}x`
}

function levelText(values: number[]) {
  return `${formatNumber(values[0])}-${formatNumber(values[1])}`
}

function currentTimeText() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = window.setInterval(refreshFromSnapshot, REFRESH_INTERVAL_MS)
}

function stopAutoRefresh() {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
}

onMounted(async () => {
  await loadReport()
  startAutoRefresh()
})
onBeforeUnmount(stopAutoRefresh)
</script>

<style scoped>
.page {
  display: grid;
  gap: 16px;
}

.page-header,
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.watchlist-actions,
.card-header-meta {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.refresh-meta,
.card-header-meta span {
  color: #667085;
  font-size: 12px;
}

.page-header h1 {
  margin: 0 0 6px;
  font-size: 22px;
}

.page-header p,
.notes {
  margin: 0;
  color: #667085;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
}

.summary-label {
  margin-top: 4px;
  color: #667085;
}

.detail-card {
  margin-top: 2px;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(220px, 320px) 1fr;
  gap: 24px;
}

.detail-grid h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.detail-grid p {
  margin: 6px 0;
}

.detail-grid ul {
  margin: 0 0 12px;
  padding-left: 18px;
}
</style>
