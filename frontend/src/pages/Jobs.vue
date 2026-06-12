<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">任务中心</h1>
      <div class="toolbar">
        <el-select v-model="statusFilter" clearable placeholder="状态" style="width: 128px">
          <el-option label="pending" value="pending" />
          <el-option label="running" value="running" />
          <el-option label="success" value="success" />
          <el-option label="failed" value="failed" />
        </el-select>
        <el-button @click="loadJobs">刷新</el-button>
      </div>
    </div>

    <div class="panel">
      <el-table :data="filteredJobs" height="620" @row-click="openJob">
        <el-table-column prop="id" label="ID" min-width="280" show-overflow-tooltip />
        <el-table-column prop="kind" label="类型" min-width="180" />
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="220">
          <template #default="{ row }">
            <div class="job-progress-cell">
              <el-progress
                :percentage="progressPercent(row)"
                :status="progressStatus(row)"
                :stroke-width="8"
              />
              <span class="progress-message">{{ row.progress?.message ?? '-' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误" min-width="220" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
        <el-table-column label="结果" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="!resultPage(row)"
              @click.stop="openResult(row)"
            >
              查看结果
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" title="任务详情" size="48%">
      <template v-if="selectedJob">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">
            <span class="mono-text">{{ selectedJob.id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="类型">{{ selectedJob.kind }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(selectedJob.status)">{{ selectedJob.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="进度">
            <el-progress
              :percentage="progressPercent(selectedJob)"
              :status="progressStatus(selectedJob)"
              :stroke-width="10"
            />
          </el-descriptions-item>
          <el-descriptions-item label="阶段">{{ selectedJob.progress?.stage ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{ selectedJob.progress?.message ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ selectedJob.created_at }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ selectedJob.updated_at }}</el-descriptions-item>
          <el-descriptions-item label="错误">{{ selectedJob.error ?? '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="drawer-actions">
          <el-button
            type="primary"
            :disabled="!resultPage(selectedJob)"
            @click="openResult(selectedJob)"
          >
            查看结果
          </el-button>
          <el-button @click="refreshSelectedJob">刷新任务</el-button>
        </div>

        <h3 class="sub-title">参数</h3>
        <pre class="json-preview">{{ formatJson(selectedJob.params) }}</pre>

        <h3 class="sub-title">结果</h3>
        <pre class="json-preview">{{ formatJson(selectedJob.result) }}</pre>
      </template>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type JobRecord, type JobStatus } from '../api/client'

const jobs = ref<JobRecord[]>([])
const statusFilter = ref<JobStatus | ''>('')
const drawerVisible = ref(false)
const selectedJob = ref<JobRecord | null>(null)
const emit = defineEmits<{
  openResult: [{ page: string; jobId: string }]
}>()

const filteredJobs = computed(() => {
  if (!statusFilter.value) return jobs.value
  return jobs.value.filter((job) => job.status === statusFilter.value)
})

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function progressPercent(job: JobRecord) {
  return Math.max(0, Math.min(100, Number(job.progress?.percent ?? 0)))
}

function progressStatus(job: JobRecord) {
  if (job.status === 'success') return 'success'
  if (job.status === 'failed') return 'exception'
  return undefined
}

async function loadJobs() {
  jobs.value = (await api.listJobs(100)).items
}

function openJob(row: JobRecord) {
  selectedJob.value = row
  drawerVisible.value = true
}

function openResult(job: JobRecord | null) {
  const page = resultPage(job)
  if (!job || !page) return
  emit('openResult', { page, jobId: job.id })
}

function resultPage(job: JobRecord | null) {
  if (!job || job.status !== 'success') return ''
  if (job.kind === 'tail_session_backtest') return 'backtest'
  if (job.kind === 'fund_tail_advice') return 'fund-tail'
  return ''
}

async function refreshSelectedJob() {
  if (!selectedJob.value) return
  selectedJob.value = await api.getJob(selectedJob.value.id)
  const index = jobs.value.findIndex((job) => job.id === selectedJob.value?.id)
  if (index >= 0) jobs.value[index] = selectedJob.value
}

function formatJson(value: unknown) {
  if (value == null) return '-'
  return JSON.stringify(value, null, 2)
}

onMounted(loadJobs)
</script>

<style scoped>
.job-progress-cell {
  display: grid;
  gap: 4px;
}

.progress-message {
  color: #5f6b7a;
  font-size: 12px;
  line-height: 1.2;
}
</style>
