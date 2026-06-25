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

    <div class="panel compact-panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">选股数据健康度</h2>
        <div class="toolbar">
          <el-tag :type="qualityTagType(dataHealth?.quality?.status)" effect="plain">
            {{ dataHealth?.quality?.status ?? 'loading' }}
          </el-tag>
          <el-tag effect="plain">{{ dataHealthUpdateText }}</el-tag>
        </div>
      </div>
      <div class="health-status-grid">
        <div class="health-status-item" v-for="item in dataHealthItems" :key="item.label">
          <div class="health-status-head">
            <span class="health-status-label">{{ item.label }}</span>
            <el-tag :type="qualityTagType(item.status)" effect="plain" size="small">{{ item.status }}</el-tag>
          </div>
          <div class="health-status-value">{{ item.value }}</div>
        </div>
      </div>
      <div v-if="dataHealthIssues.length" class="diagnostic-message muted">
        异常：{{ dataHealthIssues.join('，') }}
      </div>
    </div>

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
        <el-table v-else :data="selections" height="420" :empty-text="selectionEmptyText">
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
              <el-button link type="primary" @click="openStockTrend(row.symbol)">{{ row.symbol }}</el-button>
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
import { ElMessage } from 'element-plus'
import { api, type DataStatusResponse, type JobRecord, type JobStatus, type TailLiveSelectionPayload } from '../api/client'

interface SelectionRow {
  rank?: number
  raw_rank?: number | null
  final_candidate_rank?: number | null
  symbol: string
  trade_date: string
  strength: number
  last_price: number
  volume_ratio: number
  tail_return: number
  tail_high_return?: number
  pullback_from_high?: number
  close_position?: number
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
  tradability?: {
    buyable: boolean
    reason?: string | null
    price?: number | null
    limit_up?: number | null
    limit_up_distance?: number | null
    execution_flag?: string | null
    score?: number | null
  }
  next_day_plan?: {
    entry_policy: string
    sell_policy?: string
    gap_stop_return: number | null
    intraday_stop_return: number | null
    take_profit_return: number | null
    rules: string[]
  }
  score_breakdown?: {
    strength: number
    volume_ratio: number
    tail_return: number
    pullback_penalty: number
    v2_total?: number | null
  }
  model?: ModelScore
}

interface ModelScore {
  model_version?: string | null
  model_score?: number | null
  hit_probability?: number | null
  expected_high_return?: number | null
  risk_probability?: number | null
  feature_snapshot?: ModelFeatureSnapshot[]
}

interface ModelFeatureSnapshot {
  feature: string
  value: number | null
}

interface Credibility {
  score: number
  grade: '高' | '中' | '低'
  rule_score?: number
  rule_grade?: '高' | '中' | '低'
  historical_hit_rate?: number | null
  historical_avg_return?: number | null
  sample_size?: number
  calibrated_probability?: number | null
  history_status?: string
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
    close_win_rate?: number
    avg_close_return?: number
    max_win_rate?: number
    avg_max_return?: number
    avg_min_return?: number
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
    data_freshness?: {
      status: string
      latest_time: string | null
      target_time: string | null
      lag_minutes: number | null
      tradable: boolean
    }
    quote_status?: {
      status: string
      requested_symbols: number
      covered_symbols: number
      coverage_ratio: number
      error?: string
    }
    minute5_sync?: {
      trade_date?: string
      target_symbols?: number
      skipped?: number
      success?: number
      no_data?: number
      failed?: number
      inserted_rows?: number
      latest_datetime?: string | null
    }
    data_refresh_mode?: 'auto' | 'snapshot' | 'standard_minute5' | 'none'
    effective_data_refresh_mode?: 'snapshot' | 'standard_minute5' | 'none'
    strategy_mode?: 'rule' | 'model' | 'hybrid'
    quote_snapshot_sync?: {
      target_symbols?: number
      inserted_rows?: number
      skipped?: number
      failed?: number
      latest_snapshot_at?: string | null
      latest_bucket?: string | null
    }
  }
  stage_timings?: Record<string, number>
  persistence?: {
    signals?: {
      signal_count?: number
      selected_count?: number
    }
  }
}

const props = defineProps<{
  jobId?: string
}>()

const today = new Date().toISOString().slice(0, 10)
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
const submitting = ref(false)
const loadingHistory = ref(false)
const loadingDataHealth = ref(false)
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const runHistory = ref<JobRecord[]>([])
const dataHealth = ref<DataStatusResponse | null>(null)
const dataHealthLoadedAt = ref('')
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

async function submit() {
  submitting.value = true
  try {
    const response = await api.submitTailLiveSelection({
      ...form.value,
      symbols: manualSymbols.value.length ? manualSymbols.value : null
    })
    activeJobId.value = response.job_id
    const completed = await pollJobUntilDone(response.job_id)
    await loadRunHistory()
    if (completed) ElMessage.success('今日尾盘选股完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadDataHealth() {
  loadingDataHealth.value = true
  try {
    dataHealth.value = await api.getDataStatus()
    dataHealthLoadedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据健康度失败')
  } finally {
    loadingDataHealth.value = false
  }
}

async function loadRunHistory() {
  loadingHistory.value = true
  try {
    const response = await api.listJobs(100)
    runHistory.value = response.items.filter((item) => item.kind === 'tail_session_live_selection')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载运行记录失败')
  } finally {
    loadingHistory.value = false
  }
}

async function selectRunHistory(row: JobRecord) {
  await loadJob(row.id)
}

function openStockTrend(symbol: string) {
  window.open(stockTrendUrl(symbol), '_blank', 'noopener,noreferrer')
}

function stockTrendUrl(symbol: string) {
  const params = new URLSearchParams({ page: 'stock-trend', symbol, granularity: '5m', trade_date: form.value.trade_date })
  return `${window.location.origin}${window.location.pathname}?${params.toString()}`
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

function qualityCoverageText(row?: { covered_symbols: number; missing_symbols: number; coverage_ratio: number }) {
  if (!row) return '-'
  return `${row.covered_symbols ?? 0}/${(row.covered_symbols ?? 0) + (row.missing_symbols ?? 0)}，${formatPercent(row.coverage_ratio)}`
}

function formatCompactDateTime(value: unknown) {
  if (!value) return '-'
  const text = String(value)
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/)
  if (!match) return text
  return match[4] ? `${match[2]}-${match[3]} ${match[4]}:${match[5]}` : `${match[2]}-${match[3]}`
}

function dedupeIssues(items: string[]) {
  return Array.from(new Set(items.filter(Boolean)))
}

function qualityTagType(status?: string) {
  if (status === 'ok') return 'success'
  if (status === 'warning' || status === 'partial') return 'warning'
  if (status === 'error' || status === 'failed' || status === 'missing') return 'danger'
  return 'info'
}

function formatDateTime(value: string) {
  return value ? value.replace('T', ' ').slice(0, 19) : '-'
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

const modelFeatureLabels: Record<string, string> = {
  daily_ret_5: '5日涨幅',
  daily_ret_10: '10日涨幅',
  daily_ret_20: '20日涨幅',
  daily_volatility_20: '20日波动',
  ma5_distance: 'MA5距离',
  ma20_distance: 'MA20距离',
  avg_amount_20: '20日成交额',
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

function filterReasonText(value: unknown) {
  if (value === 'below_candidate_threshold') return '未达候选阈值'
  if (value === 'below_min_strength') return '低于最小强度'
  if (value === 'preview_not_final') return '未到14:50最终确认'
  if (value === 'v2_not_trade_candidate') return 'V2未达交易候选'
  if (value === 'limit_up_not_buyable') return '涨停/近涨停，无法买入'
  if (value === 'tail_pullback_risk') return '尾盘冲高回落'
  if (value === 'outside_historical_calibration_top_n') return '历史校准排名超出 Top N'
  if (value === 'outside_top_n') return '排名超出 Top N'
  if (value === 'not_selected') return '未入选'
  return '-'
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

watch(
  () => activeJobId.value,
  () => resetResultTableLimits()
)

onMounted(() => {
  void loadRunHistory()
  void loadDataHealth()
})
</script>
