<template>
  <div class="panel compact-panel">
    <div class="page-header panel-title-row">
      <h2 class="page-title">选股数据健康度</h2>
      <div class="toolbar">
        <el-tag :type="qualityTagType(status)" effect="plain">
          {{ status ?? 'loading' }}
        </el-tag>
        <el-tag effect="plain">{{ updateText }}</el-tag>
      </div>
    </div>
    <div class="health-status-grid">
      <div class="health-status-item" v-for="item in items" :key="item.label">
        <div class="health-status-head">
          <span class="health-status-label">{{ item.label }}</span>
          <el-tag :type="qualityTagType(item.status)" effect="plain" size="small">{{ item.status }}</el-tag>
        </div>
        <div class="health-status-value">{{ item.value }}</div>
      </div>
    </div>
    <div v-if="issues.length" class="diagnostic-message muted">
      异常：{{ issues.join('，') }}
    </div>
  </div>
</template>

<script setup lang="ts">
interface DataHealthItem {
  label: string
  value: string
  status?: string
}

defineProps<{
  status?: string
  updateText: string
  items: DataHealthItem[]
  issues: string[]
}>()

function qualityTagType(status?: string) {
  if (status === 'ok') return 'success'
  if (status === 'warning' || status === 'partial') return 'warning'
  if (status === 'error' || status === 'failed' || status === 'missing') return 'danger'
  return 'info'
}
</script>
