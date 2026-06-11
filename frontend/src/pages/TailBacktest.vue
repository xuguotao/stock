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
              <el-input v-model="form.start" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="结束日期">
              <el-input v-model="form.end" />
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
              <el-input v-model="form.dataset_path" :disabled="form.sample" placeholder="data/research/xxx.parquet" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
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
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type JobRecord, type TailBacktestPayload } from '../api/client'

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
  dataset_path: '',
  sample: true
})
const submitting = ref(false)
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const equityEl = ref<HTMLElement | null>(null)
const drawdownEl = ref<HTMLElement | null>(null)

const result = computed(() => job.value?.result ?? null)
const metrics = computed(() => (result.value?.metrics ?? {}) as Record<string, number | string>)
const metricItems = computed(() => [
  { label: '总收益', value: formatMetric(metrics.value.total_return, '%') },
  { label: '年化收益', value: formatMetric(metrics.value.annualized_return, '%') },
  { label: 'Sharpe', value: formatMetric(metrics.value.sharpe_ratio) },
  { label: '最大回撤', value: formatMetric(metrics.value.max_drawdown, '%') },
  { label: '成交数', value: String(result.value?.trade_count ?? '-') },
  { label: '股票数', value: String(result.value?.symbol_count ?? '-') }
])

async function submit() {
  submitting.value = true
  try {
    const payload = {
      ...form.value,
      dataset_path: form.value.sample ? null : form.value.dataset_path
    }
    const response = await api.submitTailBacktest(payload)
    activeJobId.value = response.job_id
    await refreshJob()
    ElMessage.success('回测任务已提交')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
  await nextTick()
  renderCharts()
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
    xAxis: { type: 'category', data: points.map((point) => point.date) },
    yAxis: { type: 'value', scale: true },
    series: [{ name, type: 'line', smooth: false, showSymbol: false, data: points.map((point) => point.value) }]
  })
}

function formatMetric(value: unknown, suffix = '') {
  if (typeof value === 'number') return `${value}${suffix}`
  if (typeof value === 'string') return value
  return '-'
}
</script>
