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
      <h2 class="page-title">净值曲线</h2>
      <div ref="equityEl" class="chart"></div>
    </div>

    <div class="panel">
      <h2 class="page-title">回撤曲线</h2>
      <div ref="drawdownEl" class="chart"></div>
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
  renderLine(equityEl.value, '净值', (result.value?.equity_curve ?? []) as unknown as SeriesPoint[])
  renderLine(drawdownEl.value, '回撤', (result.value?.drawdown_curve ?? []) as unknown as SeriesPoint[])
}

function renderLine(el: HTMLElement | null, name: string, points: SeriesPoint[]) {
  if (!el) return
  const chart = echarts.init(el)
  chart.setOption({
    grid: { left: 48, right: 24, top: 32, bottom: 42 },
    tooltip: { trigger: 'axis' },
    title: { show: !points.length, text: '暂无数据', left: 'center', top: 'middle', textStyle: { color: '#8a94a6', fontSize: 14 } },
    xAxis: { type: 'category', data: points.map((point) => point.date) },
    yAxis: { type: 'value', scale: true },
    series: [{ name, type: 'line', smooth: false, showSymbol: false, data: points.map((point) => point.value) }]
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
