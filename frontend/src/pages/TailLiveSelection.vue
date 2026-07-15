<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">今日尾盘选股</h1>
      <div class="toolbar">
        <el-button :loading="submitting" type="primary" @click="submit">运行选股</el-button>
        <el-button :loading="loadingDataHealth" @click="loadDataHealth">刷新健康度</el-button>
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
                <el-option label="全市场非ST" value="default" />
                <el-option label="流动性排序池" value="liquid-cache" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="扫描数量">
              <el-input-number v-model="form.limit" :min="0" :max="6000" />
              <div class="form-item-hint">{{ scanLimitDisplayText }}</div>
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
            <el-form-item label="数据刷新模式">
              <el-select v-model="form.data_refresh_mode">
                <el-option label="自动快速" value="auto" />
                <el-option label="快照优先" value="snapshot" />
                <el-option label="标准5m" value="standard_minute5" />
                <el-option label="不刷新" value="none" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="策略模式">
              <el-select v-model="form.strategy_mode">
                <el-option label="规则优先" value="rule" />
                <el-option label="模型排序" value="model" />
                <el-option label="混合模式" value="hybrid" />
              </el-select>
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

    <TailDataHealthPanel
      :status="dataHealth?.quality?.status"
      :update-text="dataHealthUpdateText"
      :items="dataHealthItems"
      :issues="dataHealthIssues"
    />

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">运行记录</h2>
        <div class="toolbar">
          <el-tag effect="plain">{{ runHistory.length }}</el-tag>
          <el-button :loading="loadingHistory" @click="loadRunHistory">刷新记录</el-button>
        </div>
      </div>
      <el-table
        :data="runHistory"
        height="260"
        highlight-current-row
        empty-text="暂无运行记录"
        @row-click="selectRunHistory"
      >
        <el-table-column label="运行时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="交易日" width="120">
          <template #default="{ row }">{{ row.params?.trade_date ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模式" width="110">
          <template #default="{ row }">{{ row.result?.mode ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="扫描/入选" width="120" align="right">
          <template #default="{ row }">{{ runHistorySummary(row) }}</template>
        </el-table-column>
        <el-table-column label="进度" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.progress?.message ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="id" label="任务ID" min-width="240" show-overflow-tooltip />
      </el-table>
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

    <div v-if="result" class="panel compact-panel">
      <div class="result-status-grid">
        <div class="result-status-item" v-for="item in summaryItems" :key="item.label">
          <div class="result-status-label">{{ item.label }}</div>
          <div class="result-status-value">{{ item.value }}</div>
        </div>
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
        <el-tag effect="plain">抽样分钟 {{ diagnostics.has_intraday_data_count ?? 0 }} / {{ diagnostics.checked_intraday_count ?? 0 }}</el-tag>
        <el-tag effect="plain">扫描 {{ diagnostics.resolved_scan_count ?? result?.scanned_count ?? 0 }} / {{ diagnostics.requested_scan_limit ?? form.limit }}</el-tag>
        <el-tag v-if="diagnostics.minute5_sync" effect="plain">补数据 {{ diagnostics.minute5_sync.inserted_rows ?? 0 }} 行</el-tag>
        <el-tag v-if="diagnostics.latest_intraday_time" effect="plain">最新分钟 {{ diagnostics.latest_intraday_time }}</el-tag>
        <el-tag v-if="diagnostics.scan_as_of_time" effect="plain">扫描截至 {{ diagnostics.scan_as_of_time }}</el-tag>
        <el-tag effect="plain">可评分 {{ diagnostics.scoreable_count ?? 0 }}</el-tag>
        <el-tag effect="plain">不可评分 {{ diagnostics.unscoreable_count ?? 0 }}</el-tag>
        <el-tag effect="plain">候选 {{ diagnostics.candidate_count }}</el-tag>
        <el-tag effect="plain">确认 {{ diagnostics.confirmed_count }}</el-tag>
        <el-tag :type="dataFreshnessTagType" effect="plain">数据新鲜度 {{ dataFreshnessText }}</el-tag>
        <el-tag :type="quoteStatusTagType" effect="plain">实时行情 {{ quoteStatusText }}</el-tag>
        <el-tag v-if="persistenceText" effect="plain">持久化 {{ persistenceText }}</el-tag>
      </div>
      <div v-if="diagnostics.empty_message" class="diagnostic-message">
        {{ diagnostics.empty_message }}
      </div>
      <div v-if="hasModelEnhancement" class="model-enhancement-panel">
        <div class="model-enhancement-title">模型增强状态</div>
        <div class="result-status-grid">
          <div class="result-status-item" v-for="item in modelEnhancementItems" :key="item.label">
            <div class="result-status-label">{{ item.label }}</div>
            <div class="result-status-value">{{ item.value }}</div>
          </div>
        </div>
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
          <el-tag effect="plain">{{ renderedCountText(displayedStrategyRows.length, strategyRows.length) }}</el-tag>
        </div>
        <el-table v-if="resultMode === 'precheck'" :data="displayedPrecheckRows" height="420" :empty-text="strategyEmptyText">
          <el-table-column prop="rank" label="排名" width="72" />
          <el-table-column label="股票" min-width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
            </template>
          </el-table-column>
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
        <el-table v-else :data="displayedRankedSignals" height="420" :empty-text="strategyEmptyText">
          <el-table-column prop="rank" label="排名" width="72" />
          <el-table-column prop="raw_rank" label="原始排名" width="92" />
          <el-table-column prop="final_candidate_rank" label="候选排名" width="92">
            <template #default="{ row }">{{ row.final_candidate_rank ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="股票" min-width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
            </template>
          </el-table-column>
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
          <el-table-column label="强度" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.strength) }}</template>
          </el-table-column>
          <el-table-column label="V2分" width="100" align="right">
            <template #default="{ row }">{{ formatScore(row.v2_score) }}</template>
          </el-table-column>
          <el-table-column v-if="hasModelScores" label="模型" width="136" align="right">
            <template #default="{ row }">
              <div class="metric-stack">
                <strong>{{ formatScore(row.model?.model_score) }}</strong>
                <span>{{ formatPercent(row.model?.hit_probability) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="规则分" width="120" align="right">
            <template #default="{ row }">
              <el-tag :type="credibilityType(row.credibility?.rule_score ?? row.credibility?.score)" effect="plain">
                {{ row.credibility?.rule_score ?? row.credibility?.score ?? '-' }} {{ row.credibility?.rule_grade ?? row.credibility?.grade ?? '' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="校准概率" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.credibility?.calibrated_probability) }}</template>
          </el-table-column>
          <el-table-column label="量比" width="110" align="right">
            <template #default="{ row }">{{ formatScore(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="尾盘涨幅" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.tail_return) }}</template>
          </el-table-column>
          <el-table-column label="高点回撤" width="120" align="right">
            <template #default="{ row }">{{ formatPercent(row.pullback_from_high) }}</template>
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
          <el-table-column label="资金/价格" width="120" align="right">
            <template #default="{ row }">
              {{ formatScore(row.v2_breakdown?.tail_money) }} / {{ formatScore(row.v2_breakdown?.price_action) }}
            </template>
          </el-table-column>
          <el-table-column label="评分拆解" min-width="180">
            <template #default="{ row }">
              强 {{ formatScore(row.score_breakdown?.strength) }} /
              量 {{ formatScore(row.score_breakdown?.volume_ratio) }} /
              涨 {{ formatScore(row.score_breakdown?.tail_return) }}
            </template>
          </el-table-column>
          <el-table-column label="过滤原因" min-width="150">
            <template #default="{ row }">{{ filterReasonText(row.filter_reason) }}</template>
          </el-table-column>
        </el-table>
        <div v-if="strategyRows.length > displayedStrategyRows.length" class="table-footer-actions">
          <span>仅展示前 {{ displayedStrategyRows.length }} 条，共 {{ strategyRows.length }} 条</span>
          <el-button size="small" @click="showMoreStrategyRows">显示更多</el-button>
        </div>
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
        <TailSelectionTable
          v-else
          :rows="selections"
          :empty-text="selectionEmptyText"
          :has-model-scores="hasModelScores"
          @open-stock-trend="openStockTrend"
        />
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">候选观察池</h2>
          <el-tag effect="plain">{{ renderedCountText(displayedWatchlistSignals.length, watchlistSignals.length) }}</el-tag>
        </div>
        <el-table :data="displayedWatchlistSignals" height="300" empty-text="暂无候选观察信号">
          <el-table-column label="股票" min-width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
            </template>
          </el-table-column>
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
        <div v-if="watchlistSignals.length > displayedWatchlistSignals.length" class="table-footer-actions">
          <span>仅展示前 {{ displayedWatchlistSignals.length }} 条，共 {{ watchlistSignals.length }} 条</span>
          <el-button size="small" @click="showMoreWatchlistRows">显示更多</el-button>
        </div>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">弱信号池</h2>
          <el-tag effect="plain">{{ renderedCountText(displayedWeakSignals.length, weakSignals.length) }}</el-tag>
        </div>
        <el-table :data="displayedWeakSignals" height="300" empty-text="暂无弱信号">
          <el-table-column label="股票" min-width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
            </template>
          </el-table-column>
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
        <div v-if="weakSignals.length > displayedWeakSignals.length" class="table-footer-actions">
          <span>仅展示前 {{ displayedWeakSignals.length }} 条，共 {{ weakSignals.length }} 条</span>
          <el-button size="small" @click="showMoreWeakRows">显示更多</el-button>
        </div>
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
          <el-descriptions-item label="模型增强">{{ modelEnhancementDescription }}</el-descriptions-item>
          <el-descriptions-item label="扫描口径">{{ scanScopeText }}</el-descriptions-item>
          <el-descriptions-item label="补数据">{{ syncDiagnosticText }}</el-descriptions-item>
          <el-descriptions-item label="阶段耗时">{{ stageTimingText }}</el-descriptions-item>
          <el-descriptions-item label="实时行情">{{ quoteStatusText }}</el-descriptions-item>
          <el-descriptions-item label="数据新鲜度">{{ dataFreshnessText }}</el-descriptions-item>
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
import { computed, onMounted, ref, watch } from 'vue'
import { type JobRecord, type JobStatus, type TailLiveSelectionPayload } from '../api/client'
import {
  candidateRankShiftText,
  credibilityType,
  dedupeIssues,
  executionFlagText,
  executionFlagType,
  filterReasonText,
  formatCompactDateTime,
  formatDateTime,
  formatPercent,
  formatScore,
  isModelEliminated,
  isModelPromoted,
  modelDecisionText,
  modelDecisionType,
  precheckDataStatusText,
  precheckStageText,
  qualityCoverageText,
  qualityTagType,
  strategyModeText,
  v2ActionText,
  v2LayerText,
  v2LayerType,
} from '../features/tail-live/formatters'
import { stockTrendUrl as buildStockTrendUrl } from '../features/tail-live/links'
import type { SelectionRow, TailLiveResult } from '../features/tail-live/types'
import { useTailLiveDataHealth } from '../features/tail-live/useTailLiveDataHealth'
import { useTailLiveJob } from '../features/tail-live/useTailLiveJob'
import TailDataHealthPanel from './tail-live/TailDataHealthPanel.vue'
import TailSelectionTable from './tail-live/TailSelectionTable.vue'

const props = defineProps<{
  jobId?: string
}>()

const today = formatLocalDate(new Date())
const RESULT_TABLE_RENDER_BATCH_SIZE = 120
const form = ref<TailLiveSelectionPayload>({
  trade_date: today,
  symbols: null,
  limit: 0,
  universe: 'default',
  bars_cache_dir: 'data/cache/bars',
  liquidity_min_bars: 60,
  min_market_breadth_above_ma20: null,
  confirmations: 1,
  top_n: 2,
  min_strength: null,
  ignore_session: false,
  auto_sync_minute5: true,
  data_refresh_mode: 'auto',
  strategy_mode: 'rule',
  output_dir: 'reports/tail_session'
})

const manualSymbols = ref<string[]>([])
const {
  activeJobId,
  job,
  loadingHistory,
  runHistory,
  submitting,
  loadJob,
  loadRunHistory,
  refreshJob,
  selectRunHistory,
  submit,
} = useTailLiveJob(form, manualSymbols)
const {
  dataHealth,
  dataHealthLoadedAt,
  loadingDataHealth,
  loadDataHealth,
} = useTailLiveDataHealth(computed(() => form.value.trade_date))
const strategyRenderLimit = ref(RESULT_TABLE_RENDER_BATCH_SIZE)
const watchlistRenderLimit = ref(RESULT_TABLE_RENDER_BATCH_SIZE)
const weakRenderLimit = ref(RESULT_TABLE_RENDER_BATCH_SIZE)
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
const hasModelScores = computed(() => rankedSignals.value.some((row) => Boolean(row.model)))
const hasModelEnhancement = computed(() => {
  const status = diagnostics.value?.model_status
  return Boolean(hasModelScores.value || status || diagnostics.value?.effective_strategy_mode === 'model' || diagnostics.value?.effective_strategy_mode === 'hybrid')
})
const watchlistSignals = computed(() => result.value?.watchlist_signals ?? [])
const weakSignals = computed(() => result.value?.weak_signals ?? [])
const signalLayers = computed(() => result.value?.signal_layers ?? { strong: 0, watchlist: 0, weak: 0 })
const precheckRows = computed(() => result.value?.precheck_rows ?? [])
const strategyRows = computed(() => resultMode.value === 'precheck' ? precheckRows.value : rankedSignals.value)
const displayedPrecheckRows = computed(() => precheckRows.value.slice(0, strategyRenderLimit.value))
const displayedRankedSignals = computed(() => rankedSignals.value.slice(0, strategyRenderLimit.value))
const displayedStrategyRows = computed(() => resultMode.value === 'precheck' ? displayedPrecheckRows.value : displayedRankedSignals.value)
const displayedWatchlistSignals = computed(() => watchlistSignals.value.slice(0, watchlistRenderLimit.value))
const displayedWeakSignals = computed(() => weakSignals.value.slice(0, weakRenderLimit.value))
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
  { label: '扫描数', value: scanCountText.value },
  { label: '抽样分钟', value: diagnostics.value ? `${diagnostics.value.has_intraday_data_count ?? 0}/${diagnostics.value.checked_intraday_count ?? 0}` : '-' },
  { label: '最新分钟', value: diagnostics.value?.latest_intraday_time ?? '-' },
  { label: '数据新鲜度', value: compactDataFreshnessText.value },
  { label: '实时行情', value: compactQuoteStatusText.value },
  { label: '补数据', value: compactSyncSummaryText.value },
  { label: '扫描截至', value: diagnostics.value?.scan_as_of_time ?? '-' },
  { label: '可评分', value: String(diagnostics.value?.scoreable_count ?? 0) },
  { label: '强确认/观察/弱', value: `${signalLayers.value.strong}/${signalLayers.value.watchlist}/${signalLayers.value.weak}` },
  { label: resultMode.value === 'precheck' ? '等待原因' : resultMode.value === 'preview' ? '预演入选' : '最终选股', value: resultMode.value === 'precheck' ? emptyReasonText.value : resultMode.value === 'preview' ? String(result.value?.preview_count ?? 0) : String(result.value?.selected_count ?? '-') },
  { label: '交易日', value: result.value?.trade_date ?? '-' }
])
const modelEnhancementItems = computed(() => [
  { label: '模型增强状态', value: modelEnhancementStateText.value },
  { label: '策略模式', value: strategyModeText(diagnostics.value?.effective_strategy_mode ?? diagnostics.value?.strategy_mode ?? form.value.strategy_mode) },
  { label: '评分范围', value: `${diagnostics.value?.model_scored_symbols ?? 0} 只 / Top ${diagnostics.value?.model_score_rank_limit ?? '-'}` },
  { label: '参与排序', value: diagnostics.value?.model_selection_applied ? '已参与最终排序' : '未参与最终排序' },
  { label: '入选变化', value: modelSelectionImpactText.value },
])
const modelEnhancementStateText = computed(() => {
  const status = diagnostics.value?.model_status
  if (status === 'scored') return '模型已评分'
  if (status === 'disabled') return '规则模式，未启用模型'
  if (status === 'no_promoted_model') return '无已推广模型'
  if (status === 'no_scoreable_rows') return '无可评分标的'
  return status ? String(status) : '-'
})
const modelSelectionImpactText = computed(() => {
  if (!diagnostics.value?.model_selection_applied) return '未改变最终排序'
  const promoted = selections.value.filter((row) => isModelPromoted(row)).length
  const eliminated = rankedSignals.value.filter((row) => isModelEliminated(row)).length
  return `模型提权 ${promoted}，模型淘汰 ${eliminated}`
})
const modelEnhancementDescription = computed(() => {
  if (!hasModelEnhancement.value) return '未启用模型增强，按规则/V2排序。'
  return `${modelEnhancementStateText.value}；${modelSelectionImpactText.value}；评分 ${diagnostics.value?.model_scored_symbols ?? 0} 只，模式 ${strategyModeText(diagnostics.value?.effective_strategy_mode ?? diagnostics.value?.strategy_mode)}。`
})
const scanCountText = computed(() => {
  const scanned = result.value?.scanned_count
  const requested = diagnostics.value?.requested_scan_limit ?? form.value.limit
  if (requested === 0) return `${scanned ?? '-'} / 全市场非ST`
  return `${scanned ?? '-'} / ${requested}`
})
const scanScopeText = computed(() => {
  const requested = diagnostics.value?.requested_scan_limit ?? form.value.limit
  return requested === 0 ? '扫描全市场非ST股票，不做固定数量截断' : `扫描策略池前 ${requested} 只股票`
})
const scanLimitDisplayText = computed(() => form.value.limit === 0 ? '全市场非ST' : `最多 ${form.value.limit} 只`)
const syncSummaryText = computed(() => {
  const sync = diagnostics.value?.minute5_sync
  const snapshot = diagnostics.value?.quote_snapshot_sync
  if (snapshot) return `快照 ${snapshot.inserted_rows ?? 0} 行 / 最新 ${snapshot.latest_snapshot_at ?? snapshot.latest_bucket ?? '-'}`
  if (!sync) return refreshModeWaitingText.value
  return `${sync.inserted_rows ?? 0} 行 / 最新 ${sync.latest_datetime ?? '-'}`
})
const compactSyncSummaryText = computed(() => {
  const sync = diagnostics.value?.minute5_sync
  const snapshot = diagnostics.value?.quote_snapshot_sync
  if (snapshot) return `快照${snapshot.inserted_rows ?? 0}行`
  if (!sync) return refreshModeCompactText.value
  return `${sync.inserted_rows ?? 0}行 / ${formatCompactDateTime(sync.latest_datetime)}`
})
const syncDiagnosticText = computed(() => {
  const sync = diagnostics.value?.minute5_sync
  const snapshot = diagnostics.value?.quote_snapshot_sync
  if (snapshot) {
    return `快照优先：目标 ${snapshot.target_symbols ?? 0}，插入 ${snapshot.inserted_rows ?? 0} 行，跳过 ${snapshot.skipped ?? 0}，失败 ${snapshot.failed ?? 0}，最新 ${snapshot.latest_snapshot_at ?? snapshot.latest_bucket ?? '-'}`
  }
  if (!sync) return refreshModeDescription.value
  return `目标 ${sync.target_symbols ?? 0}，跳过 ${sync.skipped ?? 0}，成功 ${sync.success ?? 0}，无数据 ${sync.no_data ?? 0}，失败 ${sync.failed ?? 0}，插入 ${sync.inserted_rows ?? 0} 行，最新 ${sync.latest_datetime ?? '-'}`
})
const refreshModeWaitingText = computed(() => {
  if (form.value.data_refresh_mode === 'none') return '未启用'
  if (form.value.data_refresh_mode === 'standard_minute5') return '等待标准5m'
  return '等待快照'
})
const refreshModeCompactText = computed(() => {
  if (form.value.data_refresh_mode === 'none') return '未启用'
  if (form.value.data_refresh_mode === 'standard_minute5') return '标准5m'
  return '快照优先'
})
const refreshModeDescription = computed(() => {
  if (form.value.data_refresh_mode === 'none') return '本次不执行运行前数据刷新'
  if (form.value.data_refresh_mode === 'standard_minute5') return '运行前补齐标准5分钟线，适合盘后复核，速度较慢'
  return '运行前优先刷新腾讯批量快照和5m聚合，适合尾盘实时选股'
})
const dataFreshnessText = computed(() => {
  const freshness = diagnostics.value?.data_freshness
  if (!freshness) return '-'
  const lag = freshness.lag_minutes == null ? '-' : `${freshness.lag_minutes} 分钟`
  return `${freshness.status}，最新 ${freshness.latest_time ?? '-'}，目标 ${freshness.target_time ?? '-'}，滞后 ${lag}`
})
const compactDataFreshnessText = computed(() => {
  const freshness = diagnostics.value?.data_freshness
  if (!freshness) return '-'
  const lag = freshness.lag_minutes == null ? '-' : `${freshness.lag_minutes}分`
  return `${freshness.status} / ${freshness.latest_time ?? '-'} / ${lag}`
})
const dataFreshnessTagType = computed(() => {
  const status = diagnostics.value?.data_freshness?.status
  if (status === 'fresh') return 'success'
  if (status === 'stale') return 'danger'
  return 'warning'
})
const quoteStatusText = computed(() => {
  const status = diagnostics.value?.quote_status
  if (!status) return '-'
  const base = `${status.status}，覆盖 ${status.covered_symbols ?? 0}/${status.requested_symbols ?? 0}，${formatPercent(status.coverage_ratio)}`
  return status.error ? `${base}，${status.error}` : base
})
const compactQuoteStatusText = computed(() => {
  const status = diagnostics.value?.quote_status
  if (!status) return '-'
  return `${status.status} / ${status.covered_symbols ?? 0}/${status.requested_symbols ?? 0} / ${formatPercent(status.coverage_ratio)}`
})
const quoteStatusTagType = computed(() => {
  const status = diagnostics.value?.quote_status?.status
  if (status === 'ok') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
})
const stageTimingText = computed(() => {
  const timings = result.value?.stage_timings
  if (!timings) return '-'
  return Object.entries(timings)
    .map(([key, value]) => `${stageTimingLabel(key)} ${Number(value).toFixed(2)}s`)
    .join('，')
})
const persistenceText = computed(() => {
  const signals = result.value?.persistence?.signals
  if (!signals) return ''
  return `排序池 ${signals.signal_count ?? 0}，入选 ${signals.selected_count ?? 0}`
})
const dataHealthUpdateText = computed(() => dataHealthLoadedAt.value ? `更新 ${dataHealthLoadedAt.value}` : '未加载')
const dataHealthItems = computed(() => {
  const quality = dataHealth.value?.quality
  const minute5 = quality?.minute5
  const quote = quality?.quote_snapshots?.raw
  const daily = quality?.daily
  const checks = quality?.scheduled_checks
  return [
    {
      label: '分钟线最新',
      value: formatCompactDateTime(minute5?.latest_datetime ?? dataHealth.value?.health?.minute5_latest_datetime),
      status: minute5?.status ?? 'missing'
    },
    {
      label: '分钟线覆盖',
      value: qualityCoverageText(minute5),
      status: minute5?.status ?? 'missing'
    },
    {
      label: '分钟线写入中',
      value: minute5 ? `${formatCompactDateTime(minute5.current_latest_datetime)} / ${minute5.current_covered_symbols ?? '-'}/${minute5.expected_symbols ?? '-'}` : '-',
      status: minute5?.current_latest_datetime === minute5?.latest_datetime ? minute5?.status ?? 'missing' : 'warning'
    },
    {
      label: '行情快照',
      value: quote ? `${formatCompactDateTime(quote.latest_datetime)} / ${quote.latest_symbol_count ?? 0}/${quality?.quote_snapshots?.expected_symbols ?? 0}` : '-',
      status: quote?.status ?? quality?.quote_snapshots?.status ?? 'missing'
    },
    {
      label: '快照缺失率',
      value: quote?.missing_rate == null ? '-' : formatPercent(quote.missing_rate),
      status: quote?.status ?? quality?.quote_snapshots?.status ?? 'missing'
    },
    {
      label: '日线质量',
      value: daily ? `${formatCompactDateTime(daily.latest_date)} / ${daily.covered_symbols ?? 0}/${quality?.expected_non_st_symbols ?? '-'}` : '-',
      status: daily?.status ?? 'missing'
    },
    {
      label: '定时质检',
      value: checks ? `${checks.freshness.status} / 异常${checks.today_anomalies.bad_rows}` : '-',
      status: checks?.status ?? 'missing'
    }
  ]
})
const dataHealthIssues = computed(() => {
  const quality = dataHealth.value?.quality
  return dedupeIssues([
    ...(quality?.issues ?? []),
    ...(quality?.quote_snapshots?.issues ?? []),
    ...(quality?.scheduled_checks?.issues ?? [])
  ]).slice(0, 6)
})

function formatLocalDate(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function stageTimingLabel(value: string) {
  if (value === 'minute5_sync') return '补数据'
  if (value === 'quote_snapshot_sync') return '快照'
  if (value === 'strategy_scan') return '策略'
  if (value === 'resolve_and_coverage') return '股票池'
  if (value === 'quote_and_breadth') return '行情'
  if (value === 'scan_intraday') return '扫描'
  if (value === 'write_outputs') return '写入'
  if (value === 'persistence') return '持久化'
  if (value === 'total') return '总计'
  return value
}

function openStockTrend(symbol: string) {
  window.open(stockTrendUrl(symbol), '_blank', 'noopener,noreferrer')
}

function stockTrendUrl(symbol: string) {
  return buildStockTrendUrl(symbol, { tradeDate: form.value.trade_date })
}

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function runHistorySummary(row: JobRecord) {
  const rowResult = (row.result ?? {}) as Record<string, unknown>
  const scanned = rowResult.scanned_count ?? '-'
  const selected = rowResult.selected_count ?? '-'
  return `${scanned} / ${selected}`
}

function renderedCountText(rendered: number, total: number) {
  return rendered >= total ? String(total) : `${rendered}/${total}`
}

function showMoreStrategyRows() {
  strategyRenderLimit.value += RESULT_TABLE_RENDER_BATCH_SIZE
}

function showMoreWatchlistRows() {
  watchlistRenderLimit.value += RESULT_TABLE_RENDER_BATCH_SIZE
}

function showMoreWeakRows() {
  weakRenderLimit.value += RESULT_TABLE_RENDER_BATCH_SIZE
}

function resetResultTableLimits() {
  strategyRenderLimit.value = RESULT_TABLE_RENDER_BATCH_SIZE
  watchlistRenderLimit.value = RESULT_TABLE_RENDER_BATCH_SIZE
  weakRenderLimit.value = RESULT_TABLE_RENDER_BATCH_SIZE
}

watch(
  () => props.jobId,
  (jobId) => {
    if (jobId) void loadJob(jobId)
  },
  { immediate: true }
)

watch(
  () => activeJobId.value,
  () => resetResultTableLimits()
)

onMounted(() => {
  void loadRunHistory()
  void loadDataHealth()
})
</script>
