<template>
  <div class="stock-list" v-loading="loading">
    <div class="stat-header">
      <div class="stat-group">
        <div class="stat-group-title">数据健康</div>
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-value">{{ items.length }}</div>
            <div class="stat-label">股票总数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ latestDaily || '—' }}</div>
            <div class="stat-label">最新交易日</div>
          </div>
          <div class="stat-card">
            <div class="stat-value fresh">{{ countFresh }}</div>
            <div class="stat-label">日线新鲜</div>
          </div>
          <div class="stat-card">
            <div class="stat-value stale">{{ countStale }}</div>
            <div class="stat-label">日线陈旧(含 ST {{ countSt }})</div>
          </div>
        </div>
      </div>
      <div class="stat-group">
        <div class="stat-group-title">宇宙画像</div>
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-value">{{ countResearchEligible }} / <span class="delisted">排除 {{ countResearchExcluded }}</span></div>
            <div class="stat-label">研究池 / 未纳入</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ countSH }} / {{ countSZ }}</div>
            <div class="stat-label">沪市 / 深市</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ industryCount }}</div>
            <div class="stat-label">行业数</div>
          </div>
        </div>
      </div>
    </div>
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
          <el-option label="数据就绪" value="ready" />
          <el-option label="有研究资格" value="research" />
          <el-option label="数据待补" value="not_ready" />
          <el-option label="未纳入" value="excluded" />
          <el-option label="非 ST" value="non_st" />
          <el-option label="ST" value="st" />
          <el-option label="退市整理" value="delisted" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <div class="summary">
      共 {{ items.length }} 只 / 符合筛选 {{ filtered.length }} 只
      (数据就绪 {{ countDataReady }} · 有研究资格 {{ countResearchEligible }} · 数据待补 {{ countDataNotReady }} · 未纳入 {{ countResearchExcluded }} · ST {{ countSt }} · 退市整理 {{ countDelisted }})
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
              <el-descriptions-item label="研究池">{{ row.research_eligible === true ? '纳入' : row.research_eligible === false ? '未纳入' : '未检查' }}</el-descriptions-item>
              <el-descriptions-item label="数据就绪">{{ row.data_ready === true ? '就绪' : row.data_ready === false ? '待补' : '未检查' }}</el-descriptions-item>
              <el-descriptions-item label="未纳入原因">{{ excludedReasonText(row) }}</el-descriptions-item>
              <el-descriptions-item label="数据缺口">{{ gapText(row) }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="代码" prop="symbol" width="120" />
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }">
          <span>{{ row.name }}</span>
          <el-tag v-if="isDelistingPeriod(row)" type="info" size="small" style="margin-left: 6px">退市整理</el-tag>
          <el-tag v-else-if="row.is_st" type="danger" size="small" style="margin-left: 6px">ST</el-tag>
          <el-tag v-if="row.research_eligible === false" type="warning" size="small" style="margin-left: 6px">未纳入</el-tag>
          <el-tag v-else-if="row.data_ready === false" type="warning" size="small" style="margin-left: 6px">待补</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="数据就绪" width="100">
        <template #default="{ row }">
          <el-tag :type="row.data_ready ? 'success' : row.data_ready === false ? 'warning' : 'info'" effect="plain" size="small">
            {{ row.data_ready === true ? '就绪' : row.data_ready === false ? '待补' : '未检查' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="未纳入原因" min-width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ excludedReasonText(row) }}</template>
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
import { computed, ref, watch } from 'vue'
import { api, type StockListItem } from '../api/client'

const emit = defineEmits<{ (e: 'open-trend', symbol: string): void }>()

const items = ref<StockListItem[]>([])
const loading = ref(false)
const error = ref('')

const keyword = ref('')
const industries = ref<string[]>([])
const markets = ref<string[]>([])
const status = ref<'all' | 'ready' | 'research' | 'not_ready' | 'excluded' | 'non_st' | 'st' | 'delisted'>('all')
const page = ref(1)
const pageSize = ref(50)

const industryOptions = computed(() =>
  [...new Set(items.value.map((i) => i.industry).filter(Boolean))].sort()
)
const marketOptions = computed(() =>
  [...new Set(items.value.map((i) => i.market).filter(Boolean))].sort()
)

function isDelistingPeriod(row: StockListItem) {
  return row.excluded_reasons?.includes('delisting_period') || row.name.startsWith('退市') || row.name.endsWith('退') || row.name.endsWith('退市')
}

function excludedReasonText(row: StockListItem) {
  const reasons = row.excluded_reasons ?? []
  if (!reasons.length) return row.research_eligible === false ? '未登记原因' : '—'
  return reasons.map(reasonLabel).join('，')
}

function gapText(row: StockListItem) {
  const gapReasons = row.data_gap_reasons ?? []
  const gaps = gapReasons.map(reasonLabel)
  if (row.daily_missing) gaps.push('日线待补')
  if (row.minute5_missing) gaps.push('5m待补')
  return [...new Set(gaps)].length ? [...new Set(gaps)].join('，') : '—'
}

function reasonLabel(reason: string) {
  const labels: Record<string, string> = {
    st_stock: 'ST',
    delisting_period: '退市整理',
    delisted: '已退市',
    unsupported_market: '不支持市场',
    status_unknown: '状态未知',
    daily_missing: '日线待补',
    minute5_missing: '5m待补'
  }
  return labels[reason] ?? reason
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
    if (status.value === 'ready' && row.data_ready !== true) return false
    if (status.value === 'research' && row.research_eligible !== true) return false
    if (status.value === 'not_ready' && !(row.research_eligible === true && row.data_ready === false)) return false
    if (status.value === 'excluded' && row.research_eligible !== false) return false
    if (status.value === 'non_st' && (row.is_st || isDelistingPeriod(row))) return false
    if (status.value === 'st' && !row.is_st) return false
    if (status.value === 'delisted' && !isDelistingPeriod(row)) return false
    return true
  })
})

watch([keyword, industries, markets, status], () => {
  page.value = 1
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const countNonSt = computed(
  () => items.value.filter((i) => !i.is_st && !isDelistingPeriod(i)).length
)
const countSt = computed(() => items.value.filter((i) => i.is_st).length)
const countDelisted = computed(() => items.value.filter((i) => isDelistingPeriod(i)).length)
const countResearchEligible = computed(() => items.value.filter((i) => i.research_eligible === true).length)
const countResearchExcluded = computed(() => items.value.filter((i) => i.research_eligible === false).length)
const countDataReady = computed(() => items.value.filter((i) => i.data_ready === true).length)
const countDataNotReady = computed(() => items.value.filter((i) => i.research_eligible === true && i.data_ready === false).length)
const countFresh = computed(
  () => items.value.filter((i) => i.last_daily_date === latestDaily.value).length
)
const countStale = computed(
  () => items.value.filter((i) => i.last_daily_date && i.last_daily_date < latestDaily.value).length
)
const countSH = computed(() => items.value.filter((i) => i.market === 'SH').length)
const countSZ = computed(() => items.value.filter((i) => i.market === 'SZ').length)
const industryCount = computed(
  () => new Set(items.value.map((i) => i.industry).filter(Boolean)).size
)

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

.stat-header {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
}

.stat-group {
  flex: 1;
}

.stat-group-title {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-cards {
  display: flex;
  gap: 16px;
}

.stat-card {
  min-width: 96px;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  line-height: 1.4;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.fresh {
  color: #67c23a;
}

.st {
  color: #f56c6c;
}

.delisted {
  color: #909399;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
