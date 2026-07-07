<template>
  <div class="stock-list" v-loading="loading">
    <div class="stat-header">
      <!-- 股票池概览 -->
      <div class="stat-group theme-primary">
        <div class="stat-group-title">
          <span class="stat-group-dot"></span>
          股票池概览
        </div>
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-value">{{ items.length }}</div>
            <div class="stat-label">总数</div>
          </div>
          <div class="stat-card has-bar">
            <div class="stat-value theme-success">{{ countResearchEligible }}</div>
            <div class="stat-label">
              可研究
              <span class="stat-rate">{{ eligibleRate }}%</span>
            </div>
            <div class="stat-bar"><div class="stat-bar-fill theme-success-bg" :style="{ width: eligibleRate + '%' }"></div></div>
          </div>
          <div class="stat-card has-bar">
            <div class="stat-value theme-success">{{ countDataReady }}</div>
            <div class="stat-label">
              数据就绪
              <span class="stat-rate">{{ dataReadyRate }}%</span>
            </div>
            <div class="stat-bar"><div class="stat-bar-fill theme-success-bg" :style="{ width: dataReadyRate + '%' }"></div></div>
          </div>
          <div class="stat-card">
            <div class="stat-value theme-warn">{{ countDataNotReady }}</div>
            <div class="stat-label">待补数据</div>
          </div>
        </div>
      </div>

      <!-- 市场分布 -->
      <div class="stat-group theme-blue">
        <div class="stat-group-title">
          <span class="stat-group-dot"></span>
          市场分布
        </div>
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-value">{{ countSH }}</div>
            <div class="stat-label">沪市</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ countSZ }}</div>
            <div class="stat-label">深市</div>
          </div>
          <div class="stat-card">
            <div class="stat-value theme-muted">{{ countBJ }}</div>
            <div class="stat-label">北交所 <span class="stat-tag">已排除</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ industryCount }}</div>
            <div class="stat-label">行业数</div>
          </div>
        </div>
      </div>

      <!-- 风险标记 -->
      <div class="stat-group theme-danger">
        <div class="stat-group-title">
          <span class="stat-group-dot"></span>
          风险标记
        </div>
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-value theme-danger-text">{{ countSt }}</div>
            <div class="stat-label">ST 股票</div>
          </div>
          <div class="stat-card">
            <div class="stat-value theme-danger-text">{{ countDelisted }}</div>
            <div class="stat-label">退市整理</div>
          </div>
          <div class="stat-card">
            <div class="stat-value theme-warn">{{ countResearchExcluded }}</div>
            <div class="stat-label">已排除</div>
          </div>
          <div class="stat-card">
            <div class="stat-value theme-muted">{{ countResearchExcluded + countSt + countDelisted }}</div>
            <div class="stat-label">风险合计</div>
          </div>
        </div>
      </div>

      <!-- 数据质量 -->
      <div class="stat-group theme-cyan">
        <div class="stat-group-title">
          <span class="stat-group-dot"></span>
          数据质量
        </div>
        <div class="stat-cards">
          <div class="stat-card has-bar">
            <div class="stat-value">{{ countFresh }}</div>
            <div class="stat-label">
              日线完整
              <span class="stat-rate">{{ freshRate }}%</span>
            </div>
            <div class="stat-bar"><div class="stat-bar-fill theme-cyan-bg" :style="{ width: freshRate + '%' }"></div></div>
          </div>
          <div class="stat-card">
            <div class="stat-value theme-warn">{{ countDailyMissing }}</div>
            <div class="stat-label">日线缺失</div>
          </div>
          <div class="stat-card has-bar">
            <div class="stat-value">{{ countMinute5Ready }}</div>
            <div class="stat-label">
              5分钟完整
              <span class="stat-rate">{{ minute5Rate }}%</span>
            </div>
            <div class="stat-bar"><div class="stat-bar-fill theme-cyan-bg" :style="{ width: minute5Rate + '%' }"></div></div>
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
const countBJ = computed(() => items.value.filter((i) => i.market === 'BJ').length)
const countDailyMissing = computed(() => items.value.length - countFresh.value)
const countMinute5Ready = computed(
  () => items.value.filter((i) => !i.minute5_missing).length
)

// 百分比计算
const eligibleRate = computed(() => {
  if (!items.value.length) return '0'
  return ((countResearchEligible.value / items.value.length) * 100).toFixed(1)
})

const dataReadyRate = computed(() => {
  if (!countResearchEligible.value) return '0'
  return ((countDataReady.value / countResearchEligible.value) * 100).toFixed(1)
})

const freshRate = computed(() => {
  if (!items.value.length) return '0'
  return ((countFresh.value / items.value.length) * 100).toFixed(1)
})

const minute5Rate = computed(() => {
  if (!items.value.length) return '0'
  return ((countMinute5Ready.value / items.value.length) * 100).toFixed(1)
})

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
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

@media (max-width: 1080px) {
  .stat-header {
    grid-template-columns: 1fr;
  }
}

.stat-group {
  background: #fff;
  border: 1px solid #e8ecf0;
  border-radius: 8px;
  padding: 14px 16px 12px;
  border-left: 3px solid #d9dee7;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}

.stat-group:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

/* 分组主题色 - 左边框 + 标题圆点 + 背景微染 */
.stat-group.theme-primary {
  border-left-color: #409eff;
  background: linear-gradient(135deg, #f0f7ff 0%, #fff 60%);
}
.stat-group.theme-primary .stat-group-dot { background: #409eff; }

.stat-group.theme-blue {
  border-left-color: #67c23a;
  background: linear-gradient(135deg, #f0f9eb 0%, #fff 60%);
}
.stat-group.theme-blue .stat-group-dot { background: #67c23a; }

.stat-group.theme-danger {
  border-left-color: #f56c6c;
  background: linear-gradient(135deg, #fef0f0 0%, #fff 60%);
}
.stat-group.theme-danger .stat-group-dot { background: #f56c6c; }

.stat-group.theme-cyan {
  border-left-color: #13c2c2;
  background: linear-gradient(135deg, #e6fffb 0%, #fff 60%);
}
.stat-group.theme-cyan .stat-group-dot { background: #13c2c2; }

.stat-group-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-group-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.stat-cards {
  display: flex;
  gap: 0;
}

.stat-card {
  flex: 1;
  min-width: 0;
  padding: 4px 10px;
  border-right: 1px solid #f0f2f5;
}

.stat-card:last-child {
  border-right: none;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #1a1a2e;
  line-height: 1.3;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

/* 有进度条的卡片 */
.stat-card.has-bar {
  padding-bottom: 0;
}

.stat-bar {
  height: 3px;
  background: #f0f2f5;
  border-radius: 2px;
  margin-top: 6px;
  overflow: hidden;
}

.stat-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s ease;
}

/* 颜色主题 */
.theme-success { color: #67c23a !important; }
.theme-success-bg { background: linear-gradient(90deg, #95d475, #67c23a); }

.theme-warn { color: #e6a23c !important; }

.theme-danger-text { color: #f56c6c !important; }

.theme-muted { color: #c0c4cc !important; }

.theme-cyan-bg { background: linear-gradient(90deg, #5cdbd3, #13c2c2); }

.stat-rate {
  font-size: 11px;
  font-weight: 500;
  color: #909399;
  font-variant-numeric: tabular-nums;
}

.stat-tag {
  font-size: 10px;
  color: #c0c4cc;
  background: #f4f4f5;
  padding: 0 4px;
  border-radius: 2px;
  line-height: 1.6;
}

/* 保留旧样式兼容性 */
.fresh { color: #67c23a; }
.stale { color: #f56c6c; }
.success { color: #67c23a; }
.warning { color: #e6a23c; }
.danger { color: #f56c6c; }
.muted { color: #909399; }
.st { color: #f56c6c; }
.delisted { color: #909399; }
.stat-percent {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 4px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
