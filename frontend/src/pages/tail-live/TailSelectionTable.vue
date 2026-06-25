<template>
  <el-table :data="rows" height="420" :empty-text="emptyText">
    <el-table-column type="expand">
      <template #default="{ row }">
        <div class="credibility-detail">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="规则分">{{ row.credibility?.rule_score ?? row.credibility?.score ?? '-' }} / 100（{{ row.credibility?.rule_grade ?? row.credibility?.grade ?? '-' }}）</el-descriptions-item>
            <el-descriptions-item label="校准概率">{{ formatPercent(row.credibility?.calibrated_probability) }}</el-descriptions-item>
            <el-descriptions-item v-if="row.model" label="模型版本">{{ row.model.model_version ?? '-' }}</el-descriptions-item>
            <el-descriptions-item v-if="row.model" label="模型分">{{ formatScore(row.model.model_score) }}，命中 {{ formatPercent(row.model.hit_probability) }}</el-descriptions-item>
            <el-descriptions-item label="阶段">{{ row.credibility?.phase ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="历史胜率">{{ formatPercent(row.credibility?.historical_hit_rate) }}</el-descriptions-item>
            <el-descriptions-item label="原始排名">{{ row.raw_rank ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="历史平均收益">{{ formatPercent(row.credibility?.historical_avg_return) }}</el-descriptions-item>
            <el-descriptions-item label="历史冲高/回撤">{{ formatPercent(row.credibility?.history?.max_win_rate) }} / {{ formatPercent(row.credibility?.history?.avg_min_return) }}</el-descriptions-item>
            <el-descriptions-item v-if="row.model" label="模型收益/风险">{{ formatPercent(row.model.expected_high_return) }} / {{ formatPercent(row.model.risk_probability) }}</el-descriptions-item>
            <el-descriptions-item v-if="row.model" label="模型因子">{{ modelFeatureText(row.model.feature_snapshot) }}</el-descriptions-item>
            <el-descriptions-item label="候选排名">{{ row.final_candidate_rank ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="信号强度">{{ formatScore(row.credibility?.components?.signal_strength) }}</el-descriptions-item>
            <el-descriptions-item label="量能质量">{{ formatScore(row.credibility?.components?.volume_quality) }}</el-descriptions-item>
            <el-descriptions-item label="涨幅质量">{{ formatScore(row.credibility?.components?.return_quality) }}</el-descriptions-item>
            <el-descriptions-item label="历史样本">{{ row.credibility?.sample_size ?? row.credibility?.history?.sample_count ?? 0 }}，{{ row.credibility?.history_status ?? row.credibility?.history?.status ?? '-' }}：{{ row.credibility?.history?.note ?? '-' }}</el-descriptions-item>
          </el-descriptions>
          <div class="credibility-lists">
            <div>
              <div class="metric-label">确认条件</div>
              <ul>
                <li v-for="item in row.credibility?.confirmation_checks ?? []" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div>
              <div class="metric-label">主要风险</div>
              <ul>
                <li v-for="item in row.credibility?.risks ?? []" :key="item">{{ item }}</li>
              </ul>
            </div>
          </div>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="股票" min-width="120">
      <template #default="{ row }">
        <el-button link type="primary" @click="$emit('openStockTrend', row.symbol)">{{ row.symbol }}</el-button>
      </template>
    </el-table-column>
    <el-table-column label="规则分" width="120" align="right">
      <template #default="{ row }">
        <el-tag :type="credibilityType(row.credibility?.rule_score ?? row.credibility?.score)" effect="plain">
          {{ row.credibility?.rule_score ?? row.credibility?.score ?? '-' }} {{ row.credibility?.rule_grade ?? row.credibility?.grade ?? '' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column v-if="hasModelScores" label="模型" width="136" align="right">
      <template #default="{ row }">
        <div class="metric-stack">
          <strong>{{ formatScore(row.model?.model_score) }}</strong>
          <span>{{ formatPercent(row.model?.hit_probability) }}</span>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="校准概率" width="120" align="right">
      <template #default="{ row }">{{ formatPercent(row.credibility?.calibrated_probability) }}</template>
    </el-table-column>
    <el-table-column label="强度" width="110" align="right">
      <template #default="{ row }">{{ formatScore(row.strength) }}</template>
    </el-table-column>
    <el-table-column label="最新价" width="110" align="right">
      <template #default="{ row }">{{ formatPrice(row.last_price) }}</template>
    </el-table-column>
    <el-table-column label="量比" width="110" align="right">
      <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
    </el-table-column>
    <el-table-column label="尾盘涨幅" width="120" align="right">
      <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
    </el-table-column>
    <el-table-column label="可执行性" width="120" align="right">
      <template #default="{ row }">
        <el-tag :type="executionFlagType(row.tradability?.execution_flag)" effect="plain">
          {{ executionFlagText(row.tradability?.execution_flag) }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="涨停距离" width="120" align="right">
      <template #default="{ row }">{{ formatPercent(row.tradability?.limit_up_distance) }}</template>
    </el-table-column>
    <el-table-column label="次日卖出" min-width="150">
      <template #default="{ row }">{{ sellPolicyText(row.next_day_plan?.sell_policy) }}</template>
    </el-table-column>
    <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
  </el-table>
</template>

<script setup lang="ts">
interface ModelFeatureSnapshot {
  feature: string
  value: number | null
}

interface TailSelectionRow {
  raw_rank?: number | null
  final_candidate_rank?: number | null
  symbol: string
  strength: number
  last_price: number
  volume_ratio: number
  tail_return: number
  reason: string
  credibility?: {
    score?: number
    grade?: string
    rule_score?: number
    rule_grade?: string
    historical_hit_rate?: number | null
    historical_avg_return?: number | null
    sample_size?: number
    calibrated_probability?: number | null
    history_status?: string
    phase?: string
    components?: {
      signal_strength?: number
      volume_quality?: number
      return_quality?: number
    }
    confirmation_checks?: string[]
    risks?: string[]
    history?: {
      status?: string
      sample_count?: number
      note?: string
      max_win_rate?: number
      avg_min_return?: number
    }
  }
  tradability?: {
    execution_flag?: string | null
    limit_up_distance?: number | null
  }
  next_day_plan?: {
    sell_policy?: string
  }
  model?: {
    model_version?: string | null
    model_score?: number | null
    hit_probability?: number | null
    expected_high_return?: number | null
    risk_probability?: number | null
    feature_snapshot?: ModelFeatureSnapshot[]
  }
}

defineProps<{
  rows: TailSelectionRow[]
  emptyText: string
  hasModelScores: boolean
}>()

defineEmits<{
  openStockTrend: [symbol: string]
}>()

function formatScore(value: unknown) {
  return typeof value === 'number' ? value.toFixed(4) : '-'
}

function formatPrice(value: unknown) {
  return typeof value === 'number' ? value.toFixed(2) : '-'
}

function formatPercent(value: unknown) {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-'
}

function credibilityType(score: unknown) {
  if (typeof score !== 'number') return 'info'
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
}

function executionFlagText(value: unknown) {
  if (value === 'blocked_limit_up') return '涨停不可买'
  if (value === 'near_limit_up') return '接近涨停'
  if (value === 'executable') return '可执行'
  return '未知'
}

function executionFlagType(value: unknown) {
  if (value === 'blocked_limit_up') return 'danger'
  if (value === 'near_limit_up') return 'warning'
  if (value === 'executable') return 'success'
  return 'info'
}

function sellPolicyText(value: unknown) {
  if (value === 'open_or_morning_strength') return '开盘/早盘强弱卖'
  return value ? String(value) : '-'
}

const modelFeatureLabels: Record<string, string> = {
  daily_ret_5: '5日涨幅',
  daily_ret_10: '10日涨幅',
  daily_ret_20: '20日涨幅',
  daily_volatility_20: '20日波动',
  ma5_distance: 'MA5距离',
  ma20_distance: 'MA20距离',
  avg_amount_20: '20日成交额',
  amount_ratio_5_20: '5/20成交额',
  amount_zscore_20: '成交额热度',
  tail_return_from_1430: '尾盘涨幅',
  tail_high_return_from_1430: '尾盘高点',
  tail_pullback_from_high: '高点回撤',
  tail_volume_ratio: '尾盘量比',
  last3_close_slope: '近3根斜率',
  last6_close_slope: '近6根斜率',
  market_ret_5: '市场5日',
  market_ret_20: '市场20日',
  market_breadth_20: '市场宽度',
  relative_ret_5: '相对5日',
  relative_ret_20: '相对20日',
  industry_ret_5: '行业5日',
  industry_ret_20: '行业20日',
  industry_breadth_20: '行业宽度',
  industry_relative_ret_5: '相对行业5日',
  industry_relative_ret_20: '相对行业20日',
}

function modelFeatureText(items?: ModelFeatureSnapshot[]) {
  if (!items?.length) return '-'
  return items
    .filter((item) => typeof item.value === 'number')
    .slice(0, 8)
    .map((item) => `${modelFeatureLabels[item.feature] ?? item.feature} ${formatModelFeatureValue(item)}`)
    .join('，')
}

function formatModelFeatureValue(item: ModelFeatureSnapshot) {
  if (typeof item.value !== 'number') return '-'
  if (item.feature.includes('return') || item.feature.includes('distance') || item.feature.includes('slope') || item.feature.includes('breadth')) {
    return formatPercent(item.value)
  }
  if (item.feature.includes('amount')) return `${(item.value / 100000000).toFixed(2)}亿`
  return item.value.toFixed(2)
}
</script>
