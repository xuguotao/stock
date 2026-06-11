<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">总览</h1>
      <el-button type="primary" @click="$emit('openBacktest')">运行尾盘回测</el-button>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">任务总数</div>
        <div class="metric-value">{{ jobs.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">成功任务</div>
        <div class="metric-value">{{ successCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">运行中</div>
        <div class="metric-value">{{ runningCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">失败任务</div>
        <div class="metric-value">{{ failedCount }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="page-header">
        <h2 class="page-title">最近任务</h2>
        <el-button @click="loadJobs">刷新</el-button>
      </div>
      <el-table :data="jobs" height="360">
        <el-table-column prop="kind" label="类型" min-width="170" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type JobRecord, type JobStatus } from '../api/client'

defineEmits<{ openBacktest: [] }>()

const jobs = ref<JobRecord[]>([])

const successCount = computed(() => jobs.value.filter((job) => job.status === 'success').length)
const runningCount = computed(() => jobs.value.filter((job) => job.status === 'running').length)
const failedCount = computed(() => jobs.value.filter((job) => job.status === 'failed').length)

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

async function loadJobs() {
  jobs.value = (await api.listJobs()).items
}

onMounted(loadJobs)
</script>
