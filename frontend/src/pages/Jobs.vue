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
        <el-table-column prop="error" label="错误" min-width="220" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
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
          <el-descriptions-item label="创建时间">{{ selectedJob.created_at }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ selectedJob.updated_at }}</el-descriptions-item>
          <el-descriptions-item label="错误">{{ selectedJob.error ?? '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="drawer-actions">
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

const filteredJobs = computed(() => {
  if (!statusFilter.value) return jobs.value
  return jobs.value.filter((job) => job.status === statusFilter.value)
})

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

async function loadJobs() {
  jobs.value = (await api.listJobs(100)).items
}

function openJob(row: JobRecord) {
  selectedJob.value = row
  drawerVisible.value = true
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
