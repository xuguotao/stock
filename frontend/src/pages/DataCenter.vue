<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">数据中心</h1>
      <div class="toolbar">
        <el-button type="primary" :loading="maintaining" @click="runDailyMaintenance">日常维护</el-button>
        <el-button :loading="buildingDataset" @click="buildClickHouseDataset">构建回测数据集</el-button>
        <el-date-picker
          v-model="minute5TradeDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="5分钟线日期"
          style="width: 150px"
        />
        <el-button :loading="syncingMinute5" @click="syncMinute5">更新 5分钟线</el-button>
        <el-button plain :loading="syncing" @click="syncStockDb">同步旧 Stock DB</el-button>
        <el-button :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">股票库</div>
        <div class="metric-value">{{ dataStatus?.database.exists ? '可用' : '缺失' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">股票数</div>
        <div class="metric-value">{{ formatNumber(dataStatus?.stock_summary.stock_count ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最新日线</div>
        <div class="metric-value compact-value">{{ dataStatus?.health.daily_latest_date ?? '-' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最新分钟</div>
        <div class="metric-value compact-value">{{ dataStatus?.health.minute5_latest_datetime ?? '-' }}</div>
      </div>
    </div>

    <div class="panel stock-db-panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">{{ databaseTitle }}</h2>
        <el-tag :type="dataStatus?.database.exists ? 'success' : 'danger'" effect="plain">
          {{ dataStatus?.health.status ?? '-' }}
        </el-tag>
      </div>
      <div v-if="syncJob" class="sync-progress">
        <div class="sync-progress-header">
          <span>同步任务：{{ syncJob.progress.message || syncJob.status }}</span>
          <el-tag :type="jobStatusType(syncJob.status)" effect="plain">{{ syncJob.status }}</el-tag>
        </div>
        <el-progress
          :percentage="syncJob.progress.percent"
          :status="syncJob.status === 'failed' ? 'exception' : syncJob.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div v-if="minute5Job" class="sync-progress">
        <div class="sync-progress-header">
          <span>5分钟线任务：{{ minute5Job.progress.message || minute5Job.status }}</span>
          <el-tag :type="jobStatusType(minute5Job.status)" effect="plain">{{ minute5Job.status }}</el-tag>
        </div>
        <el-progress
          :percentage="minute5Job.progress.percent"
          :status="minute5Job.status === 'failed' ? 'exception' : minute5Job.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div v-if="maintenanceJob" class="sync-progress">
        <div class="sync-progress-header">
          <span>日常维护：{{ maintenanceJob.progress.message || maintenanceJob.status }}</span>
          <el-tag :type="jobStatusType(maintenanceJob.status)" effect="plain">{{ maintenanceJob.status }}</el-tag>
        </div>
        <el-progress
          :percentage="maintenanceJob.progress.percent"
          :status="maintenanceJob.status === 'failed' ? 'exception' : maintenanceJob.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div v-if="datasetBuildJob" class="sync-progress">
        <div class="sync-progress-header">
          <span>数据集构建：{{ datasetBuildJob.progress.message || datasetBuildJob.status }}</span>
          <el-tag :type="jobStatusType(datasetBuildJob.status)" effect="plain">{{ datasetBuildJob.status }}</el-tag>
        </div>
        <el-progress
          :percentage="datasetBuildJob.progress.percent"
          :status="datasetBuildJob.status === 'failed' ? 'exception' : datasetBuildJob.status === 'success' ? 'success' : undefined"
        />
      </div>
      <el-descriptions :column="2" border>
        <el-descriptions-item :label="databaseLocationLabel">
          <span class="mono-text">{{ databaseLocation }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="数据质量">
          <el-tag :type="qualityTagType(dataStatus?.quality?.status)" effect="plain">
            {{ dataStatus?.quality?.status ?? '-' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatBytes(dataStatus?.database.size_bytes ?? 0) }}</el-descriptions-item>
        <el-descriptions-item label="非 ST 股票">{{ formatNumber(dataStatus?.stock_summary.non_st_stock_count ?? 0) }}</el-descriptions-item>
        <el-descriptions-item label="ST 股票">{{ formatNumber(dataStatus?.stock_summary.st_stock_count ?? 0) }}</el-descriptions-item>
        <el-descriptions-item label="日线覆盖">
          {{ tableRange('daily_kline') }}
        </el-descriptions-item>
        <el-descriptions-item label="日线股票">
          {{ formatNumber(dataStatus?.health.daily_symbol_count ?? 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="分钟线覆盖">
          {{ tableRange('minute5_kline') }}
        </el-descriptions-item>
        <el-descriptions-item label="分钟线标的">
          {{ formatNumber(dataStatus?.health.minute5_symbol_count ?? 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="日线缺口">
          {{ qualityCoverageText(dataStatus?.quality?.daily) }}
        </el-descriptions-item>
        <el-descriptions-item label="分钟线缺口">
          {{ qualityCoverageText(dataStatus?.quality?.minute5) }}
        </el-descriptions-item>
        <el-descriptions-item label="日线样本">
          {{ missingSampleText(dataStatus?.quality?.daily.missing_samples) }}
        </el-descriptions-item>
        <el-descriptions-item label="分钟线样本">
          {{ missingSampleText(dataStatus?.quality?.minute5.missing_samples) }}
        </el-descriptions-item>
      </el-descriptions>
      <el-table :data="tableRows" height="250" empty-text="暂无表信息">
        <el-table-column prop="name" label="表" min-width="160" />
        <el-table-column label="行数" width="130" align="right">
          <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
        </el-table-column>
        <el-table-column label="标的数" width="100" align="right">
          <template #default="{ row }">{{ row.symbol_count == null ? '-' : formatNumber(row.symbol_count) }}</template>
        </el-table-column>
        <el-table-column label="日期范围" min-width="220">
          <template #default="{ row }">{{ row.date_range ? `${row.date_range.start ?? '-'} / ${row.date_range.end ?? '-'}` : '-' }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div class="data-center-grid">
      <div class="panel dataset-list">
        <div class="page-header panel-title-row">
          <h2 class="page-title">本地 Research Datasets</h2>
          <el-tag effect="plain">{{ datasets.length }}</el-tag>
        </div>
        <el-table
          :data="datasets"
          height="540"
          highlight-current-row
          @row-click="selectDataset"
        >
          <el-table-column prop="name" label="名称" min-width="220" show-overflow-tooltip />
          <el-table-column label="日期范围" min-width="190">
            <template #default="{ row }">
              {{ row.start ?? '-' }} / {{ row.end ?? '-' }}
            </template>
          </el-table-column>
          <el-table-column label="符号" width="90" align="right">
            <template #default="{ row }">{{ row.symbol_count }}</template>
          </el-table-column>
          <el-table-column label="行数" width="110" align="right">
            <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel dataset-detail">
        <div class="page-header panel-title-row">
          <h2 class="page-title">数据集详情</h2>
          <el-tag v-if="detail" type="success" effect="plain">已选择</el-tag>
        </div>

        <el-empty v-if="!detail" description="选择左侧数据集查看详情" />
        <template v-else>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="文件名">{{ detail.name }}</el-descriptions-item>
            <el-descriptions-item label="路径">
              <span class="mono-text">{{ detail.path }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="Manifest">
              <span class="mono-text">{{ detail.manifest_path ?? '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="日期范围">
              {{ detail.start ?? '-' }} / {{ detail.end ?? '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="行数">{{ formatNumber(detail.row_count) }}</el-descriptions-item>
            <el-descriptions-item label="符号数">{{ detail.symbol_count }}</el-descriptions-item>
            <el-descriptions-item label="大小">{{ formatBytes(detail.size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="构建时间">{{ detail.built_at ?? '-' }}</el-descriptions-item>
          </el-descriptions>

          <div class="symbol-section">
            <div class="page-header panel-title-row">
              <h3 class="sub-title">符号列表</h3>
              <el-tag effect="plain">{{ detail.symbols.length }}</el-tag>
            </div>
            <div class="symbol-tags">
              <el-tag v-for="symbol in detail.symbols" :key="symbol" effect="plain">
                {{ symbol }}
              </el-tag>
            </div>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type DataStatusResponse, type DatasetDetail, type DatasetSummary, type JobRecord, type JobStatus } from '../api/client'

const datasets = ref<DatasetSummary[]>([])
const detail = ref<DatasetDetail | null>(null)
const dataStatus = ref<DataStatusResponse | null>(null)
const loading = ref(false)
const syncing = ref(false)
const syncingMinute5 = ref(false)
const maintaining = ref(false)
const buildingDataset = ref(false)
const syncJob = ref<JobRecord | null>(null)
const minute5Job = ref<JobRecord | null>(null)
const maintenanceJob = ref<JobRecord | null>(null)
const datasetBuildJob = ref<JobRecord | null>(null)
const minute5TradeDate = ref(todayLabel())

const tableRows = computed(() => Object.entries(dataStatus.value?.tables ?? {}).map(([name, table]) => ({
  name,
  ...table
})))
const databaseLocation = computed(() => {
  const database = dataStatus.value?.database
  if (!database) return '-'
  if (database.type === 'clickhouse') return `${database.host ?? '-'} / ${database.database ?? '-'}`
  return database.path ?? '-'
})
const databaseTitle = computed(() => (
  dataStatus.value?.database.type === 'clickhouse' ? 'ClickHouse 数据源' : '本地 Stock DB'
))
const databaseLocationLabel = computed(() => (
  dataStatus.value?.database.type === 'clickhouse' ? '连接' : '路径'
))

async function loadData() {
  loading.value = true
  try {
    const [statusResponse, datasetsResponse] = await Promise.all([
      api.getDataStatus(),
      api.listDatasets()
    ])
    dataStatus.value = statusResponse
    datasets.value = datasetsResponse.items
    if (datasets.value.length && !detail.value) {
      await selectDataset(datasets.value[0])
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据集失败')
  } finally {
    loading.value = false
  }
}

async function selectDataset(row: DatasetSummary) {
  try {
    detail.value = await api.getDataset(row.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据集详情失败')
  }
}

async function syncStockDb() {
  syncing.value = true
  try {
    const response = await api.syncStockDb({ backup: true })
    const completed = await pollSyncJob(response.job_id)
    if (completed) {
      ElMessage.success('旧 Stock DB 同步完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '旧 Stock DB 同步失败')
  } finally {
    syncing.value = false
  }
}

async function syncMinute5() {
  if (!minute5TradeDate.value) {
    ElMessage.warning('请选择 5分钟线日期')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将按非 ST 股票全市场更新 ${minute5TradeDate.value} 的 5分钟线，任务可能运行较久。`,
      '更新 5分钟线',
      { type: 'warning', confirmButtonText: '开始更新', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  syncingMinute5.value = true
  try {
    const response = await api.syncMinute5({
      trade_date: minute5TradeDate.value,
      limit: 0,
      include_st: false
    })
    const completed = await pollMinute5Job(response.job_id)
    if (completed) {
      ElMessage.success('5分钟线更新完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '5分钟线更新失败')
  } finally {
    syncingMinute5.value = false
  }
}

async function runDailyMaintenance() {
  const tradeDate = dataStatus.value?.health.daily_latest_date
  try {
    await ElMessageBox.confirm(
      `将执行${tradeDate ? ` ${tradeDate}` : ''} 的 ClickHouse 日常维护：5分钟线补齐、缺失重试、尾盘策略复核。`,
      '日常维护',
      { type: 'warning', confirmButtonText: '开始维护', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  maintaining.value = true
  try {
    const response = await api.runDailyMaintenance({
      trade_date: tradeDate ?? null,
      retry_no_data: true,
      run_strategy_review: true,
      strategy_limit: 500,
      strategy_top_n: 10
    })
    const completed = await pollMaintenanceJob(response.job_id)
    if (completed) {
      ElMessage.success('日常维护完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '日常维护失败')
  } finally {
    maintaining.value = false
  }
}

async function buildClickHouseDataset() {
  const end = dataStatus.value?.health.daily_latest_date
  if (!end) {
    ElMessage.warning('没有可用的最新日线日期')
    return
  }
  const start = defaultDatasetStart(end)
  const name = `daily_clickhouse_${end.replaceAll('-', '')}`
  try {
    await ElMessageBox.confirm(
      `将从 ClickHouse 构建 ${start} 至 ${end} 的回测数据集，默认取前 500 个非 ST 标的。`,
      '构建回测数据集',
      { type: 'warning', confirmButtonText: '开始构建', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  buildingDataset.value = true
  try {
    const response = await api.buildClickHouseDataset({
      start,
      end,
      name,
      limit: 500
    })
    const completed = await pollDatasetBuildJob(response.job_id)
    if (completed) {
      ElMessage.success('回测数据集构建完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '回测数据集构建失败')
  } finally {
    buildingDataset.value = false
  }
}

async function pollSyncJob(jobId: string) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    syncJob.value = await api.getJob(jobId)
    if (syncJob.value.status === 'success') return true
    if (syncJob.value.status === 'failed') {
      ElMessage.error(syncJob.value.error ?? '旧 Stock DB 同步失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('同步仍在运行，请稍后刷新任务状态')
  return false
}

async function pollMinute5Job(jobId: string) {
  for (let attempt = 0; attempt < 7200; attempt += 1) {
    minute5Job.value = await api.getJob(jobId)
    if (minute5Job.value.status === 'success') return true
    if (minute5Job.value.status === 'failed') {
      ElMessage.error(minute5Job.value.error ?? '5分钟线更新失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('5分钟线更新仍在运行，请稍后刷新任务状态')
  return false
}

async function pollMaintenanceJob(jobId: string) {
  for (let attempt = 0; attempt < 7200; attempt += 1) {
    maintenanceJob.value = await api.getJob(jobId)
    if (maintenanceJob.value.status === 'success') return true
    if (maintenanceJob.value.status === 'failed') {
      ElMessage.error(maintenanceJob.value.error ?? '日常维护失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('日常维护仍在运行，请稍后刷新任务状态')
  return false
}

async function pollDatasetBuildJob(jobId: string) {
  for (let attempt = 0; attempt < 1800; attempt += 1) {
    datasetBuildJob.value = await api.getJob(jobId)
    if (datasetBuildJob.value.status === 'success') return true
    if (datasetBuildJob.value.status === 'failed') {
      ElMessage.error(datasetBuildJob.value.error ?? '回测数据集构建失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('数据集构建仍在运行，请稍后刷新任务状态')
  return false
}

function defaultDatasetStart(end: string) {
  const value = new Date(`${end}T00:00:00`)
  value.setFullYear(value.getFullYear() - 2)
  return value.toISOString().slice(0, 10)
}

function todayLabel() {
  return new Date().toLocaleDateString('en-CA')
}

function jobStatusType(status: JobStatus) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function qualityTagType(status?: string) {
  if (status === 'ok') return 'success'
  if (status === 'warning') return 'warning'
  if (status === 'missing' || status === 'unavailable') return 'danger'
  return 'info'
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function tableRange(tableName: string) {
  const range = dataStatus.value?.tables[tableName]?.date_range
  return range ? `${range.start ?? '-'} / ${range.end ?? '-'}` : '-'
}

function qualityCoverageText(row?: { covered_symbols: number; missing_symbols: number; coverage_ratio: number }) {
  if (!row) return '-'
  return `覆盖 ${formatNumber(row.covered_symbols)}，缺 ${formatNumber(row.missing_symbols)}，${formatPercent(row.coverage_ratio)}`
}

function missingSampleText(samples?: Array<{ symbol: string; name: string }>) {
  if (!samples?.length) return '-'
  return samples.map((item) => `${item.symbol} ${item.name}`).join('，')
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

onMounted(loadData)
</script>

<style scoped>
.sync-progress {
  margin-bottom: 14px;
}

.sync-progress-header {
  align-items: center;
  color: #606266;
  display: flex;
  font-size: 13px;
  justify-content: space-between;
  margin-bottom: 8px;
}
</style>
