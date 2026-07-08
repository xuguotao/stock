<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">5m 分钟线质量巡检</h1>
        <p class="section-subtitle">直接检查 minute5_kline 真实数据，支持按日期、桶和股票抽验 5m OHLC 序列。</p>
      </div>
      <div class="toolbar">
        <el-date-picker v-model="minute5QualityDate" type="date" value-format="YYYY-MM-DD" placeholder="巡检日期" />
        <el-select v-model="minute5QualitySampleMode" style="width: 128px">
          <el-option label="随机抽验" value="random" />
          <el-option label="异常样本" value="invalid" />
          <el-option label="低覆盖" value="low_coverage" />
        </el-select>
        <el-button plain :loading="minute5QualityLoading" @click="loadMinute5Quality">刷新</el-button>
        <el-button type="primary" :loading="minute5QualityLoading" @click="loadMinute5QualitySample">随机抽验</el-button>
      </div>
    </div>

    <div class="panel" v-loading="minute5QualityLoading">
      <div class="quality-grid">
        <div class="quality-card">
          <div class="quality-title">
            <span>整体状态</span>
            <el-tag :type="qualityTagType(minute5QualitySummary?.status)" effect="plain">
              {{ minute5QualitySummary?.status ?? '-' }}
            </el-tag>
          </div>
          <strong>{{ formatNumber(minute5QualitySummary?.rows ?? 0) }} 行 / {{ formatNumber(minute5QualitySummary?.symbols ?? 0) }} 只</strong>
          <small>范围：{{ minute5QualitySummary?.range.start ?? '-' }} / {{ minute5QualitySummary?.range.end ?? '-' }}</small>
          <small>预期标的：{{ formatNumber(minute5QualitySummary?.expected_symbols ?? 0) }}</small>
        </div>
        <div class="quality-card">
          <div class="quality-title"><span>当前任务目标桶</span></div>
          <strong>{{ currentTaskTargetBucket }}</strong>
          <small>进度：{{ currentTaskProgress }}</small>
          <small>状态：{{ currentTaskStatus }}</small>
        </div>
        <div class="quality-card">
          <div class="quality-title"><span>最新完整桶</span></div>
          <strong>{{ minute5QualitySummary?.latest.complete_bucket ?? '-' }}</strong>
          <small>原始最新：{{ minute5QualitySummary?.latest.raw_bucket ?? '-' }}</small>
          <small>覆盖：{{ formatNumber(minute5QualitySummary?.latest.complete_symbols ?? 0) }} / {{ formatNumber(minute5QualitySummary?.latest.complete_threshold ?? 0) }}</small>
        </div>
        <div class="quality-card">
          <div class="quality-title"><span>数据污染</span></div>
          <strong>重复 {{ formatNumber(minute5QualitySummary?.issues.extra_rows ?? 0) }} 行</strong>
          <small>异常 OHLC：{{ formatNumber(minute5QualitySummary?.issues.invalid_ohlc ?? 0) }}</small>
          <small>非 5m 边界：{{ formatNumber(minute5QualitySummary?.issues.non_5m_boundary ?? 0) }}，非交易时段：{{ formatNumber(minute5QualitySummary?.issues.non_market_session ?? 0) }}</small>
        </div>
      </div>
    </div>

    <div class="quality-layout">
      <div class="panel">
        <div class="section-header no-top-margin">
          <div>
            <h2 class="section-title">日期质量</h2>
            <p class="section-subtitle">点击日期查看当天 5m 桶覆盖。</p>
          </div>
        </div>
        <el-table :data="minute5QualityDays" height="360" empty-text="暂无日期质量数据" @row-click="selectMinute5QualityDate">
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column label="桶" width="78" align="right">
            <template #default="{ row }">{{ formatNumber(row.buckets) }}</template>
          </el-table-column>
          <el-table-column label="标的" width="96" align="right">
            <template #default="{ row }">{{ formatNumber(row.symbols) }}</template>
          </el-table-column>
          <el-table-column label="异常" width="78" align="right">
            <template #default="{ row }">{{ formatNumber(row.invalid_rows) }}</template>
          </el-table-column>
          <el-table-column prop="latest_bucket" label="最新桶" min-width="150" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="panel">
        <div class="section-header no-top-margin">
          <div>
            <h2 class="section-title">桶覆盖</h2>
            <p class="section-subtitle">{{ minute5QualityDate }} 每个 5m 桶的覆盖情况。</p>
          </div>
        </div>
        <el-table :data="minute5QualityBuckets" height="360" empty-text="请选择日期查看桶覆盖">
          <el-table-column prop="datetime" label="时间" min-width="150" />
          <el-table-column label="覆盖" width="88" align="right">
            <template #default="{ row }">{{ formatPercent(row.coverage_ratio) }}</template>
          </el-table-column>
          <el-table-column label="标的" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.symbols) }}</template>
          </el-table-column>
          <el-table-column label="异常" width="78" align="right">
            <template #default="{ row }">{{ formatNumber(row.invalid_rows) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="quality-layout sample-layout">
      <div class="panel">
        <div class="section-header no-top-margin">
          <div>
            <h2 class="section-title">抽验列表</h2>
            <p class="section-subtitle">点击股票查看当日原始 5m OHLC 明细。</p>
          </div>
        </div>
        <el-table :data="minute5QualitySamples" height="360" empty-text="暂无抽验样本" @row-click="loadMinute5QualitySymbolBars">
          <el-table-column prop="symbol" label="代码" width="92" />
          <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
          <el-table-column label="bars" width="86" align="right">
            <template #default="{ row }">{{ formatNumber(row.bars) }}</template>
          </el-table-column>
          <el-table-column label="异常" width="86" align="right">
            <template #default="{ row }">{{ formatNumber(row.invalid_rows) }}</template>
          </el-table-column>
          <el-table-column prop="latest_bucket" label="最新桶" min-width="150" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="panel">
        <div class="section-header no-top-margin">
          <div>
            <h2 class="section-title">单票明细</h2>
            <p class="section-subtitle">{{ minute5QualitySelectedSymbol || '点击抽验列表中的股票查看明细。' }}</p>
          </div>
        </div>
        <el-table :data="minute5QualityBars" height="360" empty-text="暂无单票明细">
          <el-table-column prop="datetime" label="时间" min-width="150" />
          <el-table-column prop="open" label="开" width="76" align="right" />
          <el-table-column prop="high" label="高" width="76" align="right" />
          <el-table-column prop="low" label="低" width="76" align="right" />
          <el-table-column prop="close" label="收" width="76" align="right" />
          <el-table-column label="量" width="96" align="right">
            <template #default="{ row }">{{ formatNumber(row.volume) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type Minute5MonitorStatus, type Minute5QualityBar, type Minute5QualityBucket, type Minute5QualityDay, type Minute5QualitySampleItem, type Minute5QualitySummary } from '../api/client'

const minute5QualityLoading = ref(false)
const minute5QualitySummary = ref<Minute5QualitySummary | null>(null)
const minute5QualityDays = ref<Minute5QualityDay[]>([])
const minute5QualityBuckets = ref<Minute5QualityBucket[]>([])
const minute5QualitySamples = ref<Minute5QualitySampleItem[]>([])
const minute5QualityBars = ref<Minute5QualityBar[]>([])
const minute5QualityDate = ref(todayLabel())
const minute5QualitySampleMode = ref('random')
const minute5QualitySelectedSymbol = ref('')
const minute5Monitor = ref<Minute5MonitorStatus | null>(null)

const currentTaskTargetBucket = computed(() => {
  const monitor = minute5Monitor.value
  if (!monitor) return '-'
  if (!monitor.running) return '未运行'

  // Extract target bucket from progress message
  const progress = monitor.last_progress
  if (progress?.message) {
    const match = progress.message.match(/目标桶:\s*(\d{2}:\d{2})/)
    if (match) return match[1]
  }

  // Fallback to last result
  const result = monitor.last_result ?? {}
  const target = result.target_datetime as string | undefined
  if (target) {
    const timeMatch = target.match(/(\d{2}:\d{2}):\d{2}/)
    if (timeMatch) return timeMatch[1]
  }

  return '-'
})

const currentTaskProgress = computed(() => {
  const monitor = minute5Monitor.value
  if (!monitor || !monitor.running) return '-'
  const progress = monitor.last_progress
  if (!progress) return '-'
  if (progress.processed !== undefined && progress.total !== undefined) {
    return `${progress.processed} / ${progress.total} (${progress.percent}%)`
  }
  return `${progress.percent}%`
})

const currentTaskStatus = computed(() => {
  const monitor = minute5Monitor.value
  if (!monitor) return '未启动'
  if (!monitor.running) return '已停止'
  const progress = monitor.last_progress
  if (!progress) return '启动中'
  if (monitor.last_error) return `错误: ${monitor.last_error}`
  return progress.stage || '运行中'
})

async function loadMinute5Quality() {
  minute5QualityLoading.value = true
  try {
    const [summary, days, monitor] = await Promise.all([
      api.getMinute5QualitySummary(),
      api.getMinute5QualityDays({ limit: 30 }),
      api.getMinute5Monitor(),
    ])
    minute5QualitySummary.value = summary
    minute5QualityDays.value = days.items
    minute5Monitor.value = monitor
    minute5QualityDate.value = summary.latest.trade_date ?? days.items[0]?.trade_date ?? minute5QualityDate.value
    await Promise.all([
      loadMinute5QualityBuckets(),
      loadMinute5QualitySample()
    ])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载 5m 分钟线质量巡检失败')
  } finally {
    minute5QualityLoading.value = false
  }
}

async function loadMinute5QualityBuckets() {
  if (!minute5QualityDate.value) return
  const response = await api.getMinute5QualityBuckets(minute5QualityDate.value)
  minute5QualityBuckets.value = response.items
}

async function loadMinute5QualitySample() {
  const response = await api.getMinute5QualitySample({
    trade_date: minute5QualityDate.value,
    mode: minute5QualitySampleMode.value,
    limit: 20
  })
  minute5QualitySamples.value = response.items
  minute5QualityBars.value = []
  minute5QualitySelectedSymbol.value = ''
}

async function selectMinute5QualityDate(row: Minute5QualityDay) {
  minute5QualityDate.value = row.trade_date
  minute5QualityLoading.value = true
  try {
    await Promise.all([loadMinute5QualityBuckets(), loadMinute5QualitySample()])
  } finally {
    minute5QualityLoading.value = false
  }
}

async function loadMinute5QualitySymbolBars(row: Minute5QualitySampleItem) {
  if (!minute5QualityDate.value) return
  const response = await api.getMinute5QualitySymbolBars(row.symbol, minute5QualityDate.value)
  minute5QualityBars.value = response.items
  minute5QualitySelectedSymbol.value = `${response.symbol} ${response.name} / ${formatNumber(response.items.length)} 条`
}

function todayLabel() {
  return new Date().toLocaleDateString('en-CA')
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function qualityTagType(status?: string) {
  if (status === 'ok' || status === 'success') return 'success'
  if (status === 'warning' || status === 'partial') return 'warning'
  if (status === 'missing' || status === 'unavailable' || status === 'failed' || status === 'stale') return 'danger'
  return 'info'
}

onMounted(loadMinute5Quality)
</script>

<style scoped>
.quality-grid,
.quality-layout {
  display: grid;
  gap: 14px;
}

.quality-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.quality-layout {
  grid-template-columns: minmax(420px, 0.95fr) minmax(520px, 1.05fr);
  margin-top: 16px;
}

.quality-card {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 12px;
}

.quality-card strong {
  color: #20242a;
  font-size: 18px;
  line-height: 1.35;
}

.quality-card small {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.quality-title {
  align-items: center;
  color: #303133;
  display: flex;
  font-size: 14px;
  font-weight: 650;
  justify-content: space-between;
}

@media (max-width: 1200px) {
  .quality-grid,
  .quality-layout {
    grid-template-columns: 1fr;
  }
}
</style>
