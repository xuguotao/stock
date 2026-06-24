<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">尾盘策略复盘</h1>
      <div class="toolbar">
        <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
        <el-button :loading="reviewingOutcomes" @click="reviewOutcomes">补算全部待复盘</el-button>
        <el-button type="primary" :loading="loading" @click="loadStats">刷新</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">正式选股已复盘</div>
        <div class="metric-value">{{ formatNumber(stats?.tracking_summary?.completed ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">待复盘信号</div>
        <div class="metric-value">{{ formatNumber(stats?.review_plan?.pending_signal_count ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">跟踪中信号</div>
        <div class="metric-value">{{ formatNumber(stats?.tracking_summary?.live_tracking ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">胜率</div>
        <div class="metric-value">{{ formatPercent(stats?.overall.win_rate ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最终入选胜率</div>
        <div class="metric-value">{{ formatPercent(stats?.selected_overall.win_rate ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">平均开盘收益</div>
        <div class="metric-value">{{ formatPercent(stats?.selected_overall.avg_open_return ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">平均收盘收益</div>
        <div class="metric-value">{{ formatPercent(stats?.selected_overall.avg_close_return ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">次日最高收益</div>
        <div class="metric-value">{{ formatPercent(stats?.execution_summary?.avg_max_return ?? stats?.selected_overall.avg_max_return ?? 0) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">次日最低回撤</div>
        <div class="metric-value">{{ formatPercent(stats?.execution_summary?.avg_min_return ?? stats?.selected_overall.avg_min_return ?? 0) }}</div>
      </div>
    </div>

    <div class="panel review-plan-panel">
      <div class="page-header panel-title-row">
        <div>
          <h2 class="page-title">复盘补算计划</h2>
          <p class="panel-subtitle">口径：正式选股 / 最终入选 / 已有次日行情但缺少收益记录。</p>
        </div>
        <el-tag :type="(stats?.review_plan?.pending_signal_count ?? 0) > 0 ? 'warning' : 'success'" effect="plain">
          {{ stats?.review_plan?.pending_date_count ?? 0 }} 日 / {{ stats?.review_plan?.pending_signal_count ?? 0 }} 条
        </el-tag>
      </div>
      <el-table :data="stats?.review_plan?.pending_dates ?? []" height="220" empty-text="暂无待补算复盘">
        <el-table-column prop="signal_date" label="信号日" min-width="120" />
        <el-table-column prop="selected_count" label="正式选股" width="110" align="right" />
        <el-table-column prop="outcome_count" label="已复盘" width="110" align="right" />
        <el-table-column prop="missing_count" label="待补算" width="110" align="right" />
      </el-table>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">交易执行口径</h2>
        <el-tag effect="plain">{{ stats?.execution_summary?.sample_count ?? 0 }}</el-tag>
      </div>
      <div class="execution-grid">
        <div class="execution-item">
          <span>开盘可盈利率</span>
          <strong>{{ formatPercent(stats?.execution_summary?.open_win_rate ?? 0) }}</strong>
        </div>
        <div class="execution-item">
          <span>收盘胜率</span>
          <strong>{{ formatPercent(stats?.execution_summary?.close_win_rate ?? 0) }}</strong>
        </div>
        <div class="execution-item">
          <span>盘中可盈利率</span>
          <strong>{{ formatPercent(stats?.execution_summary?.max_win_rate ?? 0) }}</strong>
        </div>
        <div class="execution-item">
          <span>盈亏比</span>
          <strong>{{ formatRatio(stats?.execution_summary?.payoff_ratio ?? 0) }}</strong>
        </div>
      </div>
    </div>

    <div class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">近期复盘</h2>
          <el-tag effect="plain">{{ stats?.selected_recent.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.selected_recent ?? []" height="320" empty-text="暂无近期复盘">
          <el-table-column prop="date" label="日期" min-width="120" />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="最高收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_max_return ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="最低回撤" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_min_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按状态</h2>
          <el-tag effect="plain">{{ stats?.by_status.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_status ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="最高收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_max_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按模式</h2>
          <el-tag effect="plain">{{ stats?.by_mode?.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_mode ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="开盘胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.open_win_rate ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="收盘胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="最高收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_max_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按可信度</h2>
          <el-tag effect="plain">{{ stats?.by_confidence?.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_confidence ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分层" min-width="140" show-overflow-tooltip />
          <el-table-column prop="count" label="样本" width="90" align="right" />
          <el-table-column label="开盘胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.open_win_rate ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="收盘胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="最高收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_max_return ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="最低回撤" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_min_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按量比确认</h2>
          <el-tag effect="plain">{{ stats?.by_volume_ratio?.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_volume_ratio ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分层" min-width="140" show-overflow-tooltip />
          <el-table-column prop="count" label="样本" width="90" align="right" />
          <el-table-column label="开盘胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.open_win_rate ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="收盘胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="平均收盘" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="最低回撤" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_min_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按尾盘形态</h2>
          <el-tag effect="plain">{{ stats?.by_tail_return?.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_tail_return ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分层" min-width="140" show-overflow-tooltip />
          <el-table-column prop="count" label="样本" width="90" align="right" />
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="最高收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_max_return ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="最低回撤" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_min_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">按信号层</h2>
          <el-tag effect="plain">{{ stats?.by_layer.length ?? 0 }}</el-tag>
        </div>
        <el-table :data="stats?.by_layer ?? []" height="320" empty-text="暂无复核样本">
          <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
          <el-table-column prop="count" label="信号数" width="100" align="right" />
          <el-table-column label="胜率" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
          </el-table-column>
          <el-table-column label="开盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
          </el-table-column>
          <el-table-column label="收盘收益" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
          </el-table-column>
          <el-table-column label="最低回撤" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.avg_min_return ?? 0) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">按过滤原因</h2>
        <el-tag effect="plain">{{ stats?.by_filter_reason.length ?? 0 }} / {{ stats?.recent.length ?? 0 }}</el-tag>
      </div>
      <el-table :data="stats?.by_filter_reason ?? []" height="320" empty-text="暂无复核样本">
        <el-table-column prop="group" label="分组" min-width="160" show-overflow-tooltip />
        <el-table-column prop="count" label="信号数" width="100" align="right" />
        <el-table-column label="胜率" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.win_rate) }}</template>
        </el-table-column>
        <el-table-column label="开盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_open_return) }}</template>
        </el-table-column>
        <el-table-column label="收盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_close_return) }}</template>
        </el-table-column>
        <el-table-column label="最高收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.avg_max_return ?? 0) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">单票复盘明细</h2>
        <el-tag effect="plain">{{ stats?.details?.length ?? 0 }}</el-tag>
      </div>
      <el-table :data="stats?.details ?? []" height="420" empty-text="暂无单票复盘">
        <el-table-column prop="trade_date" label="信号日" width="120" />
        <el-table-column prop="symbol" label="股票" width="120" />
        <el-table-column prop="rank" label="排名" width="80" align="right" />
        <el-table-column label="复核状态" width="110">
          <template #default="{ row }">{{ reviewStatusText(row.review_status) }}</template>
        </el-table-column>
        <el-table-column prop="mode" label="模式" width="110" />
        <el-table-column prop="v2_layer" label="信号层" width="120" show-overflow-tooltip />
        <el-table-column prop="confidence_bucket" label="可信度" width="100" />
        <el-table-column prop="execution_label" label="表现标签" width="120" />
        <el-table-column prop="risk_label" label="回撤风险" width="100" />
        <el-table-column label="强度" width="100" align="right">
          <template #default="{ row }">{{ formatScore(row.strength) }}</template>
        </el-table-column>
        <el-table-column label="量比" width="100" align="right">
          <template #default="{ row }">{{ formatRatio(row.volume_ratio ?? 0) }}</template>
        </el-table-column>
        <el-table-column label="信号收盘" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.signal_close) }}</template>
        </el-table-column>
        <el-table-column label="次日开盘" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.next_open) }}</template>
        </el-table-column>
        <el-table-column label="次日最高" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.next_high) }}</template>
        </el-table-column>
        <el-table-column label="次日最低" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.next_low) }}</template>
        </el-table-column>
        <el-table-column label="当前价" width="100" align="right">
          <template #default="{ row }">{{ formatPrice(row.current_price) }}</template>
        </el-table-column>
        <el-table-column label="当前收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.current_return) }}</template>
        </el-table-column>
        <el-table-column label="开盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.open_return) }}</template>
        </el-table-column>
        <el-table-column label="最高收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.max_return) }}</template>
        </el-table-column>
        <el-table-column label="最低回撤" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.min_return) }}</template>
        </el-table-column>
        <el-table-column label="收盘收益" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.close_return) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type TailSignalStatsResponse } from '../api/client'

const loading = ref(false)
const reviewingOutcomes = ref(false)
const stats = ref<TailSignalStatsResponse | null>(null)
const range = ref<[string, string] | null>(null)

async function loadStats() {
  loading.value = true
  try {
    stats.value = await api.getTailSignalStats(range.value?.[0], range.value?.[1])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载策略复盘失败')
  } finally {
    loading.value = false
  }
}

async function reviewOutcomes() {
  const pendingCount = stats.value?.review_plan?.pending_signal_count ?? 0
  if (!pendingCount) {
    ElMessage.info('当前没有待补算的正式选股复盘')
    return
  }
  reviewingOutcomes.value = true
  try {
    const result = await api.reviewTailSignalOutcomes({
      mode: 'pending',
      start: range.value?.[0] ?? null,
      end: range.value?.[1] ?? null
    })
    ElMessage.success(`补算完成：${result.date_count ?? 0} 日，${result.outcome_count} 条，缺失 ${result.missing_symbols.length} 条`)
    await loadStats()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '补算复盘失败')
  } finally {
    reviewingOutcomes.value = false
  }
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function formatRatio(value: number) {
  return value ? value.toFixed(2) : '-'
}

function formatPrice(value: number) {
  return value ? value.toFixed(2) : '-'
}

function formatScore(value?: number | null) {
  if (value == null) return '-'
  return value.toFixed(2)
}

function reviewStatusText(value: string) {
  if (value === 'completed') return '已完成'
  if (value === 'live_tracking') return '盘中跟踪'
  if (value === 'pending_outcome') return '待复核'
  return value || '-'
}

onMounted(loadStats)
</script>

<style scoped>
.execution-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.execution-item {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  display: flex;
  justify-content: space-between;
  padding: 12px;
}

.execution-item span {
  color: #606266;
}

.execution-item strong {
  color: #303133;
}

.review-plan-panel {
  margin-top: 14px;
}

.panel-subtitle {
  color: #909399;
  font-size: 13px;
  margin: 4px 0 0;
}

@media (max-width: 900px) {
  .execution-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .execution-grid {
    grid-template-columns: 1fr;
  }
}
</style>
