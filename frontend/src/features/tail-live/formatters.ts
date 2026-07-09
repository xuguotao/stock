import type { ModelFeatureSnapshot, SelectionRow } from './types'

export function formatScore(value: unknown) {
  return typeof value === 'number' ? value.toFixed(4) : '-'
}

export function formatPrice(value: unknown) {
  return typeof value === 'number' ? value.toFixed(2) : '-'
}

export function formatPercent(value: unknown) {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-'
}

export function qualityCoverageText(row?: { covered_symbols: number; missing_symbols: number; coverage_ratio: number }) {
  if (!row) return '-'
  return `${row.covered_symbols ?? 0}/${(row.covered_symbols ?? 0) + (row.missing_symbols ?? 0)}，${formatPercent(row.coverage_ratio)}`
}

export function formatCompactDateTime(value: unknown) {
  if (!value) return '-'
  const text = String(value)
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/)
  if (!match) return text
  return match[4] ? `${match[2]}-${match[3]} ${match[4]}:${match[5]}` : `${match[2]}-${match[3]}`
}

export function dedupeIssues(items: string[]) {
  return Array.from(new Set(items.filter(Boolean)))
}

export function qualityTagType(status?: string) {
  if (status === 'ok') return 'success'
  if (status === 'warning' || status === 'partial') return 'warning'
  if (status === 'error' || status === 'failed' || status === 'missing') return 'danger'
  return 'info'
}

export function formatDateTime(value: string) {
  return value ? value.replace('T', ' ').slice(0, 19) : '-'
}

export function filterReasonText(value: unknown) {
  if (value === 'below_candidate_threshold') return '未达候选阈值'
  if (value === 'below_min_strength') return '低于最小强度'
  if (value === 'preview_not_final') return '未到14:50最终确认'
  if (value === 'v2_not_trade_candidate') return 'V2未达交易候选'
  if (value === 'limit_up_not_buyable') return '涨停/近涨停，无法买入'
  if (value === 'tail_pullback_risk') return '尾盘冲高回落'
  if (value === 'outside_historical_calibration_top_n') return '历史校准排名超出 Top N'
  if (value === 'outside_model_top_n') return '模型未进 Top N'
  if (value === 'outside_top_n') return '排名超出 Top N'
  if (value === 'not_selected') return '未入选'
  return '-'
}

export function strategyModeText(value: unknown) {
  if (value === 'model') return '模型排序'
  if (value === 'hybrid') return '混合模式'
  if (value === 'rule') return '规则优先'
  return '-'
}

export function modelDecisionText(row: SelectionRow) {
  if (!row.model) return '规则排序'
  if (isModelPromoted(row)) return '模型提权'
  if (isModelEliminated(row)) return '模型淘汰'
  if (row.status === 'selected') return '规则+模型一致'
  return '模型观察'
}

export function modelDecisionType(row: SelectionRow) {
  if (isModelPromoted(row)) return 'success'
  if (isModelEliminated(row)) return 'danger'
  if (row.status === 'selected') return 'warning'
  return 'info'
}

export function isModelPromoted(row: SelectionRow) {
  return Boolean(
    row.model
    && row.status === 'selected'
    && typeof row.rank === 'number'
    && typeof row.final_candidate_rank === 'number'
    && row.rank < row.final_candidate_rank
  )
}

export function isModelEliminated(row: SelectionRow) {
  return Boolean(
    row.model
    && row.status === 'filtered'
    && row.final_candidate_rank != null
    && (row.filter_reason === 'outside_model_top_n' || row.filter_reason === 'outside_top_n')
  )
}

export function candidateRankShiftText(row: SelectionRow) {
  const candidateRank = row.final_candidate_rank ?? '-'
  const finalRank = row.status === 'selected' ? row.rank ?? '-' : '未入选'
  return `${candidateRank} → ${finalRank}`
}

export function executionFlagText(value: unknown) {
  if (value === 'blocked_limit_up') return '涨停不可买'
  if (value === 'near_limit_up') return '接近涨停'
  if (value === 'executable') return '可执行'
  return '未知'
}

export function executionFlagType(value: unknown) {
  if (value === 'blocked_limit_up') return 'danger'
  if (value === 'near_limit_up') return 'warning'
  if (value === 'executable') return 'success'
  return 'info'
}

export function v2LayerText(value: unknown) {
  if (value === 'strong') return '强确认'
  if (value === 'watchlist') return '观察'
  if (value === 'weak') return '弱信号'
  return '-'
}

export function v2LayerType(value: unknown) {
  if (value === 'strong') return 'success'
  if (value === 'watchlist') return 'warning'
  if (value === 'weak') return 'info'
  return 'info'
}

export function v2ActionText(value: unknown) {
  if (value === 'trade_candidate') return '可进入最终交易候选'
  if (value === 'observe_next_open') return '次日开盘/早盘观察'
  if (value === 'no_trade') return '不交易，仅解释'
  return '-'
}

export function credibilityType(value: unknown) {
  if (typeof value !== 'number') return 'info'
  if (value >= 75) return 'success'
  if (value >= 55) return 'warning'
  return 'danger'
}

export function precheckDataStatusText(value: unknown) {
  if (value === 'has_intraday_data') return '有分钟数据'
  if (value === 'missing_intraday_data') return '缺分钟数据'
  return '-'
}

export function precheckStageText(value: unknown) {
  if (value === 'waiting_tail_window') return '等待尾盘窗口'
  if (value === 'waiting_data') return '等待数据'
  return '-'
}

export function sellPolicyText(value: unknown) {
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

export function modelFeatureText(items?: ModelFeatureSnapshot[]) {
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
