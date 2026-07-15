<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Mootdx 数据源</h1>
        <p class="page-subtitle">股票目录与日线同步的配置、运行审计和数据健康状态。</p>
      </div>
      <div class="page-actions">
        <el-button @click="router.push({ name: 'mootdx-catalog-quality' })">目录质量</el-button>
        <el-button @click="router.push({ name: 'mootdx-daily-quality' })">日线质量</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="health-grid">
      <section class="health-card">
        <span>目录快照</span>
        <strong>{{ healthValue('catalog', 'symbols') }}</strong>
        <small>{{ healthValue('catalog', 'captured_at') }}</small>
        <el-tag :type="healthType(snapshot?.health.catalog.status)">{{ mootdxStatusText(snapshot?.health.catalog.status ?? 'loading') }}</el-tag>
      </section>
      <section class="health-card">
        <span>最新日线覆盖</span>
        <strong>{{ healthValue('daily', 'symbols') }}</strong>
        <small>{{ healthValue('daily', 'trade_date') }}</small>
        <el-tag :type="healthType(snapshot?.health.daily.status)">{{ mootdxStatusText(snapshot?.health.daily.status ?? 'loading') }}</el-tag>
      </section>
      <section class="health-card">
        <span>日线标的状态</span>
        <strong>{{ activeSymbols }}</strong>
        <small>有效 / 已知无数据 / 临时失败</small>
        <el-tag :type="healthType(snapshot?.health.symbol_status.status)">{{ symbolStatusSummary }}</el-tag>
      </section>
    </div>

    <el-tabs v-model="activeTab" class="monitor-tabs">
      <el-tab-pane label="任务配置" name="tasks">
        <el-table :data="snapshot?.tasks ?? []" row-key="task_key">
          <el-table-column label="任务" min-width="220">
            <template #default="{ row }">
              <div class="task-name">{{ row.label }}</div>
              <div class="muted">{{ row.description }}</div>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="86">
            <template #default="{ row }"><el-switch v-model="draft(row).enabled" /></template>
          </el-table-column>
          <el-table-column label="调度" min-width="170">
            <template #default="{ row }">
              <el-select v-model="draft(row).schedule_kind" style="width: 128px">
                <el-option label="交易日定时" value="daily_time" />
                <el-option label="手动" value="manual" />
                <el-option label="间隔" value="interval" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="调度参数" min-width="260">
            <template #default="{ row }">
              <el-input v-model="draft(row).scheduleConfigJson" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="运行上限(秒)" width="145">
            <template #default="{ row }"><el-input-number v-model="draft(row).max_runtime_seconds" :min="1" controls-position="right" /></template>
          </el-table-column>
          <el-table-column label="失联阈值(秒)" width="145">
            <template #default="{ row }"><el-input-number v-model="draft(row).stale_after_seconds" :min="1" controls-position="right" /></template>
          </el-table-column>
          <el-table-column label="当前状态" width="120">
            <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ mootdxStatusText(row.status) }}</el-tag><div v-if="row.status === 'running'" class="muted">{{ row.progress.percent ?? 0 }}% {{ row.progress.processed ?? 0 }} / {{ row.progress.total ?? '-' }}</div></template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="saveTask(row)">保存</el-button>
              <el-button link :disabled="row.status === 'running'" @click="runTask(row.task_key)">{{ row.status === 'running' ? '执行中' : '运行一次' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="运行审计" name="audits">
        <el-table :data="snapshot?.audits ?? []" height="520" @row-click="openAudit">
          <el-table-column prop="task_label" label="任务" min-width="150" />
          <el-table-column prop="started_at" label="开始时间" min-width="170" />
          <el-table-column prop="duration_seconds" label="耗时(秒)" width="105" />
          <el-table-column label="运行" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ mootdxStatusText(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="审计" width="110"><template #default="{ row }"><el-tag :type="healthType(row.audit.status)">{{ mootdxStatusText(row.audit.status) }}</el-tag></template></el-table-column>
          <el-table-column label="写入" min-width="160"><template #default="{ row }">{{ insertedSummary(row.inserted) }}</template></el-table-column>
          <el-table-column label="原因 / 错误" min-width="260"><template #default="{ row }">{{ mootdxAuditReasonText(row.audit.reasons, row.error) }}</template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="健康状态" name="health">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="目录">{{ formatJson(snapshot?.health.catalog ?? {}) }}</el-descriptions-item>
          <el-descriptions-item label="日线">{{ formatJson(snapshot?.health.daily ?? {}) }}</el-descriptions-item>
          <el-descriptions-item label="标的状态">{{ formatJson(snapshot?.health.symbol_status ?? {}) }}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="auditDrawer" title="运行审计详情" size="46%">
      <div v-loading="auditLoading">
      <pre class="json-preview">{{ formatJson(selectedAudit) }}</pre>
      </div>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { api, type MootdxAuditRecord, type MootdxMonitorResponse, type MootdxMonitorTask } from '../api/client'
import { mootdxAuditReasonText, mootdxStatusText } from '../features/mootdx/formatters'

type TaskDraft = {
  enabled: boolean
  schedule_kind: string
  scheduleConfigJson: string
  max_runtime_seconds: number
  stale_after_seconds: number
}

const snapshot = ref<MootdxMonitorResponse | null>(null)
const router = useRouter()
const drafts = ref<Record<string, TaskDraft>>({})
const loading = ref(false)
const activeTab = ref('tasks')
const auditDrawer = ref(false)
const selectedAudit = ref<MootdxAuditRecord | null>(null)
const auditLoading = ref(false)
let refreshTimer: ReturnType<typeof window.setTimeout> | null = null

const activeSymbols = computed(() => String(snapshot.value?.health.symbol_status.active ?? '-'))
const symbolStatusSummary = computed(() => {
  const health = snapshot.value?.health.symbol_status
  if (!health) return '加载中'
  return `已知无数据 ${health.no_data ?? 0} / 临时失败 ${health.temporary_failed ?? 0}`
})

function draft(task: MootdxMonitorTask) {
  if (!drafts.value[task.task_key]) {
    drafts.value[task.task_key] = {
      enabled: task.enabled,
      schedule_kind: task.schedule_kind,
      scheduleConfigJson: JSON.stringify(task.schedule_config),
      max_runtime_seconds: task.max_runtime_seconds,
      stale_after_seconds: task.stale_after_seconds,
    }
  }
  return drafts.value[task.task_key]
}

function healthValue(section: 'catalog' | 'daily', key: string) {
  return String(snapshot.value?.health[section][key] ?? '-')
}

function healthType(status?: string) {
  return status === 'healthy' ? 'success' : status === 'failed' || status === 'unavailable' ? 'danger' : status === 'degraded' ? 'warning' : 'info'
}

function statusType(status?: string) {
  return status === 'success' ? 'success' : status === 'failed' || status === 'stale' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function insertedSummary(inserted: Record<string, number>) {
  return Object.entries(inserted).map(([table, rows]) => `${table}: ${rows}`).join(' | ') || '-'
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

async function load() {
  if (refreshTimer) { window.clearTimeout(refreshTimer); refreshTimer = null }
  loading.value = true
  try {
    snapshot.value = await api.getMootdxMonitor()
    const nextDrafts: Record<string, TaskDraft> = {}
    for (const task of snapshot.value.tasks) {
      nextDrafts[task.task_key] = {
        enabled: task.enabled,
        schedule_kind: task.schedule_kind,
        scheduleConfigJson: JSON.stringify(task.schedule_config),
        max_runtime_seconds: task.max_runtime_seconds,
        stale_after_seconds: task.stale_after_seconds,
      }
    }
    drafts.value = nextDrafts
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载 mootdx 监控失败')
  } finally {
    loading.value = false
    if (snapshot.value?.tasks.some((task) => task.status === 'running')) {
      refreshTimer = window.setTimeout(load, 2000)
    }
  }
}

async function saveTask(task: MootdxMonitorTask) {
  try {
    const value = draft(task)
    const scheduleConfig = JSON.parse(value.scheduleConfigJson)
    if (!scheduleConfig || Array.isArray(scheduleConfig) || typeof scheduleConfig !== 'object') throw new Error('调度参数必须是 JSON 对象')
    await api.updateDataOpsTaskConfig(task.task_key, {
      enabled: value.enabled,
      schedule_kind: value.schedule_kind,
      schedule_config: scheduleConfig,
      max_runtime_seconds: value.max_runtime_seconds,
      stale_after_seconds: value.stale_after_seconds,
    })
    ElMessage.success('任务配置已保存')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存任务配置失败')
  }
}

async function runTask(taskKey: string) {
  try {
    await api.runDataOpsTaskOnce(taskKey)
    ElMessage.success('已提交，等待独立 runner 接管')
    window.setTimeout(async () => {
      await load()
      const task = snapshot.value?.tasks.find((item) => item.task_key === taskKey)
      if (task?.status === 'failed' || task?.status === 'stale') {
        ElMessage.error(task.last_error || task.progress.message || '任务执行失败')
      } else if (task?.status === 'running') {
        ElMessage.success(task.progress.message || '任务已开始执行')
      }
    }, 2500)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交任务失败')
  }
}

async function openAudit(row: MootdxAuditRecord) {
  selectedAudit.value = row
  auditDrawer.value = true
  auditLoading.value = true
  try {
    selectedAudit.value = (await api.getMootdxMonitorAudit(row.run_id)).item
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载运行审计详情失败')
  } finally {
    auditLoading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => { if (refreshTimer) window.clearTimeout(refreshTimer) })
</script>

<style scoped>
.page-header, .page-actions { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }
.page-actions { margin: 0; flex-wrap: wrap; justify-content: flex-end; }
.page-title { margin: 0; }
.page-subtitle, .muted { color: #667085; font-size: 13px; margin: 6px 0 0; line-height: 1.45; }
.health-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.health-card { min-height: 112px; border: 1px solid #d9dee7; background: #fff; padding: 14px; display: grid; gap: 5px; }
.health-card span, .health-card small { color: #667085; font-size: 13px; }
.health-card strong { font-size: 24px; font-weight: 650; }
.task-name { font-weight: 600; }
.monitor-tabs { background: #fff; border: 1px solid #d9dee7; padding: 0 14px 14px; }
.json-preview { white-space: pre-wrap; word-break: break-word; margin: 0; padding: 12px; background: #f4f6f8; border: 1px solid #d9dee7; font-size: 12px; }
@media (max-width: 980px) { .health-grid { grid-template-columns: 1fr; } }
</style>
