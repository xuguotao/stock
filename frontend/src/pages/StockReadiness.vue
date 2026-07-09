<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">策略数据就绪度</h1>
      <div class="toolbar">
        <el-button type="primary" :loading="generatingSnapshot" @click="generateSnapshot">生成当前窗口快照</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="panel">
      <el-form label-width="92px">
        <el-row :gutter="12">
          <el-col :span="7">
            <el-form-item label="回测窗口">
              <el-date-picker
                v-model="filters.range"
                type="daterange"
                value-format="YYYY-MM-DD"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
              />
            </el-form-item>
          </el-col>
          <el-col :span="5">
            <el-form-item label="数据维度">
              <el-select v-model="filters.dimensions" multiple collapse-tags collapse-tags-tooltip>
                <el-option label="日线" value="daily" />
                <el-option label="5m" value="minute5" />
                <el-option label="行情快照" value="snapshot" />
                <el-option label="除权除息" value="xdxr" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="状态">
              <el-select v-model="filters.status">
                <el-option label="全部" value="all" />
                <el-option label="就绪" value="ready" />
                <el-option label="可回补" value="repairable" />
                <el-option label="快照不足" value="snapshot_insufficient" />
                <el-option label="不可回补" value="unrepairable" />
                <el-option label="无数据" value="no_data" />
              </el-select>
              <div class="form-hint">筛选按所选维度同时满足计算</div>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="市场">
              <el-select v-model="filters.market">
                <el-option label="全部" value="all" />
                <el-option label="沪市" value="SH" />
                <el-option label="深市" value="SZ" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="板块">
              <el-select v-model="filters.board">
                <el-option label="全部" value="all" />
                <el-option label="主板" value="MAIN" />
                <el-option label="科创板" value="STAR" />
                <el-option label="创业板" value="CHINEXT" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="搜索">
              <el-input v-model="filters.q" clearable placeholder="股票代码或名称" @keyup.enter="resetPageAndLoad" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-button type="primary" :loading="loading" @click="resetPageAndLoad">查询</el-button>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">已建档股票</div>
        <div class="metric-value">{{ summary?.total_symbols ?? 0 }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">就绪维度</div>
        <div class="metric-value">{{ aggregateStatus('ready') }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">可回补维度</div>
        <div class="metric-value">{{ aggregateStatus('repairable') }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">快照不足维度</div>
        <div class="metric-value">{{ aggregateStatus('snapshot_insufficient') }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">不可回补维度</div>
        <div class="metric-value">{{ aggregateStatus('unrepairable') }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">无数据维度</div>
        <div class="metric-value">{{ aggregateStatus('no_data') }}</div>
      </div>
    </div>

    <el-alert
      class="scope-alert"
      :title="snapshotScopeText()"
      type="info"
      :closable="false"
      show-icon
    />

    <el-alert
      v-if="activeSnapshotJob"
      class="snapshot-alert"
      :title="snapshotStatusText"
      :type="activeSnapshotJob.status === 'failed' ? 'error' : activeSnapshotJob.status === 'success' ? 'success' : 'info'"
      :closable="false"
      show-icon
    />

    <el-alert
      v-if="activeRepairJob"
      class="repair-alert"
      :title="repairStatusText"
      :type="activeRepairJob.status === 'failed' ? 'error' : activeRepairJob.status === 'success' ? 'success' : 'info'"
      :closable="false"
      show-icon
    />

    <div class="panel">
      <el-table :data="rows" v-loading="loading" height="620" empty-text="暂无就绪度数据">
        <el-table-column prop="symbol" label="代码" width="100" fixed />
        <el-table-column prop="name" label="名称" min-width="150" fixed show-overflow-tooltip />
        <el-table-column label="市场" width="80">
          <template #default="{ row }">{{ row.market }}</template>
        </el-table-column>
        <el-table-column label="板块" width="100">
          <template #default="{ row }">{{ boardText(row.board) }}</template>
        </el-table-column>
        <el-table-column
          v-for="dimension in filters.dimensions"
          :key="dimension"
          :label="dimensionLabel(dimension)"
          min-width="190"
        >
          <template #default="{ row }">
            <div class="metric-stack">
              <el-tag :type="statusType(row.dimensions[dimension]?.status)" effect="plain">
                {{ statusText(row.dimensions[dimension]?.status) }}
              </el-tag>
              <span>覆盖率 {{ formatCoverage(row.dimensions[dimension]?.coverage_ratio) }}</span>
              <span>缺失天数 {{ row.dimensions[dimension]?.missing_days ?? '-' }}</span>
              <span>检查 {{ row.dimensions[dimension]?.checked_days ?? 0 }} / {{ row.dimensions[dimension]?.query_trade_days ?? 0 }} 天</span>
              <span>最新 {{ row.dimensions[dimension]?.latest_date ?? '-' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="!canRepair(row)"
              :loading="repairing"
              @click="repair(row)"
            >
              {{ repairButtonText(row) }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pager"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="page = $event; load()"
        @size-change="pageSize = $event; resetPageAndLoad()"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { boardText, dimensionLabel, formatCoverage, statusText, statusType } from '../features/stock-readiness/formatters'
import { useStockReadiness } from '../features/stock-readiness/useStockReadiness'
import type { StockReadinessItem } from '../features/stock-readiness/types'

const {
  activeRepairJob,
  activeSnapshotJob,
  filters,
  generatingSnapshot,
  loading,
  page,
  pageSize,
  repairing,
  rows,
  summary,
  total,
  generateSnapshot,
  load,
  repair,
  repairStatusText,
  snapshotStatusText,
  resetPageAndLoad,
} = useStockReadiness()

function aggregateStatus(status: string) {
  return filters.value.dimensions.reduce((total, dimension) => total + (summary.value?.dimensions?.[dimension]?.[status] ?? 0), 0)
}

function canRepair(row: StockReadinessItem) {
  return filters.value.dimensions.some((dimension) => row.dimensions[dimension]?.repairable)
}

function minCheckedDays() {
  const values = rows.value.flatMap((row) =>
    filters.value.dimensions.map((dimension) => row.dimensions[dimension]?.checked_days).filter((value): value is number => typeof value === 'number')
  )
  return values.length ? Math.min(...values) : 0
}

function snapshotScopeText() {
  return `仅展示已生成就绪度快照的股票；查询窗口交易日 ${summary.value?.query_trade_days ?? 0} 天，快照检查交易日 ${minCheckedDays()} 天。`
}

function repairButtonText(row: StockReadinessItem) {
  const dimensions = filters.value.dimensions.filter((dimension) => row.dimensions[dimension]?.repairable)
  return dimensions.length ? `回补 ${dimensions.map(dimensionLabel).join('/')}` : '不可回补'
}

onMounted(load)
</script>
