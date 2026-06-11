<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">任务中心</h1>
      <el-button @click="loadJobs">刷新</el-button>
    </div>

    <div class="panel">
      <el-table :data="jobs" height="620">
        <el-table-column prop="id" label="ID" min-width="280" />
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
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type JobRecord, type JobStatus } from '../api/client'

const jobs = ref<JobRecord[]>([])

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

async function loadJobs() {
  jobs.value = (await api.listJobs(100)).items
}

onMounted(loadJobs)
</script>
