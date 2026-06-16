<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">策略复盘</h1>
      <div class="toolbar">
        <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
        <el-button type="primary" :loading="loading" @click="loadStats">刷新</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">已复核信号</div>
        <div class="metric-value">{{ formatNumber(stats?.overall.count ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">胜率</div>
        <div class="metric-value">{{ formatPercent(stats?.overall.win_rate ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最终入选胜率</div>
        <div class="metric-value">{{ formatPercent(stats?.selected_overall.win_rate ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">平均开盘收益</div>
        <div class="metric-value">{{ formatPercent(stats?.selected_overall.avg_open_return ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">平均收盘收益</div>
        <div class="metric-value">{{ formatPercent(stats?.selected_overall.avg_close_return ?? 0) }}</div>
      </div>
    </div>

    <div class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">近期复盘</h2>
          <el-tag effect="plain">{{ stats?.selected_recent.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.selected_recent ?? []" height="320" empty-text="暂无近期复盘">
          <el-table-column prop="date" label="日期" min-width="120" />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按状态</h2>
          <el-tag effect="plain">{{ stats?.by_status.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_status ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按信号层</h2>
          <el-tag effect="plain">{{ stats?.by_layer.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_layer ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">按过滤原因</h2>
        <el-tag effect="plain">{{ stats?.by_filter_reason.length ?? 0 }} / {{ stats?.recent.length ?? 0 }}</el-tag>
      </div>
      <el-table :data="stats?.by_filter_reason ?? []" height="320" empty-text="暂无复核样本">
        <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
        <el-table-column prop="count" label="信号数" width="100" align="right" />
        <el-table-column label="胜率" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
        </el-table-column>
        <el-table-column label="开盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
        </el-table-column>
        <el-table-column label="收盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type TailSignalStatsResponse } from '../api/client'

const loading = ref(false)
const stats = ref<TailSignalStatsResponse | null>(null)
const range = ref<[string, string] | null>(null)

async function loadStats() {
  loading.value = true
  try {
    stats.value = await api.getTailSignalStats(range.value?.[0], range.value?.[1])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载策略复盘失败')
  } finally {
    loading.value = false
  }
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

onMounted(loadStats)
</script>
