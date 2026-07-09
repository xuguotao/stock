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
    <el-table-column v-if="hasModelScores" label="模型决策" width="126">
      <template #default="{ row }">
        <el-tag :type="modelDecisionType(row)" effect="plain">
          {{ modelDecisionText(row) }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column v-if="hasModelScores" label="规则候选→最终" width="132" align="center">
      <template #default="{ row }">{{ candidateRankShiftText(row) }}</template>
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
    <el-table-column v-if="hasModelScores" label="模型收益/风险" width="148" align="right">
      <template #default="{ row }">
        <div class="metric-stack">
          <strong>{{ formatPercent(row.model?.expected_high_return) }}</strong>
          <span>风险 {{ formatPercent(row.model?.risk_probability) }}</span>
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
import {
  candidateRankShiftText,
  credibilityType,
  executionFlagText,
  executionFlagType,
  formatPercent,
  formatPrice,
  formatScore,
  modelDecisionText,
  modelDecisionType,
  modelFeatureText,
  sellPolicyText,
} from '../../features/tail-live/formatters'
import type { SelectionRow } from '../../features/tail-live/types'

defineProps<{
  rows: SelectionRow[]
  emptyText: string
  hasModelScores: boolean
}>()

defineEmits<{
  openStockTrend: [symbol: string]
}>()
</script>
