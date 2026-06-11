<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">基金尾盘</h1>
      <div class="toolbar">
        <el-date-picker v-model="tradeDate" type="date" value-format="YYYY-MM-DD" />
        <el-button :loading="submitting" type="primary" @click="runAdvice">生成建议</el-button>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">基金池</div>
        <div class="metric-value">{{ universe.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">NAV 已就绪</div>
        <div class="metric-value">{{ navReadyCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">代理数据已就绪</div>
        <div class="metric-value">{{ proxyReadyCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">建议行数</div>
        <div class="metric-value">{{ report.rows.length }}</div>
      </div>
    </div>

    <div class="fund-tail-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">基金池数据状态</h2>
          <el-tag effect="plain">{{ universe.length }}</el-tag>
        </div>
        <el-table :data="universe" height="420">
          <el-table-column prop="code" label="代码" width="96" />
          <el-table-column prop="name" label="基金名称" min-width="220" show-overflow-tooltip />
          <el-table-column prop="proxy_provider" label="代理源" width="96" />
          <el-table-column prop="proxy_code" label="代理代码" width="110" />
          <el-table-column label="NAV" width="120">
            <template #default="{ row }">
              <el-tag :type="row.has_nav ? 'success' : 'danger'" effect="plain">
                {{ row.latest_nav_date ?? '缺失' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Proxy" width="120">
            <template #default="{ row }">
              <el-tag :type="row.has_proxy ? 'success' : 'danger'" effect="plain">
                {{ row.latest_proxy_date ?? '缺失' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">最新操作建议</h2>
          <el-button :disabled="!activeJobId" @click="refreshJob">刷新任务</el-button>
        </div>
        <el-table :data="report.rows" height="420">
          <el-table-column prop="基金代码" label="代码" width="96" />
          <el-table-column prop="基金名称" label="基金" min-width="210" show-overflow-tooltip />
          <el-table-column prop="今日代理涨跌率" label="涨跌" width="96" />
          <el-table-column prop="操作等级" label="等级" width="80" />
          <el-table-column prop="最终操作建议" label="建议" width="110" />
          <el-table-column prop="建议原因" label="原因" min-width="180" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">Markdown 报告</h2>
        <el-tag v-if="job" :type="job.status === 'success' ? 'success' : job.status === 'failed' ? 'danger' : 'warning'">
          {{ job.status }}
        </el-tag>
      </div>
      <pre class="markdown-preview">{{ report.markdown || '暂无报告' }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type FundTailReportResponse, type FundTailUniverseItem, type JobRecord } from '../api/client'

const loading = ref(false)
const submitting = ref(false)
const universe = ref<FundTailUniverseItem[]>([])
const report = ref<FundTailReportResponse>({
  rows: [],
  markdown: '',
  report_path: '',
  markdown_path: ''
})
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const tradeDate = ref(new Date().toISOString().slice(0, 10))

const navReadyCount = computed(() => universe.value.filter((item) => item.has_nav).length)
const proxyReadyCount = computed(() => universe.value.filter((item) => item.has_proxy).length)

async function loadAll() {
  loading.value = true
  try {
    const [universeResponse, reportResponse] = await Promise.all([
      api.listFundTailUniverse(),
      api.getFundTailReport()
    ])
    universe.value = universeResponse.items
    report.value = reportResponse
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载基金尾盘数据失败')
  } finally {
    loading.value = false
  }
}

async function runAdvice() {
  submitting.value = true
  try {
    const response = await api.submitFundTailAdvice({ trade_date: tradeDate.value })
    activeJobId.value = response.job_id
    await refreshJob()
    ElMessage.success('基金尾盘建议任务已提交')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
  if (job.value.status === 'success' && job.value.result) {
    const result = job.value.result as unknown as FundTailReportResponse
    report.value = {
      rows: result.rows ?? [],
      markdown: result.markdown ?? '',
      report_path: result.report_path ?? '',
      markdown_path: result.markdown_path ?? ''
    }
  }
}

onMounted(loadAll)
</script>
