<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">数据中心</h1>
      <div class="toolbar">
        <el-button :loading="loading" @click="loadDatasets">刷新</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">数据集</div>
        <div class="metric-value">{{ datasets.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">总行数</div>
        <div class="metric-value">{{ formatNumber(totalRows) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">总大小</div>
        <div class="metric-value">{{ formatBytes(totalBytes) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最近构建</div>
        <div class="metric-value compact-value">{{ latestBuiltAt }}</div>
      </div>
    </div>

    <div class="data-center-grid">
      <div class="panel dataset-list">
        <div class="page-header panel-title-row">
          <h2 class="page-title">本地 Research Datasets</h2>
          <el-tag effect="plain">{{ datasets.length }}</el-tag>
        </div>
        <el-table
          :data="datasets"
          height="540"
          highlight-current-row
          @row-click="selectDataset"
        >
          <el-table-column prop="name" label="名称" min-width="220" show-overflow-tooltip />
          <el-table-column label="日期范围" min-width="190">
            <template #default="{ row }">
              {{ row.start ?? '-' }} / {{ row.end ?? '-' }}
            </template>
          </el-table-column>
          <el-table-column label="符号" width="90" align="right">
            <template #default="{ row }">{{ row.symbol_count }}</template>
          </el-table-column>
          <el-table-column label="行数" width="110" align="right">
            <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel dataset-detail">
        <div class="page-header panel-title-row">
          <h2 class="page-title">数据集详情</h2>
          <el-tag v-if="detail" type="success" effect="plain">已选择</el-tag>
        </div>

        <el-empty v-if="!detail" description="选择左侧数据集查看详情" />
        <template v-else>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="文件名">{{ detail.name }}</el-descriptions-item>
            <el-descriptions-item label="路径">
              <span class="mono-text">{{ detail.path }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="Manifest">
              <span class="mono-text">{{ detail.manifest_path ?? '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="日期范围">
              {{ detail.start ?? '-' }} / {{ detail.end ?? '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="行数">{{ formatNumber(detail.row_count) }}</el-descriptions-item>
            <el-descriptions-item label="符号数">{{ detail.symbol_count }}</el-descriptions-item>
            <el-descriptions-item label="大小">{{ formatBytes(detail.size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="构建时间">{{ detail.built_at ?? '-' }}</el-descriptions-item>
          </el-descriptions>

          <div class="symbol-section">
            <div class="page-header panel-title-row">
              <h3 class="sub-title">符号列表</h3>
              <el-tag effect="plain">{{ detail.symbols.length }}</el-tag>
            </div>
            <div class="symbol-tags">
              <el-tag v-for="symbol in detail.symbols" :key="symbol" effect="plain">
                {{ symbol }}
              </el-tag>
            </div>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type DatasetDetail, type DatasetSummary } from '../api/client'

const datasets = ref<DatasetSummary[]>([])
const detail = ref<DatasetDetail | null>(null)
const loading = ref(false)

const totalRows = computed(() => datasets.value.reduce((total, dataset) => total + dataset.row_count, 0))
const totalBytes = computed(() => datasets.value.reduce((total, dataset) => total + dataset.size_bytes, 0))
const latestBuiltAt = computed(() => {
  const values = datasets.value.map((dataset) => dataset.built_at).filter(Boolean) as string[]
  return values.length ? values.sort().at(-1) ?? '-' : '-'
})

async function loadDatasets() {
  loading.value = true
  try {
    datasets.value = (await api.listDatasets()).items
    if (datasets.value.length && !detail.value) {
      await selectDataset(datasets.value[0])
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据集失败')
  } finally {
    loading.value = false
  }
}

async function selectDataset(row: DatasetSummary) {
  try {
    detail.value = await api.getDataset(row.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据集详情失败')
  }
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`
}

onMounted(loadDatasets)
</script>
