<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">尾盘模型实验</h1>
      <div class="page-actions">
        <el-tag effect="plain">{{ models.length }}</el-tag>
        <el-button :loading="loading" @click="loadModels">刷新</el-button>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">模型运行记录</h2>
        <el-tag effect="plain">{{ modelRoot || '-' }}</el-tag>
      </div>
      <el-table :data="models" height="460" empty-text="暂无模型记录">
        <el-table-column prop="version" label="版本" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="170" />
        <el-table-column label="样本/折数" width="120" align="right">
          <template #default="{ row }">{{ row.sample_count ?? 0 }} / {{ row.fold_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="选中天数" width="110" align="right">
          <template #default="{ row }">{{ metric(row, 'selected_days') }}</template>
        </el-table-column>
        <el-table-column label="模型命中率" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(metric(row, 'hit_next_high_1pct_rate')) }}</template>
        </el-table-column>
        <el-table-column label="模型高点收益" width="130" align="right">
          <template #default="{ row }">{{ formatPercent(metric(row, 'avg_next_high_return')) }}</template>
        </el-table-column>
        <el-table-column label="模型回撤" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(metric(row, 'avg_next_low_drawdown')) }}</template>
        </el-table-column>
        <el-table-column label="规则基线" min-width="220">
          <template #default="{ row }">
            命中 {{ formatPercent(baselineMetric(row, 'next_high_hit_1pct_rate')) }} /
            高点 {{ formatPercent(baselineMetric(row, 'avg_next_high_return')) }} /
            回撤 {{ formatPercent(baselineMetric(row, 'avg_next_low_drawdown')) }}
          </template>
        </el-table-column>
        <el-table-column label="提升门禁" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ promotionText(row) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type TailMlModelManifest } from '../api/client'

const loading = ref(false)
const models = ref<TailMlModelManifest[]>([])
const modelRoot = ref('')

async function loadModels() {
  loading.value = true
  try {
    const payload = await api.getTailMlModels()
    models.value = payload.items
    modelRoot.value = payload.model_root
  } catch (error) {
    ElMessage.error(`加载尾盘模型失败：${String(error)}`)
  } finally {
    loading.value = false
  }
}

function statusType(status: string) {
  if (status === 'promoted') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'ready') return 'warning'
  return 'info'
}

function metric(row: TailMlModelManifest, key: string) {
  return row.metrics?.[key] ?? null
}

function baselineMetric(row: TailMlModelManifest, key: string) {
  return row.baseline_metrics?.[key] ?? null
}

function formatPercent(value: unknown) {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-'
}

function promotionText(row: TailMlModelManifest) {
  const decision = row.promotion_decision
  if (!decision) return '-'
  return decision.eligible ? '通过，可提升' : `未通过：${decision.reasons.join('，') || '-'}`
}

onMounted(() => {
  void loadModels()
})
</script>
