<template>
  <div class="stock-list" v-loading="loading">
    <el-form :inline="true" class="filters">
      <el-form-item label="代码 / 名称">
        <el-input v-model="keyword" placeholder="代码 / 名称" clearable style="width: 200px" />
      </el-form-item>
      <el-form-item label="行业">
        <el-select
          v-model="industries"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="全部"
          style="width: 220px"
        >
          <el-option v-for="ind in industryOptions" :key="ind" :label="ind" :value="ind" />
        </el-select>
      </el-form-item>
      <el-form-item label="市场">
        <el-select
          v-model="markets"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="全部"
          style="width: 140px"
        >
          <el-option v-for="m in marketOptions" :key="m" :label="m" :value="m" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="status" style="width: 140px">
          <el-option label="全部" value="all" />
          <el-option label="非 ST" value="non_st" />
          <el-option label="ST" value="st" />
          <el-option label="退市" value="delisted" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <div class="summary">
      共 {{ items.length }} 只 / 符合筛选 {{ filtered.length }} 只
      (非 ST {{ countNonSt }} · ST {{ countSt }} · 退市 {{ countDelisted }})
    </div>

    <el-table v-if="!error" :data="paged" stripe border>
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-detail">
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="代码">{{ row.symbol }}</el-descriptions-item>
              <el-descriptions-item label="名称">{{ row.name }}</el-descriptions-item>
              <el-descriptions-item label="是否 ST">{{ row.is_st ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="行业">{{ row.industry || '—' }}</el-descriptions-item>
              <el-descriptions-item label="市场">{{ row.market || '—' }}</el-descriptions-item>
              <el-descriptions-item label="上市日">{{ row.list_date || '—' }}</el-descriptions-item>
              <el-descriptions-item label="最新日线">{{ row.last_daily_date || '—' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="代码" prop="symbol" width="120" />
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }">
          <span>{{ row.name }}</span>
          <el-tag v-if="isDelisted(row.name)" type="info" size="small" style="margin-left: 6px">退市</el-tag>
          <el-tag v-else-if="row.is_st" type="danger" size="small" style="margin-left: 6px">ST</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="行业" prop="industry" min-width="120">
        <template #default="{ row }">{{ row.industry || '—' }}</template>
      </el-table-column>
      <el-table-column label="市场" prop="market" width="80">
        <template #default="{ row }">{{ row.market || '—' }}</template>
      </el-table-column>
      <el-table-column label="上市日" prop="list_date" width="120">
        <template #default="{ row }">{{ row.list_date || '—' }}</template>
      </el-table-column>
      <el-table-column label="最新日线" width="130">
        <template #default="{ row }">
          <span :class="{ stale: isStale(row.last_daily_date) }">
            {{ row.last_daily_date || '—' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="emit('open-trend', row.symbol)">
            查看趋势
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="error" :description="error">
      <el-button @click="load">重试</el-button>
    </el-empty>

    <el-pagination
      v-if="!error"
      class="pager"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="[20, 50, 100]"
      :total="filtered.length"
      layout="total, sizes, prev, pager, next"
      @current-change="page = $event"
      @size-change="onPageSizeChange"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type StockListItem } from '../api/client'

const emit = defineEmits<{ (e: 'open-trend', symbol: string): void }>()

const items = ref<StockListItem[]>([])
const loading = ref(false)
const error = ref('')

const keyword = ref('')
const industries = ref<string[]>([])
const markets = ref<string[]>([])
const status = ref<'all' | 'non_st' | 'st' | 'delisted'>('all')
const page = ref(1)
const pageSize = ref(50)

const industryOptions = computed(() =>
  [...new Set(items.value.map((i) => i.industry).filter(Boolean))].sort()
)
const marketOptions = computed(() =>
  [...new Set(items.value.map((i) => i.market).filter(Boolean))].sort()
)

function isDelisted(name: string) {
  return name.includes('退市')
}

const latestDaily = computed(() => {
  const dates = items.value.map((i) => i.last_daily_date).filter(Boolean) as string[]
  if (!dates.length) return ''
  return dates.sort().slice(-1)[0]
})

function isStale(lastDaily: string | null) {
  if (!lastDaily || !latestDaily.value) return false
  return lastDaily < latestDaily.value
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return items.value.filter((row) => {
    if (kw) {
      const hit =
        row.symbol.toLowerCase().includes(kw) || row.name.toLowerCase().includes(kw)
      if (!hit) return false
    }
    if (industries.value.length && !industries.value.includes(row.industry)) return false
    if (markets.value.length && !markets.value.includes(row.market)) return false
    if (status.value === 'non_st' && (row.is_st || isDelisted(row.name))) return false
    if (status.value === 'st' && !row.is_st) return false
    if (status.value === 'delisted' && !isDelisted(row.name)) return false
    return true
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const countNonSt = computed(
  () => items.value.filter((i) => !i.is_st && !isDelisted(i.name)).length
)
const countSt = computed(() => items.value.filter((i) => i.is_st).length)
const countDelisted = computed(() => items.value.filter((i) => isDelisted(i.name)).length)

function onPageSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
}

function resetFilters() {
  keyword.value = ''
  industries.value = []
  markets.value = []
  status.value = 'all'
  page.value = 1
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.listStocks()
    items.value = res.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

load()
</script>

<style scoped>
.stock-list {
  background: #fff;
  padding: 16px;
  border-radius: 4px;
}

.filters {
  margin-bottom: 12px;
}

.summary {
  margin-bottom: 12px;
  color: #606266;
  font-size: 13px;
}

.expand-detail {
  padding: 12px 16px;
}

.stale {
  color: #f56c6c;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
