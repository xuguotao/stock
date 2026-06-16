<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">今日尾盘选股</h1>
      <div class="toolbar">
        <el-button :loading="submitting" type="primary" @click="submit">运行选股</el-button>
        <el-button :disabled="!activeJobId" @click="refreshJob">刷新结果</el-button>
      </div>
    </div>

    <div class="panel">
      <el-form :model="form" label-width="130px">
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="交易日">
              <el-date-picker
                v-model="form.trade_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择交易日"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="股票池">
              <el-select v-model="form.universe">
                <el-option label="本地流动性池" value="liquid-cache" />
                <el-option label="默认池" value="default" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="扫描数量">
              <el-input-number v-model="form.limit" :min="1" :max="500" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Top N">
              <el-input-number v-model="form.top_n" :min="1" :max="50" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="确认次数">
              <el-input-number v-model="form.confirmations" :min="1" :max="10" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最小强度">
              <el-input-number v-model="form.min_strength" :min="0" :max="1" :step="0.05" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="市场宽度阈值">
              <el-input-number
                v-model="form.min_market_breadth_above_ma20"
                :min="0"
                :max="1"
                :step="0.05"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="允许盘外试跑">
              <el-switch v-model="form.ignore_session" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="手动股票">
              <el-select
                v-model="manualSymbols"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="可选，输入 000001 或 000001.SZ"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最少日线数">
              <el-input-number v-model="form.liquidity_min_bars" :min="1" :max="500" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="输出目录">
              <el-input v-model="form.output_dir" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div v-if="job" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">当前任务</div>
          <div class="summary-title">{{ job.id }}</div>
        </div>
        <el-tag :type="statusType(job.status)" effect="plain">{{ job.status }}</el-tag>
        <el-tag v-if="job.error" type="danger" effect="plain">{{ job.error }}</el-tag>
      </div>
      <div class="job-progress-panel">
        <el-progress :percentage="jobProgressPercent" :status="jobProgressStatus" :stroke-width="10" />
        <div class="progress-message">{{ job.progress?.message ?? '-' }}</div>
      </div>
    </div>

    <div v-if="result" class="metric-grid">
      <div class="metric-card" v-for="item in summaryItems" :key="item.label">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
      </div>
    </div>

    <div v-if="diagnostics" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">{{ diagnosticsPanelLabel }}</div>
          <div class="summary-title">{{ emptyReasonText }}</div>
        </div>
        <el-tag :type="resultMode === 'precheck' ? 'warning' : 'success'" effect="plain">
          {{ resultModeText }}
        </el-tag>
        <el-tag effect="plain">分钟数据 {{ diagnostics.has_intraday_data_count ?? 0 }} / {{ diagnostics.checked_intraday_count ?? 0 }}</el-tag>
        <el-tag effect="plain">扫描 {{ diagnostics.resolved_scan_count ?? result?.scanned_count ?? 0 }} / {{ diagnostics.requested_scan_limit ?? form.limit }}</el-tag>
        <el-tag v-if="diagnostics.latest_intraday_time" effect="plain">最新分钟 {{ diagnostics.latest_intraday_time }}</el-tag>
        <el-tag v-if="diagnostics.scan_as_of_time" effect="plain">扫描截至 {{ diagnostics.scan_as_of_time }}</el-tag>
        <el-tag effect="plain">可评分 {{ diagnostics.scoreable_count ?? 0 }}</el-tag>
        <el-tag effect="plain">不可评分 {{ diagnostics.unscoreable_count ?? 0 }}</el-tag>
        <el-tag effect="plain">候选 {{ diagnostics.candidate_count }}</el-tag>
        <el-tag effect="plain">确认 {{ diagnostics.confirmed_count }}</el-tag>
      </div>
      <div v-if="diagnostics.empty_message" class="diagnostic-message">
        {{ diagnostics.empty_message }}
      </div>
      <div class="diagnostic-tags">
        <el-tag
          v-for="symbol in diagnostics.scan_universe_preview"
          :key="symbol"
          effect="plain"
        >
          {{ symbol }}
        </el-tag>
      </div>
      <div v-if="diagnostics.missing_intraday_symbols?.length" class="diagnostic-message muted">
        缺分钟数据：{{ diagnostics.missing_intraday_symbols.join(', ') }}
      </div>
    </div>

    <div v-if="result" class="tail-result-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">{{ strategyPanelTitle }}</h2>
          <el-tag effect="plain">{{ strategyRows.length }}</el-tag>
        </div>
        <el-table v-if="resultMode === 'precheck'" :data="precheckRows" height="420" :empty-text="strategyEmptyText">
          <el-table-column prop="rank" label="排名" width="72" />
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="数据状态" width="130">
            <template #default="{ row }">
              <el-tag :type="row.data_status === 'has_intraday_data' ? 'success' : 'danger'" effect="plain">
                {{ precheckDataStatusText(row.data_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="latest_intraday_time" label="最新分钟" width="120" />
          <el-table-column label="阶段" width="140">
            <template #default="{ row }">{{ precheckStageText(row.stage) }}</template>
          </el-table-column>
          <el-table-column label="原因" min-width="260">
            <template #default="{ row }">{{ row.explanation }}</template>
          </el-table-column>
        </el-table>
        <el-table v-else :data="rankedSignals" height="420" :empty-text="strategyEmptyText">
          <el-table-column prop="rank" label="排名" width="72" />
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="层级" width="110">
            <template #default="{ row }">
              <el-tag :type="v2LayerType(row.v2_layer)" effect="plain">
                {{ v2LayerText(row.v2_layer) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row.status === 'selected' ? 'success' : 'info'" effect="plain">
                {{ row.status === 'selected' ? '入选' : '过滤' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="强度" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.strength) }}</template>
          </el-table-column>
          <el-table-column label="V2分" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.v2_score) }}</template>
          </el-table-column>
          <el-table-column label="可信度" width="120" align="right">
            <template #default="{ row }">
              <el-tag :type="credibilityType(row.credibility?.score)" effect="plain">
                {{ row.credibility?.score ?? '-' }} {{ row.credibility?.grade ?? '' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="量比" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column label="资金/价格" width="120" align="right">
            <template #default="{ row }">
              {{ formatScore(row.v2_breakdown?.tail_money) }} / {{ formatScore(row.v2_breakdown?.price_action) }}
            </template>
          </el-table-column>
          <el-table-column label="过滤原因" min-width="150">
            <template #default="{ row }">{{ filterReasonText(row.filter_reason) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">{{ resultMode === 'preview' ? '盘中预演入选' : '最终选股' }}</h2>
          <el-tag effect="plain">{{ selections.length }}</el-tag>
        </div>
        <div v-if="resultMode === 'precheck'" class="selection-explain">
          <el-alert
            title="预检阶段不会产生最终选股"
            :description="selectionEmptyText"
            type="warning"
            show-icon
            :closable="false"
          />
          <el-descriptions :column="1" border>
            <el-descriptions-item label="当前最新分钟">{{ diagnostics?.latest_intraday_time ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="缺少数据">14:30-15:00 尾盘 5 分钟 K</el-descriptions-item>
            <el-descriptions-item label="无法计算">尾盘涨幅、尾盘量比、连续确认、最终排序</el-descriptions-item>
            <el-descriptions-item label="下一步">14:30 后重新运行，系统会进入正式尾盘评分</el-descriptions-item>
          </el-descriptions>
        </div>
        <el-table v-else :data="selections" height="420" :empty-text="selectionEmptyText">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="credibility-detail">
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="可信度">{{ row.credibility?.score ?? '-' }} / 100（{{ row.credibility?.grade ?? '-' }}）</el-descriptions-item>
                  <el-descriptions-item label="阶段">{{ row.credibility?.phase ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="信号强度">{{ formatScore(row.credibility?.components?.signal_strength) }}</el-descriptions-item>
                  <el-descriptions-item label="量能质量">{{ formatScore(row.credibility?.components?.volume_quality) }}</el-descriptions-item>
                  <el-descriptions-item label="涨幅质量">{{ formatScore(row.credibility?.components?.return_quality) }}</el-descriptions-item>
                  <el-descriptions-item label="历史样本">{{ row.credibility?.history?.status ?? '-' }}：{{ row.credibility?.history?.note ?? '-' }}</el-descriptions-item>
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
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="可信度" width="120" align="right">
            <template #default="{ row }">
              <el-tag :type="credibilityType(row.credibility?.score)" effect="plain">
                {{ row.credibility?.score ?? '-' }} {{ row.credibility?.grade ?? '' }}
              </el-tag>
            </template>
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
          <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">候选观察池</h2>
          <el-tag effect="plain">{{ watchlistSignals.length }}</el-tag>
        </div>
        <el-table :data="watchlistSignals" height="300" empty-text="暂无候选观察信号">
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="V2分" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.v2_score) }}</template>
          </el-table-column>
          <el-table-column label="量比" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column label="动作" min-width="160">
            <template #default="{ row }">{{ v2ActionText(row.v2_action) }}</template>
          </el-table-column>
          <el-table-column prop="v2_explanation" label="说明" min-width="260" show-overflow-tooltip />
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">弱信号池</h2>
          <el-tag effect="plain">{{ weakSignals.length }}</el-tag>
        </div>
        <el-table :data="weakSignals" height="300" empty-text="暂无弱信号">
          <el-table-column prop="symbol" label="股票" min-width="120" />
          <el-table-column label="V2分" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.v2_score) }}</template>
          </el-table-column>
          <el-table-column label="量比" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="110" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column label="主要风险" min-width="260">
            <template #default="{ row }">{{ row.v2_risks?.join('；') || '-' }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">策略说明</h2>
          <el-tag effect="plain">{{ resultModeText }}</el-tag>
        </div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="股票池">{{ strategyRules?.universe ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="数据要求">{{ strategyRules?.bar_frequency ?? '5m' }} 覆盖 {{ strategyRules?.tail_window ?? '14:30-15:00' }}</el-descriptions-item>
          <el-descriptions-item label="盘中预演">最新 {{ strategyRules?.preview_window_bars ?? '-' }} 根 5 分钟 K 先行评分，正式尾盘后复核</el-descriptions-item>
          <el-descriptions-item label="候选条件">量比 >= {{ strategyRules?.volume_ratio_threshold ?? '-' }}，尾盘涨幅 >= {{ formatPercent(strategyRules?.min_tail_return) }}</el-descriptions-item>
          <el-descriptions-item label="确认条件">连续确认 {{ strategyRules?.confirmations ?? '-' }} 次</el-descriptions-item>
          <el-descriptions-item label="最终过滤">Top {{ strategyRules?.top_n ?? '-' }}，最小强度 {{ strategyRules?.min_strength ?? '未设置' }}，市场宽度 {{ strategyRules?.min_market_breadth_above_ma20 ?? '未设置' }}</el-descriptions-item>
          <el-descriptions-item label="排序方法">{{ strategyRules?.ranking ?? '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">输出文件</h2>
          <el-tag effect="plain">{{ result.trade_date }}</el-tag>
        </div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="JSON">{{ result.files?.json ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="CSV">{{ result.files?.csv ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="日报">{{ result.files?.report ?? '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type JobRecord, type JobStatus, type TailLiveSelectionPayload } from '../api/client'

interface SelectionRow {
  rank?: number
  symbol: string
  trade_date: string
  strength: number
  last_price: number
  volume_ratio: number
  tail_return: number
  reason: string
  status?: 'selected' | 'filtered'
  filter_reason?: string | null
  v2_score?: number
  v2_layer?: 'strong' | 'watchlist' | 'weak'
  v2_action?: 'trade_candidate' | 'observe_next_open' | 'no_trade'
  v2_explanation?: string
  v2_risks?: string[]
  v2_breakdown?: {
    tail_money: number
    price_action: number
    liquidity: number
    risk_control: number
  }
  credibility?: Credibility
}

interface Credibility {
  score: number
  grade: '高' | '中' | '低'
  phase: string
  components: {
    signal_strength: number
    volume_quality: number
    return_quality: number
    phase_discount: number
  }
  confirmation_checks: string[]
  risks: string[]
  history: {
    status: string
    sample_count: number
    note: string
  }
}

interface PrecheckRow {
  rank: number
  symbol: string
  data_status: 'has_intraday_data' | 'missing_intraday_data'
  latest_intraday_time: string | null
  stage: 'waiting_tail_window' | 'waiting_data'
  filter_reason: string
  explanation: string
}

interface StrategyRules {
  universe: string
  tail_window: string
  bar_frequency: string
  preview_window_bars: number
  volume_ratio_threshold: number
  min_tail_return: number
  confirmations: number
  top_n: number
  min_strength: number | null
  min_market_breadth_above_ma20: number | null
  ranking: string
}

interface TailLiveResult {
  mode?: 'precheck' | 'preview' | 'selection'
  trade_date: string
  scanned_count: number
  candidate_count: number
  confirmed_count: number
  selected_count: number
  preview_count?: number
  selections: SelectionRow[]
  preview_signals?: SelectionRow[]
  ranked_signals?: SelectionRow[]
  signal_layers?: {
    strong: number
    watchlist: number
    weak: number
  }
  watchlist_signals?: SelectionRow[]
  weak_signals?: SelectionRow[]
  precheck_rows?: PrecheckRow[]
  strategy_rules?: StrategyRules
  files: Record<string, string>
  market_breadth: { breadth: number; above_count: number; symbol_count: number } | null
  diagnostics?: {
    empty_reason: string | null
    empty_message: string | null
    scan_universe_preview: string[]
    has_intraday_data_count: number
    checked_intraday_count: number
    missing_intraday_symbols: string[]
    latest_intraday_time: string | null
    scan_as_of_time?: string | null
    scoreable_count: number
    unscoreable_count: number
    candidate_count: number
    confirmed_count: number
    selected_count: number
    blocked_by_market_breadth: boolean
    requested_scan_limit?: number
    resolved_scan_count?: number
  }
}

const props = defineProps<{
  jobId?: string
}>()

const today = new Date().toISOString().slice(0, 10)
const form = ref<TailLiveSelectionPayload>({
  trade_date: today,
  symbols: null,
  limit: 200,
  universe: 'liquid-cache',
  bars_cache_dir: 'data/cache/bars',
  liquidity_min_bars: 60,
  min_market_breadth_above_ma20: null,
  confirmations: 1,
  top_n: 5,
  min_strength: null,
  ignore_session: true,
  output_dir: 'reports/tail_session'
})

const manualSymbols = ref<string[]>([])
const submitting = ref(false)
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const result = computed(() => (job.value?.result ?? null) as unknown as TailLiveResult | null)
const resultMode = computed(() => result.value?.mode ?? 'selection')
const resultModeText = computed(() => {
  if (resultMode.value === 'precheck') return '数据预检'
  if (resultMode.value === 'preview') return '盘中预演'
  return '尾盘评分'
})
const diagnosticsPanelLabel = computed(() => resultMode.value === 'selection' ? '结果诊断' : resultModeText.value)
const strategyPanelTitle = computed(() => {
  if (resultMode.value === 'precheck') return '预检待评分池'
  if (resultMode.value === 'preview') return '盘中预演排序池'
  return '策略排序池'
})
const finalSelections = computed(() => result.value?.selections ?? [])
const previewSignals = computed(() => result.value?.preview_signals ?? [])
const selections = computed(() => resultMode.value === 'preview' ? previewSignals.value : finalSelections.value)
const rankedSignals = computed(() => result.value?.ranked_signals ?? [])
const watchlistSignals = computed(() => result.value?.watchlist_signals ?? [])
const weakSignals = computed(() => result.value?.weak_signals ?? [])
const signalLayers = computed(() => result.value?.signal_layers ?? { strong: 0, watchlist: 0, weak: 0 })
const precheckRows = computed(() => result.value?.precheck_rows ?? [])
const strategyRows = computed(() => resultMode.value === 'precheck' ? precheckRows.value : rankedSignals.value)
const strategyRules = computed(() => result.value?.strategy_rules ?? null)
const diagnostics = computed(() => result.value?.diagnostics ?? null)
const emptyReasonText = computed(() => {
  const reason = diagnostics.value?.empty_reason
  if (!reason) return selections.value.length ? '已选出信号' : '未发现异常'
  if (reason === 'scan_universe_empty') return '股票池为空'
  if (reason === 'blocked_by_market_breadth') return '市场宽度拦截'
  if (reason === 'intraday_preview') return '盘中预演结果'
  if (reason === 'tail_window_not_available') return '尾盘数据未出现'
  if (reason === 'no_scoreable_intraday_data') return '无可评分尾盘分钟数据'
  if (reason === 'no_intraday_candidates') return '没有尾盘候选信号'
  if (reason === 'no_confirmed_signals') return '候选未连续确认'
  if (reason === 'filtered_by_selection_rules') return '被强度/Top N 过滤'
  return reason
})
const jobProgressPercent = computed(() => Math.max(0, Math.min(100, Number(job.value?.progress?.percent ?? 0))))
const jobProgressStatus = computed(() => {
  if (job.value?.status === 'success') return 'success'
  if (job.value?.status === 'failed') return 'exception'
  return undefined
})
const strategyEmptyText = computed(() => {
  const reason = diagnostics.value?.empty_reason
  if (reason === 'tail_window_not_available') return '尾盘数据未出现，请在 14:30 后重新运行'
  if (reason === 'no_scoreable_intraday_data') return '无可评分尾盘分钟数据，请检查实时数据源或分钟数据是否覆盖 14:30-15:00'
  if (reason === 'scan_universe_empty') return '股票池为空'
  if (reason === 'blocked_by_market_breadth') return '市场宽度未达标，本次未扫描'
  return '暂无策略排序'
})
const selectionEmptyText = computed(() => {
  if (!result.value) return '暂无选股结果'
  if (resultMode.value === 'precheck') return '当前处于数据预检阶段，14:30 后再生成最终选股'
  if (resultMode.value === 'preview') return '盘中预演未产生临时入选，14:30 后仍需正式复核'
  if (rankedSignals.value.length > 0) return '最终条件未通过，请查看左侧策略排序池'
  return diagnostics.value?.empty_message ?? '暂无最终选股'
})
const summaryItems = computed(() => [
  { label: '运行模式', value: resultModeText.value },
  { label: '扫描数', value: String(result.value?.scanned_count ?? '-') },
  { label: '分钟覆盖', value: diagnostics.value ? `${diagnostics.value.has_intraday_data_count ?? 0}/${diagnostics.value.checked_intraday_count ?? 0}` : '-' },
  { label: '最新分钟', value: diagnostics.value?.latest_intraday_time ?? '-' },
  { label: '扫描截至', value: diagnostics.value?.scan_as_of_time ?? '-' },
  { label: '可评分', value: String(diagnostics.value?.scoreable_count ?? 0) },
  { label: '强确认/观察/弱', value: `${signalLayers.value.strong}/${signalLayers.value.watchlist}/${signalLayers.value.weak}` },
  { label: resultMode.value === 'precheck' ? '等待原因' : resultMode.value === 'preview' ? '预演入选' : '最终选股', value: resultMode.value === 'precheck' ? emptyReasonText.value : resultMode.value === 'preview' ? String(result.value?.preview_count ?? 0) : String(result.value?.selected_count ?? '-') },
  { label: '交易日', value: result.value?.trade_date ?? '-' }
])

async function submit() {
  submitting.value = true
  try {
    const response = await api.submitTailLiveSelection({
      ...form.value,
      symbols: manualSymbols.value.length ? manualSymbols.value : null
    })
    activeJobId.value = response.job_id
    const completed = await pollJobUntilDone(response.job_id)
    if (completed) ElMessage.success('今日尾盘选股完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
}

async function loadJob(jobId: string) {
  activeJobId.value = jobId
  await refreshJob()
}

async function pollJobUntilDone(jobId: string) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    job.value = await api.getJob(jobId)
    if (job.value.status === 'success') return true
    if (job.value.status === 'failed') {
      ElMessage.error(job.value.error ?? '今日尾盘选股失败')
      return false
    }
    await sleep(500)
  }
  ElMessage.warning('任务仍在运行，请稍后刷新')
  return false
}

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function formatScore(value: unknown) {
  return typeof value === 'number' ? value.toFixed(4) : '-'
}

function formatPrice(value: unknown) {
  return typeof value === 'number' ? value.toFixed(2) : '-'
}

function formatPercent(value: unknown) {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-'
}

function filterReasonText(value: unknown) {
  if (value === 'below_candidate_threshold') return '未达候选阈值'
  if (value === 'below_min_strength') return '低于最小强度'
  if (value === 'preview_not_final') return '未到14:50最终确认'
  if (value === 'v2_not_trade_candidate') return 'V2未达交易候选'
  if (value === 'outside_top_n') return '排名超出 Top N'
  if (value === 'not_selected') return '未入选'
  return '-'
}

function v2LayerText(value: unknown) {
  if (value === 'strong') return '强确认'
  if (value === 'watchlist') return '观察'
  if (value === 'weak') return '弱信号'
  return '-'
}

function v2LayerType(value: unknown) {
  if (value === 'strong') return 'success'
  if (value === 'watchlist') return 'warning'
  if (value === 'weak') return 'info'
  return 'info'
}

function v2ActionText(value: unknown) {
  if (value === 'trade_candidate') return '可进入最终交易候选'
  if (value === 'observe_next_open') return '次日开盘/早盘观察'
  if (value === 'no_trade') return '不交易，仅解释'
  return '-'
}

function credibilityType(value: unknown) {
  if (typeof value !== 'number') return 'info'
  if (value >= 75) return 'success'
  if (value >= 55) return 'warning'
  return 'danger'
}

function precheckDataStatusText(value: unknown) {
  if (value === 'has_intraday_data') return '有分钟数据'
  if (value === 'missing_intraday_data') return '缺分钟数据'
  return '-'
}

function precheckStageText(value: unknown) {
  if (value === 'waiting_tail_window') return '等待尾盘窗口'
  if (value === 'waiting_data') return '等待数据'
  return '-'
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

watch(
  () => props.jobId,
  (jobId) => {
    if (jobId) void loadJob(jobId)
  },
  { immediate: true }
)
</script>
