<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">数据中心</h1>
      <div class="toolbar">
        <el-button type="primary" :loading="maintaining" @click="runDailyMaintenance">日常维护</el-button>
        <el-button :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div class="panel overview-panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">今日尾盘策略可用性</h2>
          <p class="section-subtitle">只按策略可交易池判断日线、5m、快照和自动采集是否阻塞今日选股</p>
        </div>
        <el-tag :type="qualityTagType(dataStatus?.quality?.status)" effect="plain" size="large">
          {{ overallReadiness }}
        </el-tag>
      </div>
      <div class="readiness-grid">
        <div class="readiness-item">
          <span class="metric-label">策略可交易池</span>
          <strong>{{ formatNumber(strategyTradableCount) }}</strong>
          <small>非 ST {{ formatNumber(dataStatus?.stock_summary.non_st_stock_count ?? 0) }} / 共 {{ formatNumber(dataStatus?.stock_summary.stock_count ?? 0) }}</small>
        </div>
        <div class="readiness-item">
          <span class="metric-label">日线</span>
          <strong>{{ dataStatus?.health.daily_latest_date ?? '-' }}</strong>
          <small>{{ scheduledFreshnessText }}</small>
        </div>
        <div class="readiness-item">
          <span class="metric-label">5m 分钟线</span>
          <strong>{{ dataStatus?.health.minute5_latest_datetime ?? '-' }}</strong>
          <small>{{ minute5ReadinessText }}</small>
        </div>
        <div class="readiness-item">
          <span class="metric-label">行情快照</span>
          <strong>{{ dataStatus?.health.quote_snapshot_latest_datetime ?? '-' }}</strong>
          <small>{{ quoteSnapshotReadinessText }}</small>
        </div>
      </div>
      <div v-if="ignoredIssueCount" class="ignored-issues-strip">
        <span>已忽略非阻塞异常 {{ ignoredIssueCount }} 项</span>
        <small>{{ ignoredIssuesText }}</small>
      </div>
      <div v-if="repairPlan?.actions.length" class="repair-plan-panel">
        <div class="repair-plan-head">
          <div>
            <div class="operation-title">告警修复计划</div>
            <div class="operation-desc">
              自动 {{ repairPlan.summary.auto_repair_count }} 项，手动 {{ repairPlan.summary.manual_count }} 项；{{ repairPlan.issues.join('，') || '无告警' }}
            </div>
          </div>
          <div class="repair-actions">
            <el-button size="small" :loading="repairPlanLoading" @click="loadRepairPlan">刷新计划</el-button>
            <el-button
              size="small"
              type="primary"
              :disabled="!repairPlan.summary.auto_repair_count"
              :loading="repairingHealth"
              @click="repairDataHealth"
            >
              自动修复可处理项
            </el-button>
          </div>
        </div>
        <div class="repair-action-list">
          <div v-for="action in repairPlan.actions" :key="action.key" class="repair-action-item">
            <span>{{ action.title }}</span>
            <small>{{ action.reason }}</small>
            <el-tag :type="action.auto_repair ? 'success' : 'warning'" effect="plain" size="small">
              {{ action.auto_repair ? '自动' : '手动' }}
            </el-tag>
          </div>
        </div>
      </div>
      <div class="section-header compact-section-header">
        <div>
          <h3 class="section-title">消费链路状态</h3>
        </div>
      </div>
      <div class="consumer-strip">
        <div v-for="row in consumerReadinessRows" :key="row.key" class="consumer-item">
          <div class="consumer-title">
            <span>{{ row.title }}</span>
            <el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
          </div>
          <div class="consumer-desc">{{ row.detail }}</div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">数据可靠性总控</h2>
          <p class="section-subtitle">从数据源、自动更新、健康检查和修复机制四个维度审计核心链路</p>
        </div>
        <el-tag :type="qualityTagType(reliabilityReport?.status)" effect="plain">
          {{ reliabilityReport?.status ?? '-' }}
        </el-tag>
      </div>
      <el-table :data="reliabilityReport?.rows ?? []" empty-text="暂无可靠性审计信息">
        <el-table-column prop="name" label="数据链路" min-width="120" />
        <el-table-column prop="source" label="数据源" min-width="240" show-overflow-tooltip />
        <el-table-column prop="update_mechanism" label="自动更新" min-width="240" show-overflow-tooltip />
        <el-table-column label="自动化" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.automation === 'running' || row.automation === 'scheduled' ? 'success' : 'warning'" effect="plain">
              {{ row.automation }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="qualityTagType(row.health)" effect="plain">{{ row.health }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latest" label="最新" min-width="150" />
        <el-table-column prop="coverage" label="完整度" min-width="150" />
        <el-table-column prop="repair" label="修复机制" min-width="220" show-overflow-tooltip />
        <el-table-column label="当前告警" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">{{ row.issues.length ? row.issues.join('，') : '无' }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div class="ops-grid">
      <div class="panel">
        <div class="section-header no-top-margin">
          <div>
            <h2 class="page-title">数据资产地图</h2>
            <p class="section-subtitle">按用途查看底层数据是否可用</p>
          </div>
        </div>
        <div class="asset-grid">
          <div v-for="row in assetRows" :key="row.key" class="asset-item">
            <div class="asset-title">
              <span>{{ row.title }}</span>
              <el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
            </div>
            <div class="asset-meta">
              <span>{{ row.range }}</span>
              <span>{{ row.symbols }}</span>
              <span>{{ row.purpose }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="section-header no-top-margin">
          <div>
            <h2 class="page-title">更新任务中心</h2>
            <p class="section-subtitle">当前任务、自动采集和可操作入口</p>
          </div>
        </div>
        <div class="operation-list">
          <div v-for="row in operationRows" :key="row.key" class="operation-item">
            <div>
              <div class="operation-title">{{ row.title }}</div>
              <div class="operation-desc">{{ row.detail }}</div>
              <div v-if="row.key === 'minute5'" class="inline-control manual-minute5-control">
                <el-date-picker
                  v-model="minute5TradeDate"
                  type="date"
                  value-format="YYYY-MM-DD"
                  placeholder="5分钟线日期"
                  style="width: 150px"
                />
                <el-button size="small" :loading="syncingMinute5" @click="syncMinute5">更新 5分钟线</el-button>
              </div>
              <div v-if="row.key === 'minute5-monitor'" class="inline-control">
                <el-button
                  size="small"
                  :type="minute5Monitor?.running ? 'warning' : 'success'"
                  :loading="monitorChanging"
                  @click="toggleMinute5Monitor"
                >
                  {{ minute5Monitor?.running ? '停止持续更新' : '启动持续更新' }}
                </el-button>
              </div>
            </div>
            <el-tag :type="row.type" effect="plain">{{ row.status }}</el-tag>
          </div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">数据健康矩阵</h2>
          <p class="section-subtitle">按数据资产查看来源、更新机制、完整度、服务功能和当前告警</p>
        </div>
        <el-tag effect="plain">{{ datasetHealthRows.length }}</el-tag>
      </div>
      <el-table
        :data="datasetHealthRows"
        row-key="key"
        empty-text="暂无数据健康信息"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="dataset-health-detail">
              <div><strong>数据源</strong><span>{{ row.source }}</span></div>
              <div><strong>更新机制</strong><span>{{ row.update_mechanism }}</span></div>
              <div><strong>服务功能</strong><span>{{ row.consumer }}</span></div>
              <div><strong>底层表</strong><span class="mono-text">{{ row.table }}</span></div>
              <div><strong>告警</strong><span>{{ row.issues.length ? row.issues.join('，') : '无' }}</span></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="数据" min-width="170">
          <template #default="{ row }">
            <div class="dataset-health-name">
              <strong>{{ row.name }}</strong>
              <small>{{ row.category }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="update_mechanism" label="更新机制" min-width="260" show-overflow-tooltip />
        <el-table-column prop="consumer" label="服务功能" min-width="240" show-overflow-tooltip />
        <el-table-column label="最新/范围" min-width="210">
          <template #default="{ row }">
            <div class="dataset-health-range">
              <span>{{ row.latest ?? '-' }}</span>
              <small>{{ datasetHealthRangeText(row) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="完整度" width="150">
          <template #default="{ row }">{{ datasetHealthCoverageText(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="qualityTagType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel stock-db-panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">{{ databaseTitle }}</h2>
        <el-tag :type="dataStatus?.database.exists ? 'success' : 'danger'" effect="plain">
          {{ dataStatus?.health.status ?? '-' }}
        </el-tag>
      </div>
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">质量中心</h2>
          <p class="section-subtitle">覆盖、缺口、重复键、定时质量检查和快照采集健康</p>
        </div>
        <el-tag :type="qualityTagType(dataStatus?.quality?.status)" effect="plain">
          {{ dataStatus?.quality?.status ?? '-' }}
        </el-tag>
      </div>
      <div v-if="syncJob" class="sync-progress">
        <div class="sync-progress-header">
          <span>同步任务：{{ syncJob.progress.message || syncJob.status }}</span>
          <el-tag :type="jobStatusType(syncJob.status)" effect="plain">{{ syncJob.status }}</el-tag>
        </div>
        <el-progress
          :percentage="syncJob.progress.percent"
          :status="syncJob.status === 'failed' ? 'exception' : syncJob.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div v-if="minute5Job" class="sync-progress">
        <div class="sync-progress-header">
          <span>5分钟线任务：{{ minute5Job.progress.message || minute5Job.status }}</span>
          <el-tag :type="jobStatusType(minute5Job.status)" effect="plain">{{ minute5Job.status }}</el-tag>
        </div>
        <el-progress
          :percentage="minute5Job.progress.percent"
          :status="minute5Job.status === 'failed' ? 'exception' : minute5Job.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div v-if="maintenanceJob" class="sync-progress">
        <div class="sync-progress-header">
          <span>日常维护：{{ maintenanceJob.progress.message || maintenanceJob.status }}</span>
          <el-tag :type="jobStatusType(maintenanceJob.status)" effect="plain">{{ maintenanceJob.status }}</el-tag>
        </div>
        <el-progress
          :percentage="maintenanceJob.progress.percent"
          :status="maintenanceJob.status === 'failed' ? 'exception' : maintenanceJob.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div v-if="healthRepairJob" class="sync-progress">
        <div class="sync-progress-header">
          <span>健康修复：{{ healthRepairJob.progress.message || healthRepairJob.status }}</span>
          <el-tag :type="jobStatusType(healthRepairJob.status)" effect="plain">{{ healthRepairJob.status }}</el-tag>
        </div>
        <el-progress
          :percentage="healthRepairJob.progress.percent"
          :status="healthRepairJob.status === 'failed' ? 'exception' : healthRepairJob.status === 'success' ? 'success' : undefined"
        />
      </div>
      <div class="sync-progress">
        <div class="sync-progress-header">
          <span>分钟线持续更新：{{ minute5MonitorText }}</span>
          <el-tag :type="minute5Monitor?.running ? 'success' : 'info'" effect="plain">
            {{ minute5Monitor?.running ? 'running' : 'stopped' }}
          </el-tag>
        </div>
        <div class="monitor-meta">
          <span>{{ minute5MonitorModeText }}</span>
          <span>{{ minute5MonitorSessionText }}</span>
          <span>最近完成：{{ minute5Monitor?.last_finished_at ?? '-' }}</span>
          <span>下次检查：{{ minute5Monitor?.next_run_at ?? '-' }}</span>
        </div>
        <el-progress
          :percentage="minute5Monitor?.last_progress?.percent ?? 0"
          :status="minute5Monitor?.last_error ? 'exception' : minute5Monitor?.running ? undefined : 'success'"
        />
      </div>
      <div class="sync-progress">
        <div class="sync-progress-header">
          <span>行情快照采集：{{ quoteSnapshotMonitorText }}</span>
          <el-tag :type="quoteSnapshotMonitor?.running ? 'success' : 'info'" effect="plain">
            {{ quoteSnapshotMonitor?.running ? 'running' : 'stopped' }}
          </el-tag>
        </div>
        <div class="monitor-meta">
          <span>{{ quoteSnapshotMonitorModeText }}</span>
          <span>{{ quoteSnapshotMonitorSessionText }}</span>
          <span>{{ quoteSnapshotMonitorCadenceText }}</span>
          <span>{{ quoteSnapshotMonitorTimingText }}</span>
          <span>最近完成：{{ quoteSnapshotMonitor?.last_finished_at ?? '-' }}</span>
          <span>下次采集：{{ quoteSnapshotMonitor?.next_run_at ?? '-' }}</span>
        </div>
        <el-progress
          :percentage="quoteSnapshotMonitor?.last_progress?.percent ?? 0"
          :status="quoteSnapshotMonitor?.last_error ? 'exception' : quoteSnapshotMonitor?.running ? undefined : 'success'"
        />
      </div>
      <div class="sync-progress">
        <div class="sync-progress-header">
          <span>自动数据运维：{{ dataOpsSchedulerText }}</span>
          <el-tag :type="dataOpsScheduler?.running ? 'success' : 'info'" effect="plain">
            {{ dataOpsScheduler?.running ? 'running' : 'stopped' }}
          </el-tag>
        </div>
        <div class="monitor-meta">
          <span>阶段：{{ dataOpsScheduler?.phase ?? '-' }}</span>
          <span>日终维护：{{ dataOpsScheduler?.tasks.post_close_maintenance.enabled ? '启用' : '未启用' }}</span>
          <span>最近完成：{{ dataOpsScheduler?.last_finished_at ?? '-' }}</span>
          <span>下次检查：{{ dataOpsScheduler?.next_run_at ?? '-' }}</span>
        </div>
        <el-progress
          :percentage="dataOpsScheduler?.running ? 100 : 0"
          :status="dataOpsScheduler?.last_error ? 'exception' : dataOpsScheduler?.running ? undefined : 'success'"
        />
      </div>
      <el-descriptions :column="2" border>
        <el-descriptions-item :label="databaseLocationLabel">
          <span class="mono-text">{{ databaseLocation }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="数据质量">
          <el-tag :type="qualityTagType(dataStatus?.quality?.status)" effect="plain">
            {{ dataStatus?.quality?.status ?? '-' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatBytes(dataStatus?.database.size_bytes ?? 0) }}</el-descriptions-item>
        <el-descriptions-item label="策略可交易池">{{ formatNumber(strategyTradableCount) }}</el-descriptions-item>
        <el-descriptions-item label="非 ST 股票">{{ formatNumber(dataStatus?.stock_summary.non_st_stock_count ?? 0) }}</el-descriptions-item>
        <el-descriptions-item label="ST 股票">{{ formatNumber(dataStatus?.stock_summary.st_stock_count ?? 0) }}</el-descriptions-item>
        <el-descriptions-item label="日线覆盖">
          {{ tableRange('daily_kline') }}
        </el-descriptions-item>
        <el-descriptions-item label="日线股票">
          {{ formatNumber(dataStatus?.health.daily_symbol_count ?? 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="1m覆盖">
          {{ tableRange('minute1_kline') }}
        </el-descriptions-item>
        <el-descriptions-item label="1m标的">
          {{ formatNumber(dataStatus?.health.minute1_symbol_count ?? 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="5m覆盖">
          {{ tableRange('minute5_kline') }}
        </el-descriptions-item>
        <el-descriptions-item label="5m标的">
          {{ formatNumber(dataStatus?.health.minute5_symbol_count ?? 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="快照覆盖">
          {{ tableRange('stock_quote_snapshots') }}
        </el-descriptions-item>
        <el-descriptions-item label="快照标的">
          {{ formatNumber(dataStatus?.health.quote_snapshot_symbol_count ?? 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="日线缺口">
          {{ qualityCoverageText(dataStatus?.quality?.daily) }}
        </el-descriptions-item>
        <el-descriptions-item label="分钟线缺口">
          {{ qualityCoverageText(dataStatus?.quality?.minute5) }}
        </el-descriptions-item>
        <el-descriptions-item label="日线样本">
          {{ missingSampleText(dataStatus?.quality?.daily.missing_samples) }}
        </el-descriptions-item>
        <el-descriptions-item label="分钟线样本">
          {{ missingSampleText(dataStatus?.quality?.minute5.missing_samples) }}
        </el-descriptions-item>
      </el-descriptions>
      <div v-if="scheduledQualityRows.length" class="quote-health-section">
        <div class="section-header">
          <div>
            <h3 class="section-title">定时质量检查</h3>
            <p class="section-subtitle">完整性、异常值和新鲜度检查，供每日维护和数据中心共同使用</p>
          </div>
          <el-tag :type="qualityTagType(dataStatus?.quality?.scheduled_checks?.status)" effect="plain">
            {{ dataStatus?.quality?.scheduled_checks?.status ?? '-' }}
          </el-tag>
        </div>
        <div class="quote-health-grid">
          <div v-for="row in scheduledQualityRows" :key="row.key" class="quote-health-item">
            <div class="quote-health-title">
              <span>{{ row.title }}</span>
              <el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
            </div>
            <div class="quote-health-main">{{ row.main }}</div>
            <div class="quote-health-meta">
              <span v-for="item in row.meta" :key="item">{{ item }}</span>
            </div>
            <div v-if="row.samples.length" class="quote-health-issues">
              样本：{{ row.samples.join('，') }}
            </div>
          </div>
        </div>
        <div v-if="dataStatus?.quality?.scheduled_checks?.issues.length" class="quote-health-issues">
          异常：{{ dataStatus.quality.scheduled_checks.issues.join('，') }}
        </div>
      </div>
      <div v-if="quotePipelineRows.length" class="quote-health-section">
        <div class="section-header">
          <div>
            <h3 class="section-title">快照数据体系健康</h3>
            <p class="section-subtitle">
              原始快照保留 {{ quoteSnapshotQuality?.raw_retention_days ?? '-' }} 天，聚合数据保留 {{ quoteSnapshotQuality?.aggregate_retention_days ?? '-' }} 天
            </p>
          </div>
          <el-tag :type="qualityTagType(quoteSnapshotQuality?.status)" effect="plain">
            {{ quoteSnapshotQuality?.status ?? '-' }}
          </el-tag>
        </div>
        <div class="quote-health-grid">
          <div v-for="row in quotePipelineRows" :key="row.key" class="quote-health-item">
            <div class="quote-health-title">
              <span>{{ row.title }}</span>
              <el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
            </div>
            <div class="quote-health-main">{{ row.latestLabel }}：{{ row.latestTime ?? '-' }}</div>
            <div class="quote-health-meta">
              <span>表：{{ row.table }}</span>
              <span>行数：{{ formatNumber(row.row_count) }}</span>
              <span>标的：{{ formatNumber(row.latest_symbol_count) }} / {{ formatNumber(quoteSnapshotQuality?.expected_symbols ?? 0) }}</span>
              <span>覆盖：{{ formatPercent(row.coverage_ratio) }}</span>
              <span>缺失标的：{{ formatNumber(row.missing_symbols) }}</span>
              <span>保留：{{ row.retention_days }} 天</span>
              <span>{{ row.cadenceText }}</span>
              <span v-if="row.missingRateText">缺失轮次：{{ row.missingRateText }}</span>
              <span v-if="row.recent5mText">近5分钟：{{ row.recent5mText }}</span>
              <span v-if="row.recent30mText">近30分钟：{{ row.recent30mText }}</span>
            </div>
          </div>
        </div>
        <div v-if="quoteSnapshotQuality?.issues.length" class="quote-health-issues">
          异常：{{ quoteSnapshotQuality.issues.join('，') }}
        </div>
      </div>
      <el-table :data="tableRows" height="250" empty-text="暂无表信息">
        <el-table-column prop="name" label="表" min-width="160" />
        <el-table-column label="行数" width="130" align="right">
          <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
        </el-table-column>
        <el-table-column label="标的数" width="100" align="right">
          <template #default="{ row }">{{ row.symbol_count == null ? '-' : formatNumber(row.symbol_count) }}</template>
        </el-table-column>
        <el-table-column label="日期范围" min-width="220">
          <template #default="{ row }">{{ row.date_range ? `${row.date_range.start ?? '-'} / ${row.date_range.end ?? '-'}` : '-' }}</template>
        </el-table-column>
      </el-table>
      <div class="advanced-maintenance">
        <div>
          <div class="operation-title">高级维护</div>
          <div class="operation-desc">兼容旧 SQLite 数据源，通常不需要日常执行。</div>
        </div>
        <el-button plain size="small" :loading="syncing" @click="syncStockDb">同步旧 Stock DB</el-button>
      </div>
    </div>

  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type DataHealthRepairPlan, type DataOpsSchedulerStatus, type DataReliabilityReport, type DataStatusResponse, type JobRecord, type JobStatus, type Minute5MonitorStatus, type QuoteSnapshotMonitorStatus } from '../api/client'

const dataStatus = ref<DataStatusResponse | null>(null)
const loading = ref(false)
const syncing = ref(false)
const syncingMinute5 = ref(false)
const maintaining = ref(false)
const repairingHealth = ref(false)
const repairPlanLoading = ref(false)
const monitorChanging = ref(false)
const syncJob = ref<JobRecord | null>(null)
const minute5Job = ref<JobRecord | null>(null)
const maintenanceJob = ref<JobRecord | null>(null)
const healthRepairJob = ref<JobRecord | null>(null)
const minute5Monitor = ref<Minute5MonitorStatus | null>(null)
const quoteSnapshotMonitor = ref<QuoteSnapshotMonitorStatus | null>(null)
const dataOpsScheduler = ref<DataOpsSchedulerStatus | null>(null)
const repairPlan = ref<DataHealthRepairPlan | null>(null)
const reliabilityReport = ref<DataReliabilityReport | null>(null)
const minute5TradeDate = ref(todayLabel())
let operationalRefreshTimer: number | null = null
let dataStatusRefreshTimer: number | null = null

const tableRows = computed(() => Object.entries(dataStatus.value?.tables ?? {}).map(([name, table]) => ({
  name,
  ...table
})))
const datasetHealthRows = computed(() => dataStatus.value?.datasets_health ?? [])
const quoteSnapshotQuality = computed(() => dataStatus.value?.quality?.quote_snapshots)
const scheduledQuality = computed(() => dataStatus.value?.quality?.scheduled_checks)
const strategyTradableCount = computed(() => dataStatus.value?.quality?.expected_strategy_tradable_symbols ?? dataStatus.value?.stock_summary.non_st_stock_count ?? 0)
const ignoredIssueCount = computed(() => dataStatus.value?.quality?.ignored_issues?.length ?? 0)
const ignoredIssuesText = computed(() => dataStatus.value?.quality?.ignored_issues?.join('，') || '无')
const quoteRollupTitles: Record<string, string> = {
  '1m': '1m 聚合',
  '5m': '5m 聚合'
}
const quotePipelineRows = computed(() => {
  const quality = quoteSnapshotQuality.value
  if (!quality) return []
  const raw = quality.raw
  const rows = [{
    key: 'raw',
    title: '秒级原始',
    table: raw.table,
    latestLabel: '最新快照',
    latestTime: raw.latest_datetime,
    row_count: raw.row_count,
    latest_symbol_count: raw.latest_symbol_count,
    missing_symbols: raw.missing_symbols,
    coverage_ratio: raw.coverage_ratio,
    retention_days: raw.retention_days,
    status: raw.status,
    cadenceText: `目标 ${raw.expected_interval_seconds}s，实际 ${formatOptionalSeconds(raw.actual_avg_interval_seconds)}`,
    missingRateText: `${formatNumber(raw.missing_rounds)} / ${formatNumber(raw.expected_rounds)}，${formatPercent(raw.missing_rate)}`,
    recent5mText: quoteWindowText(raw.recent_windows?.['5m']),
    recent30mText: quoteWindowText(raw.recent_windows?.['30m'])
  }]
  for (const label of ['1m', '5m']) {
    const rollup = quality.rollups[label]
    if (!rollup) continue
    rows.push({
      key: label,
      title: quoteRollupTitles[label],
      table: rollup.table,
      latestLabel: '最新桶',
      latestTime: rollup.latest_bucket,
      row_count: rollup.row_count,
      latest_symbol_count: rollup.latest_symbol_count,
      missing_symbols: rollup.missing_symbols,
      coverage_ratio: rollup.coverage_ratio,
      retention_days: rollup.retention_days,
      status: rollup.status,
      cadenceText: `桶宽 ${formatOptionalSeconds(rollup.bucket_seconds)}`,
      missingRateText: '',
      recent5mText: '',
      recent30mText: ''
    })
  }
  return rows
})
const overallReadiness = computed(() => {
  const status = dataStatus.value?.quality?.status
  if (status === 'ok') return '数据可用'
  if (status === 'warning') return '有告警'
  if (status === 'missing') return '数据缺失'
  if (status === 'unavailable') return '不可用'
  return '-'
})
const scheduledFreshnessText = computed(() => {
  const freshness = dataStatus.value?.quality?.scheduled_checks?.freshness
  if (!freshness) return '等待检查'
  return `滞后 ${freshness.lag_days ?? '-'} 天 / 阈值 ${freshness.max_lag_days} 天`
})
const minute5ReadinessText = computed(() => {
  const minute5 = dataStatus.value?.quality?.minute5
  if (!minute5) return '等待检查'
  return `覆盖 ${formatPercent(minute5.coverage_ratio)}，重复 ${formatNumber(minute5.extra_rows ?? 0)} 行`
})
const quoteSnapshotReadinessText = computed(() => {
  const raw = dataStatus.value?.quality?.quote_snapshots?.raw
  if (!raw) return '等待检查'
  return `覆盖 ${formatPercent(raw.coverage_ratio)}，缺失轮次 ${formatPercent(raw.missing_rate)}`
})
const assetRows = computed(() => {
  const status = dataStatus.value
  const quality = status?.quality
  return [
    {
      key: 'base',
      title: '策略可交易池',
      status: status?.database.exists ? 'ok' : 'missing',
      range: `${formatNumber(strategyTradableCount.value)} 只可交易标的`,
      symbols: `非 ST ${formatNumber(status?.stock_summary.non_st_stock_count ?? 0)}`,
      purpose: '尾盘策略目标池、名称、ST过滤'
    },
    {
      key: 'daily',
      title: '日线行情',
      status: quality?.daily.status ?? 'missing',
      range: tableRange('daily_kline'),
      symbols: `标的 ${formatNumber(status?.health.daily_symbol_count ?? 0)}`,
      purpose: '回测、趋势、因子、完整性检查'
    },
    {
      key: 'minute',
      title: '分钟行情',
      status: quality?.minute5.status ?? 'missing',
      range: tableRange('minute5_kline'),
      symbols: `5m ${formatNumber(status?.health.minute5_symbol_count ?? 0)} / 1m ${formatNumber(status?.health.minute1_symbol_count ?? 0)}`,
      purpose: '尾盘策略、盘中预演、复盘'
    },
    {
      key: 'snapshot',
      title: '盘中快照',
      status: quality?.quote_snapshots?.status ?? 'missing',
      range: tableRange('stock_quote_snapshots'),
      symbols: `标的 ${formatNumber(status?.health.quote_snapshot_symbol_count ?? 0)}`,
      purpose: '实时状态、快照聚合、盘中信号'
    },
    {
      key: 'fund',
      title: '基金尾盘',
      status: status?.tables.fund_tail_nav ? 'ok' : 'info',
      range: tableRange('fund_tail_nav'),
      symbols: `净值 ${formatNumber(status?.tables.fund_tail_nav?.row_count ?? 0)} 行`,
      purpose: '基金尾盘建议、代理行情、基准'
    },
  ]
})
const operationRows = computed(() => [
  {
    key: 'maintenance',
    title: '日常维护',
    status: maintenanceJob.value?.status ?? (maintaining.value ? 'running' : 'idle'),
    type: jobStatusType(maintenanceJob.value?.status ?? (maintaining.value ? 'running' : 'pending')),
    detail: maintenanceJob.value?.progress.message || '补数据、质量检查、可选策略复核'
  },
  {
    key: 'minute5',
    title: '5分钟线更新',
    status: minute5Job.value?.status ?? (syncingMinute5.value ? 'running' : 'idle'),
    type: jobStatusType(minute5Job.value?.status ?? (syncingMinute5.value ? 'running' : 'pending')),
    detail: minute5Job.value?.progress.message || `目标日期 ${minute5TradeDate.value}`
  },
  {
    key: 'minute5-monitor',
    title: '分钟线持续更新',
    status: minute5Monitor.value?.running ? 'running' : 'stopped',
    type: minute5Monitor.value?.running ? 'success' : 'info',
    detail: minute5MonitorText.value
  },
  {
    key: 'quote-monitor',
    title: '行情快照采集',
    status: quoteSnapshotMonitor.value?.running ? 'running' : 'stopped',
    type: quoteSnapshotMonitor.value?.running ? 'success' : 'info',
    detail: quoteSnapshotMonitorText.value
  },
  {
    key: 'data-ops-scheduler',
    title: '自动数据运维',
    status: dataOpsScheduler.value?.running ? 'running' : 'stopped',
    type: dataOpsScheduler.value?.running ? 'success' : 'info',
    detail: dataOpsSchedulerText.value
  }
])
const consumerReadinessRows = computed(() => {
  const quality = dataStatus.value?.quality
  const dailyOk = quality?.scheduled_checks?.freshness.status === 'ok' && quality?.scheduled_checks?.today_anomalies.status === 'ok'
  const minuteOk = quality?.minute5.status === 'ok'
  const snapshotOk = quality?.quote_snapshots?.status === 'ok'
  return [
    {
      key: 'tail-live',
      title: '可用于尾盘选股',
      status: dailyOk && minuteOk && snapshotOk ? 'ok' : 'warning',
      detail: dailyOk && minuteOk && snapshotOk ? '日线、5m、快照均满足' : '检查日线/分钟线/快照告警'
    },
    {
      key: 'backtest',
      title: '可用于回测',
      status: dailyOk && minuteOk ? 'ok' : 'warning',
      detail: dailyOk && minuteOk ? '日线和5m覆盖可用' : '分钟或日线质量存在告警'
    },
    {
      key: 'stock-trend',
      title: '可用于个股趋势',
      status: dailyOk && minuteOk ? 'ok' : 'warning',
      detail: dailyOk && minuteOk ? '趋势图和分钟走势可用' : '趋势分析可能缺少分钟数据'
    },
    {
      key: 'fund-tail',
      title: '可用于基金尾盘',
      status: dataStatus.value?.tables.fund_tail_nav ? 'ok' : 'info',
      detail: dataStatus.value?.tables.fund_tail_nav ? '基金净值和代理行情已入库' : '基金表未纳入当前状态接口'
    }
  ]
})
const scheduledQualityRows = computed(() => {
  const quality = scheduledQuality.value
  if (!quality) return []
  const completeness = quality.completeness_30d
  const anomalies = quality.today_anomalies
  const historicalInvalid = quality.historical_invalid_prices
  const freshness = quality.freshness
  const rows = [
    {
      key: 'completeness_30d',
      title: '近30日完整性',
      status: completeness.status,
      main: `不足 ${formatNumber(completeness.min_required_days)} 天：${formatNumber(completeness.affected_symbols)} 只`,
      meta: [
        `窗口：${formatNumber(completeness.window_days)} 天`,
        `阈值：${formatNumber(completeness.min_required_days)} 天`
      ],
      samples: completeness.samples.map((item) => `${item.symbol} ${item.name} ${formatNumber(item.data_days)}天`)
    },
    {
      key: 'today_anomalies',
      title: '今日异常值',
      status: anomalies.status,
      main: `异常记录：${formatNumber(anomalies.bad_rows)} 条`,
      meta: [`检查日期：${anomalies.latest_date ?? '-'}`, '规则：价格 <= 0 或成交量 <= 0'],
      samples: anomalies.samples.map((item) => `${item.symbol} ${item.date} O:${item.open} H:${item.high} L:${item.low} C:${item.close} V:${formatNumber(item.volume)}`)
    },
    ...(historicalInvalid
      ? [{
          key: 'historical_invalid_prices',
          title: '历史价格污染',
          status: historicalInvalid.status,
          main: `异常 ${formatNumber(historicalInvalid.bad_rows)} 条 / ${formatNumber(historicalInvalid.affected_symbols)} 只`,
          meta: [
            `范围：${historicalInvalid.start_date ?? '-'} / ${historicalInvalid.end_date ?? '-'}`,
            '规则：历史 OHLC <= 0'
          ],
          samples: historicalInvalid.samples.map((item) => `${item.symbol} ${item.name} ${formatNumber(item.bad_rows)}条`)
        }]
      : []),
    {
      key: 'freshness',
      title: '数据新鲜度',
      status: freshness.status,
      main: `滞后：${freshness.lag_days ?? '-'} 天`,
      meta: [
        `最新：${freshness.latest_date ?? '-'}`,
        `当前：${freshness.as_of_date}`,
        `阈值：${formatNumber(freshness.max_lag_days)} 天`
      ],
      samples: []
    }
  ]
  return rows
})
const databaseLocation = computed(() => {
  const database = dataStatus.value?.database
  if (!database) return '-'
  if (database.type === 'clickhouse') return `${database.host ?? '-'} / ${database.database ?? '-'}`
  return database.path ?? '-'
})
const databaseTitle = computed(() => (
  dataStatus.value?.database.type === 'clickhouse' ? 'ClickHouse 数据源' : '本地 Stock DB'
))
const databaseLocationLabel = computed(() => (
  dataStatus.value?.database.type === 'clickhouse' ? '连接' : '路径'
))
const minute5MonitorText = computed(() => {
  const monitor = minute5Monitor.value
  if (!monitor) return '未加载'
  const result = monitor.last_result ?? {}
  const displayCycle = Math.max(monitor.started_count ?? 0, monitor.cycle_count + monitor.skip_count)
  if (result.skip_reason) {
    const message = typeof result.message === 'string' ? result.message : String(result.skip_reason)
    const error = monitor.last_error ? `，错误：${monitor.last_error}` : ''
    return `轮次 ${displayCycle}，完成 ${monitor.cycle_count} 次，跳过 ${monitor.skip_count} 次，${message}${error}`
  }
  const target = result.target_datetime ?? '-'
  const inserted = result.inserted_rows ?? 0
  const skipped = result.skipped ?? 0
  const remaining = result.remaining_symbols ?? 0
  const partial = result.partial ? `，剩余 ${remaining} 只待补` : ''
  const error = monitor.last_error ? `，错误：${monitor.last_error}` : ''
  return `轮次 ${displayCycle}，完成 ${monitor.cycle_count} 次，目标 ${target}，插入 ${inserted} 行，跳过 ${skipped}${partial}${error}`
})
const minute5MonitorModeText = computed(() => {
  const monitor = minute5Monitor.value
  if (!monitor) return '模式：-'
  return `模式：${monitor.mode === 'auto' ? '自动守护' : '手动'}`
})
const minute5MonitorSessionText = computed(() => {
  const monitor = minute5Monitor.value
  if (!monitor) return '交易窗口：-'
  return `交易窗口：${monitor.session.open ? '可执行' : monitor.session.message}`
})
const quoteSnapshotMonitorText = computed(() => {
  const monitor = quoteSnapshotMonitor.value
  if (!monitor) return '未加载'
  const result = monitor.last_result ?? {}
  if (result.skip_reason) {
    const message = typeof result.message === 'string' ? result.message : String(result.skip_reason)
    const error = monitor.last_error ? `，错误：${monitor.last_error}` : ''
    return `轮次 ${monitor.cycle_count}，跳过 ${monitor.skip_count} 次，失败 ${monitor.failure_count} 次，${message}${error}`
  }
  const inserted = result.inserted_rows ?? 0
  const quoteRows = result.quote_rows ?? 0
  const latest = result.latest_quote_time ?? '-'
  const timeout = result.timeout ? '，本轮超时' : ''
  const error = monitor.last_error ? `，错误：${monitor.last_error}` : ''
  return `轮次 ${monitor.cycle_count}，快照 ${quoteRows} 条，写入 ${inserted} 行，最新 ${latest}${timeout}${error}`
})
const quoteSnapshotMonitorModeText = computed(() => {
  const monitor = quoteSnapshotMonitor.value
  if (!monitor) return '模式：-'
  return `模式：${monitor.mode === 'auto' ? '自动守护' : '手动'}`
})
const quoteSnapshotMonitorSessionText = computed(() => {
  const monitor = quoteSnapshotMonitor.value
  if (!monitor) return '交易窗口：-'
  return `交易窗口：${monitor.session.open ? '可执行' : monitor.session.message}`
})
const quoteSnapshotMonitorCadenceText = computed(() => {
  const monitor = quoteSnapshotMonitor.value
  if (!monitor) return '节拍：-'
  return `节拍：${monitor.config.interval_seconds ?? '-'}s，超时 ${monitor.timeout_count} 次，chunk ${monitor.effective_chunk_size ?? monitor.config.chunk_size ?? '-'}`
})
const quoteSnapshotMonitorTimingText = computed(() => {
  const monitor = quoteSnapshotMonitor.value
  const timings = monitor?.last_result?.timings
  if (!timings || typeof timings !== 'object') return '耗时：-'
  const fetch = Number((timings as Record<string, unknown>).fetch_seconds ?? 0)
  const write = Number((timings as Record<string, unknown>).write_seconds ?? 0)
  const rollup = Number((timings as Record<string, unknown>).rollup_seconds ?? 0)
  return `耗时：拉取 ${formatOptionalSeconds(fetch)}，写入 ${formatOptionalSeconds(write)}，聚合 ${formatOptionalSeconds(rollup)}`
})
const dataOpsSchedulerText = computed(() => {
  const scheduler = dataOpsScheduler.value
  if (!scheduler) return '未加载'
  const result = scheduler.last_result ?? {}
  const jobStatus = typeof result.status === 'string' ? result.status : ''
  const jobId = typeof result.id === 'string' ? result.id : typeof result.job_id === 'string' ? result.job_id : ''
  const jobText = jobStatus ? `，最近任务 ${jobStatus}${jobId ? ` / ${jobId}` : ''}` : ''
  const error = scheduler.last_error ? `，错误：${scheduler.last_error}` : ''
  return `阶段 ${scheduler.phase}，检查 ${scheduler.cycle_count} 次，维护 ${scheduler.maintenance_count} 次，跳过 ${scheduler.skip_count} 次${jobText}${error}`
})

async function loadData() {
  loading.value = true
  try {
    const [reliabilityResponse, monitorResponse, quoteSnapshotMonitorResponse, dataOpsSchedulerResponse] = await Promise.all([
      api.getDataReliability(),
      api.getMinute5Monitor(),
      api.getQuoteSnapshotMonitor(),
      api.getDataOpsScheduler()
    ])
    reliabilityReport.value = reliabilityResponse
    dataStatus.value = reliabilityResponse.data_status
    repairPlan.value = reliabilityResponse.repair_plan
    minute5Monitor.value = monitorResponse
    quoteSnapshotMonitor.value = quoteSnapshotMonitorResponse
    dataOpsScheduler.value = dataOpsSchedulerResponse
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载数据中心失败')
  } finally {
    loading.value = false
  }
}

async function loadRepairPlan() {
  repairPlanLoading.value = true
  try {
    repairPlan.value = await api.getDataHealthRepairPlan()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载修复计划失败')
  } finally {
    repairPlanLoading.value = false
  }
}

async function refreshOperationalStatus() {
  try {
    const [monitorResponse, quoteSnapshotMonitorResponse, dataOpsSchedulerResponse] = await Promise.all([
      api.getMinute5Monitor(),
      api.getQuoteSnapshotMonitor(),
      api.getDataOpsScheduler()
    ])
    minute5Monitor.value = monitorResponse
    quoteSnapshotMonitor.value = quoteSnapshotMonitorResponse
    dataOpsScheduler.value = dataOpsSchedulerResponse
  } catch {
    // Keep the last known status on transient refresh failures.
  }
}

async function refreshDataStatus() {
  try {
    const reliabilityResponse = await api.getDataReliability()
    reliabilityReport.value = reliabilityResponse
    dataStatus.value = reliabilityResponse.data_status
    repairPlan.value = reliabilityResponse.repair_plan
  } catch {
    // Keep the last known data status on transient refresh failures.
  }
}

async function loadMinute5Monitor() {
  try {
    minute5Monitor.value = await api.getMinute5Monitor()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载分钟线持续更新状态失败')
  }
}

async function toggleMinute5Monitor() {
  if (minute5Monitor.value?.running) {
    await stopMinute5Monitor()
  } else {
    await startMinute5Monitor()
  }
}

async function startMinute5Monitor() {
  monitorChanging.value = true
  try {
    minute5Monitor.value = await api.startMinute5Monitor({
      trade_date: minute5TradeDate.value,
      interval_seconds: 60,
      limit: 0,
      include_st: false
    })
    ElMessage.success('分钟线持续更新已启动')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '启动持续更新失败')
  } finally {
    monitorChanging.value = false
  }
}

async function stopMinute5Monitor() {
  monitorChanging.value = true
  try {
    minute5Monitor.value = await api.stopMinute5Monitor()
    ElMessage.success('分钟线持续更新已停止')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '停止持续更新失败')
  } finally {
    monitorChanging.value = false
  }
}

async function syncStockDb() {
  syncing.value = true
  try {
    const response = await api.syncStockDb({ backup: true })
    const completed = await pollSyncJob(response.job_id)
    if (completed) {
      ElMessage.success('旧 Stock DB 同步完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '旧 Stock DB 同步失败')
  } finally {
    syncing.value = false
  }
}

async function syncMinute5() {
  if (!minute5TradeDate.value) {
    ElMessage.warning('请选择 5分钟线日期')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将按非 ST 股票全市场更新 ${minute5TradeDate.value} 的 5分钟线，任务可能运行较久。`,
      '更新 5分钟线',
      { type: 'warning', confirmButtonText: '开始更新', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  syncingMinute5.value = true
  try {
    const response = await api.syncMinute5({
      trade_date: minute5TradeDate.value,
      limit: 0,
      include_st: false
    })
    const completed = await pollMinute5Job(response.job_id)
    if (completed) {
      ElMessage.success('5分钟线更新完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '5分钟线更新失败')
  } finally {
    syncingMinute5.value = false
  }
}

async function runDailyMaintenance() {
  const tradeDate = dataStatus.value?.health.daily_latest_date
  try {
    await ElMessageBox.confirm(
      `将执行${tradeDate ? ` ${tradeDate}` : ''} 的 ClickHouse 日常维护：5分钟线补齐、缺失重试、尾盘策略复核。`,
      '日常维护',
      { type: 'warning', confirmButtonText: '开始维护', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  maintaining.value = true
  try {
    const response = await api.runDailyMaintenance({
      trade_date: tradeDate ?? null,
      retry_no_data: true,
      run_strategy_review: true,
      strategy_limit: 500,
      strategy_top_n: 10
    })
    const completed = await pollMaintenanceJob(response.job_id)
    if (completed) {
      ElMessage.success('日常维护完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '日常维护失败')
  } finally {
    maintaining.value = false
  }
}

async function repairDataHealth() {
  try {
    await ElMessageBox.confirm(
      `将自动执行 ${repairPlan.value?.summary.auto_repair_count ?? 0} 个可处理修复项；历史回填类手动项不会自动执行。`,
      '自动修复数据告警',
      { type: 'warning', confirmButtonText: '开始修复', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  repairingHealth.value = true
  try {
    const actionKeys = repairPlan.value?.actions.filter((action) => action.auto_repair).map((action) => action.key) ?? []
    const response = await api.repairDataHealth({ action_keys: actionKeys })
    const completed = await pollHealthRepairJob(response.job_id)
    if (completed) {
      ElMessage.success('数据健康修复完成')
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '数据健康修复失败')
  } finally {
    repairingHealth.value = false
  }
}

async function pollSyncJob(jobId: string) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    syncJob.value = await api.getJob(jobId)
    if (syncJob.value.status === 'success') return true
    if (syncJob.value.status === 'failed') {
      ElMessage.error(syncJob.value.error ?? '旧 Stock DB 同步失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('同步仍在运行，请稍后刷新任务状态')
  return false
}

async function pollMinute5Job(jobId: string) {
  for (let attempt = 0; attempt < 7200; attempt += 1) {
    minute5Job.value = await api.getJob(jobId)
    if (minute5Job.value.status === 'success') return true
    if (minute5Job.value.status === 'failed') {
      ElMessage.error(minute5Job.value.error ?? '5分钟线更新失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('5分钟线更新仍在运行，请稍后刷新任务状态')
  return false
}

async function pollMaintenanceJob(jobId: string) {
  for (let attempt = 0; attempt < 7200; attempt += 1) {
    maintenanceJob.value = await api.getJob(jobId)
    if (maintenanceJob.value.status === 'success') return true
    if (maintenanceJob.value.status === 'failed') {
      ElMessage.error(maintenanceJob.value.error ?? '日常维护失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('日常维护仍在运行，请稍后刷新任务状态')
  return false
}

async function pollHealthRepairJob(jobId: string) {
  for (let attempt = 0; attempt < 7200; attempt += 1) {
    healthRepairJob.value = await api.getJob(jobId)
    if (healthRepairJob.value.status === 'success') return true
    if (healthRepairJob.value.status === 'failed') {
      ElMessage.error(healthRepairJob.value.error ?? '数据健康修复失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('数据健康修复仍在运行，请稍后刷新任务状态')
  return false
}

function todayLabel() {
  return new Date().toLocaleDateString('en-CA')
}

function jobStatusType(status: JobStatus) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function qualityTagType(status?: string) {
  if (status === 'ok') return 'success'
  if (status === 'warning') return 'warning'
  if (status === 'missing' || status === 'unavailable') return 'danger'
  return 'info'
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function tableRange(tableName: string) {
  const range = dataStatus.value?.tables[tableName]?.date_range
  return range ? `${range.start ?? '-'} / ${range.end ?? '-'}` : '-'
}

function qualityCoverageText(row?: { covered_symbols: number; missing_symbols: number; coverage_ratio: number }) {
  if (!row) return '-'
  return `覆盖 ${formatNumber(row.covered_symbols)}，缺 ${formatNumber(row.missing_symbols)}，${formatPercent(row.coverage_ratio)}`
}

function missingSampleText(samples?: Array<{ symbol: string; name: string }>) {
  if (!samples?.length) return '-'
  return samples.map((item) => `${item.symbol} ${item.name}`).join('，')
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function quoteWindowText(row?: { missing_rate: number; actual_avg_interval_seconds?: number | null }) {
  if (!row) return ''
  return `${formatPercent(row.missing_rate)}，间隔 ${formatOptionalSeconds(row.actual_avg_interval_seconds)}`
}

function formatOptionalSeconds(value?: number | null) {
  if (value == null) return '-'
  if (value >= 60 && value % 60 === 0) return `${value / 60}m`
  return `${value}s`
}

function datasetHealthRangeText(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  if (!row.range) return `行数 ${formatNumber(row.rows)}`
  return `${row.range.start ?? '-'} / ${row.range.end ?? '-'}，${formatNumber(row.rows)} 行`
}

function datasetHealthCoverageText(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  const symbolText = row.expected_symbols
    ? `${formatNumber(row.symbols)} / ${formatNumber(row.expected_symbols)}`
    : formatNumber(row.symbols)
  const ratioText = row.coverage_ratio == null ? '-' : formatPercent(row.coverage_ratio)
  return `${symbolText}，${ratioText}`
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function startAutoRefresh() {
  stopAutoRefresh()
  operationalRefreshTimer = window.setInterval(refreshOperationalStatus, 3000)
  dataStatusRefreshTimer = window.setInterval(refreshDataStatus, 15000)
}

function stopAutoRefresh() {
  if (operationalRefreshTimer !== null) {
    window.clearInterval(operationalRefreshTimer)
    operationalRefreshTimer = null
  }
  if (dataStatusRefreshTimer !== null) {
    window.clearInterval(dataStatusRefreshTimer)
    dataStatusRefreshTimer = null
  }
}

onMounted(async () => {
  await loadData()
  startAutoRefresh()
})
onBeforeUnmount(stopAutoRefresh)
</script>

<style scoped>
.overview-panel {
  display: grid;
  gap: 14px;
}

.no-top-margin {
  margin-top: 0;
}

.compact-section-header {
  margin: 2px 0 8px;
}

.readiness-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.readiness-item,
.asset-item,
.operation-item,
.consumer-item {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  min-width: 0;
  padding: 12px;
}

.readiness-item {
  display: grid;
  gap: 5px;
}

.readiness-item strong {
  color: #20242a;
  font-size: 17px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.readiness-item small,
.ignored-issues-strip small,
.consumer-desc,
.operation-desc {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.45;
}

.ignored-issues-strip {
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  color: #606266;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  padding: 9px 12px;
}

.ignored-issues-strip span {
  color: #303133;
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
}

.ignored-issues-strip small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.consumer-strip,
.asset-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.ops-grid {
  align-items: start;
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1.4fr) minmax(360px, 0.8fr);
}

.asset-title,
.consumer-title {
  align-items: center;
  color: #303133;
  display: flex;
  font-size: 14px;
  font-weight: 650;
  gap: 8px;
  justify-content: space-between;
  margin-bottom: 8px;
}

.asset-meta {
  color: #606266;
  display: grid;
  font-size: 12px;
  gap: 5px;
  line-height: 1.45;
}

.operation-list {
  display: grid;
  gap: 10px;
}

.operation-item {
  align-items: flex-start;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.operation-title {
  color: #303133;
  font-size: 14px;
  font-weight: 650;
  margin-bottom: 4px;
}

.dataset-health-name,
.dataset-health-range {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.dataset-health-name strong,
.dataset-health-range span {
  color: #303133;
  font-size: 13px;
  line-height: 1.35;
}

.dataset-health-name small,
.dataset-health-range small {
  color: #909399;
  font-size: 12px;
  line-height: 1.35;
}

.dataset-health-detail {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  display: grid;
  gap: 8px;
  margin: 6px 0;
  padding: 12px;
}

.dataset-health-detail div {
  display: grid;
  gap: 8px;
  grid-template-columns: 90px minmax(0, 1fr);
}

.dataset-health-detail strong {
  color: #606266;
  font-size: 12px;
}

.dataset-health-detail span {
  color: #303133;
  font-size: 12px;
  line-height: 1.5;
}

.inline-control {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.advanced-maintenance {
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  margin-top: 12px;
  padding: 12px;
}

.sync-progress {
  margin-bottom: 14px;
}

.sync-progress-header {
  align-items: center;
  color: #606266;
  display: flex;
  font-size: 13px;
  justify-content: space-between;
  margin-bottom: 8px;
}

.monitor-meta {
  color: #909399;
  display: grid;
  font-size: 12px;
  gap: 6px 18px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 8px;
}

.section-header {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin: 18px 0 12px;
}

.section-title {
  color: #303133;
  font-size: 16px;
  font-weight: 650;
  line-height: 1.35;
  margin: 0;
}

.section-subtitle {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin: 4px 0 0;
}

.quote-health-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 12px;
}

.quote-health-item {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
}

.quote-health-title {
  align-items: center;
  color: #303133;
  display: flex;
  font-size: 14px;
  font-weight: 650;
  justify-content: space-between;
  margin-bottom: 8px;
}

.quote-health-main {
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
}

.quote-health-meta {
  color: #606266;
  display: grid;
  font-size: 12px;
  gap: 5px 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.quote-health-issues {
  color: #b88230;
  font-size: 12px;
  line-height: 1.6;
  margin-bottom: 12px;
}

.repair-plan-panel {
  border-top: 1px solid #ebeef5;
  margin-top: 14px;
  padding-top: 14px;
}

.repair-plan-head,
.repair-action-item {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.repair-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.repair-action-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.repair-action-item {
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  color: #303133;
  font-size: 13px;
  padding: 9px 10px;
}

.repair-action-item small {
  color: #909399;
  flex: 1;
  min-width: 0;
}

@media (max-width: 1100px) {
  .readiness-grid,
  .consumer-strip,
  .asset-grid,
  .ops-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .monitor-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quote-health-grid {
    grid-template-columns: 1fr;
  }

  .repair-plan-head,
  .repair-action-item {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .readiness-grid,
  .consumer-strip,
  .asset-grid,
  .ops-grid {
    grid-template-columns: 1fr;
  }

  .monitor-meta {
    grid-template-columns: 1fr;
  }

  .section-header {
    display: block;
  }

  .quote-health-meta {
    grid-template-columns: 1fr;
  }
}
</style>
