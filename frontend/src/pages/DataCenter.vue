<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">数据中心</h1>
      <div class="toolbar">
        <el-tag :type="qualityTagType(dataStatus?.quality?.status)" effect="plain">{{ overallReadiness }}</el-tag>
        <el-button type="primary" :loading="maintaining" @click="runDailyMaintenance">日常维护</el-button>
        <el-button :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div class="panel primary-health-panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">数据健康矩阵</h2>
          <p class="section-subtitle">按数据源查看状态、完整度、最新时间、当前告警和修复入口</p>
        </div>
        <el-tag :type="qualityTagType(dataStatus?.quality?.status)" effect="plain">{{ overallReadiness }}</el-tag>
      </div>
      <el-table
        :data="datasetHealthRows"
        v-loading="loading"
        row-key="key"
        empty-text="数据源健康信息加载中或暂无返回"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="dataset-health-detail">
              <div><strong>数据来源</strong><span>{{ row.source }}</span></div>
              <div><strong>更新机制</strong><span>{{ row.update_mechanism }}</span></div>
              <div><strong>系统使用</strong><span>{{ row.consumer }}</span></div>
              <div><strong>质量规则</strong><span>{{ datasetQualityRules(row).length ? datasetQualityRules(row).join('，') : '-' }}</span></div>
              <div><strong>底层表</strong><span class="mono-text">{{ row.table }}</span></div>
              <div><strong>告警</strong><span>{{ row.issues.length ? row.issues.join('，') : '无' }}</span></div>
              <div>
                <strong>数据修复</strong>
                <span v-if="datasetActionableRepairKeys(row).length">
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :disabled="!datasetActionableRepairKeys(row).length"
                    :loading="repairingHealth"
                    @click="repairDatasetHealth(row)"
                  >
                    修复此数据源
                  </el-button>
                </span>
                <span v-else>-</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="数据源" min-width="170">
          <template #default="{ row }">
            <div class="dataset-health-name">
              <strong>{{ row.name }}</strong>
              <small>{{ row.category }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态/完整度" min-width="210">
          <template #default="{ row }">
            <div class="dataset-health-range">
              <span>
                <el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
              </span>
              <small>{{ datasetHealthStatusSummary(row) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="最新/范围" min-width="220">
          <template #default="{ row }">
            <div class="dataset-health-range">
              <span>{{ row.latest ?? '-' }}</span>
              <small>{{ datasetHealthRangeText(row) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="当前告警" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.issues.length ? row.issues.join('，') : '无' }}</template>
        </el-table-column>
        <el-table-column label="修复" width="120" align="center">
          <template #default="{ row }">
            <template v-if="datasetActionableRepairKeys(row).length">
              <el-button
                size="small"
                type="primary"
                plain
                :disabled="!datasetActionableRepairKeys(row).length"
                :loading="repairingHealth"
                @click="repairDatasetHealth(row)"
              >
                数据修复
              </el-button>
            </template>
            <span v-else class="muted-text">-</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel data-quality-calendar-panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">数据日历</h2>
          <p class="section-subtitle">按交易日 × 数据源查看已沉淀的数据质量统计</p>
        </div>
        <div class="toolbar compact-toolbar">
          <el-date-picker
            v-model="qualityCalendarRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
          <el-select
            v-model="qualityCalendarSourceKeys"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="数据源"
            style="width: 220px"
          >
            <el-option
              v-for="source in qualityCalendarSources"
              :key="source.key"
              :label="source.name"
              :value="source.key"
            />
          </el-select>
          <el-button :loading="qualityCalendarLoading" @click="loadQualityCalendar">刷新</el-button>
          <el-button type="primary" plain :loading="qualityCalendarGenerating" @click="generateQualityCalendar">
            生成质量统计
          </el-button>
        </div>
      </div>
      <el-table
        :data="qualityCalendarRows"
        v-loading="qualityCalendarLoading"
        row-key="trade_date"
        empty-text="暂无数据日历统计"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="dataset-health-detail data-quality-calendar-detail">
              <div v-for="cell in row.sources" :key="cell.source_key">
                <strong>{{ cell.source_name }}</strong>
                <span>{{ qualityCalendarCellDetail(cell) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="trade_date" label="交易日" width="130" />
        <el-table-column label="总体状态" width="120">
          <template #default="{ row }">
            <el-tag :type="qualityTagType(row.overall_status)" effect="plain">
              {{ qualityCalendarStatusText(row.overall_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          v-for="source in qualityCalendarSources"
          :key="source.key"
          :label="source.name"
          min-width="150"
        >
          <template #default="{ row }">
            <button
              class="quality-calendar-cell"
              :class="qualityCalendarCellClass(qualityCalendarCell(row, source.key)?.status)"
              type="button"
              @click="selectedQualityCalendarCell = qualityCalendarCell(row, source.key)"
            >
              <strong>{{ qualityCalendarStatusText(qualityCalendarCell(row, source.key)?.status ?? 'unchecked') }}</strong>
              <small>{{ qualityCalendarCell(row, source.key)?.summary ?? '未检查' }}</small>
            </button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="selectedQualityCalendarCell" class="quality-calendar-selected">
        <strong>{{ selectedQualityCalendarCell.source_name }}</strong>
        <span>{{ qualityCalendarCellDetail(selectedQualityCalendarCell) }}</span>
      </div>
    </div>

    <div class="panel data-ops-task-panel">
      <div class="section-header no-top-margin">
        <div>
          <h2 class="page-title">更新任务状态</h2>
          <p class="section-subtitle">由 ClickHouse 配置和状态表驱动，runner 可独立部署到其他服务器</p>
        </div>
      </div>
      <el-table
        :data="dataOpsTaskRows"
        row-key="task_key"
        :expand-row-keys="expandedDataOpsTaskKeys"
        empty-text="暂无更新任务状态"
        @expand-change="onDataOpsTaskExpandChange"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="dataset-health-detail data-ops-task-detail">
              <div><strong>任务逻辑</strong><span>{{ dataOpsTaskDetail(row.task_key).logic }}</span></div>
              <div><strong>触发规则</strong><span>{{ dataOpsTaskDetail(row.task_key).trigger }}</span></div>
              <div><strong>读写数据</strong><span>{{ dataOpsTaskDetail(row.task_key).data }}</span></div>
              <div><strong>执行依赖</strong><span>{{ dataOpsTaskDetail(row.task_key).dependency }}</span></div>
              <div><strong>检查方式</strong><span>{{ dataOpsTaskDetail(row.task_key).verification }}</span></div>
              <div><strong>异常判断</strong><span>{{ dataOpsTaskDetail(row.task_key).failure }}</span></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="任务" min-width="170">
          <template #default="{ row }">
            <div class="dataset-health-name">
              <strong>{{ dataOpsTaskTitle(row.task_key) }}</strong>
              <small class="mono-text">{{ row.task_key }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="dataOpsTaskTagType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              :loading="dataOpsTaskChanging === row.task_key"
              @change="(value: boolean) => updateDataOpsTaskEnabled(row, value)"
            />
          </template>
        </el-table-column>
        <el-table-column label="调度配置" min-width="210">
          <template #default="{ row }">
            <div class="inline-control data-ops-schedule-control">
              <el-time-picker
                v-if="row.schedule_kind === 'daily_time'"
                :model-value="dataOpsTaskScheduleValue(row)"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="执行时间"
                style="width: 112px"
                @change="(value: string) => saveDataOpsTaskSchedule(row, value)"
              />
              <el-input-number
                v-else
                :model-value="dataOpsTaskScheduleValue(row)"
                :min="5"
                :max="86400"
                :step="5"
                controls-position="right"
                style="width: 120px"
                @change="(value: number | undefined) => saveDataOpsTaskSchedule(row, value)"
              />
              <small>{{ row.schedule_kind === 'daily_time' ? '执行时间' : '间隔秒数' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="最近运行" min-width="220">
          <template #default="{ row }">
            <div class="dataset-health-range">
              <span>{{ row.last_finished_at ?? row.last_started_at ?? '-' }}</span>
              <small>{{ row.last_error || dataOpsTaskResultText(row) }}</small>
              <el-progress
                :percentage="row.progress_percent ?? (row.status === 'success' ? 100 : 0)"
                :status="dataOpsTaskProgressStatus(row)"
              />
              <small>{{ row.progress_message ?? row.progress_stage ?? '等待进度' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="心跳/Runner" min-width="180">
          <template #default="{ row }">
            <div class="dataset-health-range">
              <span>{{ row.heartbeat_at ?? '-' }}</span>
              <small>{{ row.runner_id ?? '-' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-button
              size="small"
              plain
              :disabled="row.status === 'running'"
              :loading="dataOpsTaskChanging === row.task_key"
              @click="runDataOpsTaskOnce(row.task_key)"
            >
              手动运行一次
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-collapse v-model="advancedSections" class="advanced-diagnostics">
      <el-collapse-item title="高级诊断" name="advanced">
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
          <h2 class="page-title">尾盘模型训练数据</h2>
          <p class="section-subtitle">训练前置审计：日线、5m尾盘样本、次日标签和当前策略信号是否足够支撑模型训练</p>
        </div>
        <el-tag :type="qualityTagType(tailMlAudit?.status)" effect="plain">
          {{ tailMlAudit?.status ?? '-' }}
        </el-tag>
      </div>
      <div class="readiness-grid">
        <div class="readiness-item">
          <span class="metric-label">日线样本</span>
          <strong>{{ formatNumber(tailMlAudit?.summary.daily_rows ?? 0) }}</strong>
          <small>{{ tailMlAudit?.daily.start ?? '-' }} / {{ tailMlAudit?.daily.end ?? '-' }}，异常 {{ formatNumber(tailMlAudit?.daily.invalid_ohlc_rows ?? 0) }} 行</small>
        </div>
        <div class="readiness-item">
          <span class="metric-label">5m 可用交易日</span>
          <strong>{{ formatNumber(tailMlAudit?.summary.minute5_usable_days ?? 0) }}</strong>
          <small>目标 {{ formatNumber(tailMlAudit?.minute5.minimum_usable_days ?? 0) }} 天，覆盖 {{ formatNumber(tailMlAudit?.summary.minute5_symbols ?? 0) }} 标的</small>
        </div>
        <div class="readiness-item">
          <span class="metric-label">可生成标签日</span>
          <strong>{{ formatNumber(tailMlAudit?.summary.joinable_label_days ?? 0) }}</strong>
          <small>目标 {{ formatNumber(tailMlAudit?.labels.minimum_joinable_days ?? 0) }} 天，outcome {{ formatNumber(tailMlAudit?.labels.outcome_rows ?? 0) }} 条</small>
        </div>
        <div class="readiness-item">
          <span class="metric-label">策略可交易池</span>
          <strong>{{ formatNumber(tailMlAudit?.summary.tradable_pool ?? 0) }}</strong>
          <small>快照角色：{{ tailMlAudit?.snapshots.training_role ?? '-' }}</small>
        </div>
      </div>
      <div class="consumer-strip">
        <div v-for="row in tailMlAuditRows" :key="row.key" class="consumer-item">
          <div class="consumer-title">
            <span>{{ row.title }}</span>
            <el-tag :type="qualityTagType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
          </div>
          <div class="consumer-desc">{{ row.detail }}</div>
        </div>
      </div>
      <div v-if="tailMlAudit?.issues.length" class="diagnostic-message muted">
        模型训练限制：{{ tailMlAudit.issues.join('，') }}
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

      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type DataHealthRepairPlan, type DataOpsSchedulerStatus, type DataOpsTaskStatus, type DataQualityCalendarCell, type DataQualityCalendarDateRow, type DataQualityCalendarResponse, type DataReliabilityReport, type DataStatusResponse, type JobRecord, type JobStatus, type Minute5MonitorStatus, type QuoteSnapshotMonitorStatus, type TailMlAuditResponse } from '../api/client'

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
const dataOpsTasks = ref<DataOpsTaskStatus[]>([])
const expandedDataOpsTaskKeys = ref<string[]>([])
const dataOpsTaskChanging = ref<string | null>(null)
const repairPlan = ref<DataHealthRepairPlan | null>(null)
const reliabilityReport = ref<DataReliabilityReport | null>(null)
const qualityCalendarRange = ref<[string, string]>(defaultQualityCalendarRange())
const qualityCalendarSourceKeys = ref<string[]>([])
const qualityCalendarLoading = ref(false)
const qualityCalendarGenerating = ref(false)
const qualityCalendarReport = ref<DataQualityCalendarResponse | null>(null)
const selectedQualityCalendarCell = ref<DataQualityCalendarCell | null>(null)
const tailMlAudit = ref<TailMlAuditResponse | null>(null)
const minute5TradeDate = ref(todayLabel())
const advancedSections = ref<string[]>([])
let operationalRefreshTimer: number | null = null
let dataStatusRefreshTimer: number | null = null

const tableRows = computed(() => Object.entries(dataStatus.value?.tables ?? {}).map(([name, table]) => ({
  name,
  ...table
})))
const datasetHealthRows = computed(() => dataStatus.value?.datasets_health ?? [])
const qualityCalendarSources = computed(() => qualityCalendarReport.value?.sources ?? [])
const qualityCalendarRows = computed(() => qualityCalendarReport.value?.dates ?? [])
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
      symbols: `5m ${formatNumber(status?.health.minute5_symbol_count ?? 0)}`,
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
const dataOpsTaskRows = computed(() => dataOpsTasks.value)
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
const tailMlAuditRows = computed(() => {
  const audit = tailMlAudit.value
  if (!audit) return []
  return [
    {
      key: 'daily',
      title: '日线长周期特征',
      status: audit.daily.status,
      detail: `${audit.daily.start ?? '-'} / ${audit.daily.end ?? '-'}，${formatNumber(audit.daily.symbol_count)} 标的`
    },
    {
      key: 'minute5',
      title: '尾盘5m特征',
      status: audit.minute5.status,
      detail: `${formatNumber(audit.minute5.usable_days)} / ${formatNumber(audit.minute5.minimum_usable_days)} 个可用交易日`
    },
    {
      key: 'labels',
      title: '次日收益标签',
      status: audit.labels.status,
      detail: `${formatNumber(audit.labels.joinable_days)} / ${formatNumber(audit.labels.minimum_joinable_days)} 个可拼接标签日`
    },
    {
      key: 'signals',
      title: '现有策略信号',
      status: audit.strategy_signals.status,
      detail: `${formatNumber(audit.strategy_signals.signal_days)} 个信号日，${formatNumber(audit.strategy_signals.outcome_rows)} 条 outcome，仅作 baseline`
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
    const [reliabilityResult, monitorResult, quoteSnapshotMonitorResult, dataOpsSchedulerResult, dataOpsTasksResult, tailMlAuditResult, qualityCalendarResult] = await Promise.allSettled([
      api.getDataReliability(),
      api.getMinute5Monitor(),
      api.getQuoteSnapshotMonitor(),
      api.getDataOpsScheduler(),
      api.getDataOpsTasks(),
      api.getTailMlAudit(),
      loadQualityCalendar()
    ])
    if (reliabilityResult.status !== 'fulfilled') throw reliabilityResult.reason
    const reliabilityResponse = reliabilityResult.value
    reliabilityReport.value = reliabilityResponse
    dataStatus.value = reliabilityResponse.data_status
    repairPlan.value = reliabilityResponse.repair_plan
    if (monitorResult.status === 'fulfilled') minute5Monitor.value = monitorResult.value
    if (quoteSnapshotMonitorResult.status === 'fulfilled') quoteSnapshotMonitor.value = quoteSnapshotMonitorResult.value
    if (dataOpsSchedulerResult.status === 'fulfilled') dataOpsScheduler.value = dataOpsSchedulerResult.value
    if (dataOpsTasksResult.status === 'fulfilled') dataOpsTasks.value = dataOpsTasksResult.value.items
    if (tailMlAuditResult.status === 'fulfilled') {
      tailMlAudit.value = tailMlAuditResult.value
    } else {
      tailMlAudit.value = null
    }
    if (qualityCalendarResult.status === 'rejected') qualityCalendarReport.value = null
  } catch (error) {
    await loadDataStatusFallback()
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
    const [monitorResponse, quoteSnapshotMonitorResponse, dataOpsSchedulerResponse, dataOpsTasksResponse] = await Promise.all([
      api.getMinute5Monitor(),
      api.getQuoteSnapshotMonitor(),
      api.getDataOpsScheduler(),
      api.getDataOpsTasks()
    ])
    minute5Monitor.value = monitorResponse
    quoteSnapshotMonitor.value = quoteSnapshotMonitorResponse
    dataOpsScheduler.value = dataOpsSchedulerResponse
    dataOpsTasks.value = dataOpsTasksResponse.items
  } catch {
    // Keep the last known status on transient refresh failures.
  }
}

async function updateDataOpsTaskEnabled(row: DataOpsTaskStatus, enabled: boolean) {
  dataOpsTaskChanging.value = row.task_key
  try {
    const response = await api.updateDataOpsTaskConfig(row.task_key, {
      enabled,
      schedule_kind: row.schedule_kind,
      schedule_config: row.schedule_config
    })
    dataOpsTasks.value = dataOpsTasks.value.map(item => item.task_key === row.task_key ? response.item : item)
    ElMessage.success(enabled ? '任务已启用' : '任务已停用')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新任务配置失败')
  } finally {
    dataOpsTaskChanging.value = null
  }
}

function onDataOpsTaskExpandChange(_row: DataOpsTaskStatus, expandedRows: DataOpsTaskStatus[]) {
  expandedDataOpsTaskKeys.value = expandedRows.map(row => row.task_key)
}

async function saveDataOpsTaskSchedule(row: DataOpsTaskStatus, value: string | number | undefined) {
  if (value === undefined || value === null || value === '') return
  const scheduleConfig = dataOpsTaskScheduleConfig(row, value)
  dataOpsTaskChanging.value = row.task_key
  try {
    const response = await api.updateDataOpsTaskConfig(row.task_key, {
      enabled: row.enabled,
      schedule_kind: row.schedule_kind,
      schedule_config: scheduleConfig
    })
    dataOpsTasks.value = dataOpsTasks.value.map(item => item.task_key === row.task_key ? response.item : item)
    ElMessage.success('调度配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存调度配置失败')
  } finally {
    dataOpsTaskChanging.value = null
  }
}

async function runDataOpsTaskOnce(taskKey: string) {
  dataOpsTaskChanging.value = taskKey
  try {
    await api.runDataOpsTaskOnce(taskKey)
    ElMessage.success('已提交手动运行请求')
    const response = await api.getDataOpsTasks()
    dataOpsTasks.value = response.items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交任务失败')
  } finally {
    dataOpsTaskChanging.value = null
  }
}

async function refreshDataStatus() {
  try {
    const [reliabilityResponse] = await Promise.all([
      api.getDataReliability(),
      loadQualityCalendar()
    ])
    reliabilityReport.value = reliabilityResponse
    dataStatus.value = reliabilityResponse.data_status
    repairPlan.value = reliabilityResponse.repair_plan
  } catch {
    await loadDataStatusFallback()
  }
}

async function loadQualityCalendar() {
  qualityCalendarLoading.value = true
  try {
    const [start, end] = qualityCalendarRange.value
    qualityCalendarReport.value = await api.getDataQualityCalendar(start, end, qualityCalendarSourceKeys.value)
  } finally {
    qualityCalendarLoading.value = false
  }
}

async function generateQualityCalendar() {
  qualityCalendarGenerating.value = true
  try {
    const [start, end] = qualityCalendarRange.value
    const result = await api.generateDataQualityCalendar({
      start,
      end,
      source_keys: qualityCalendarSourceKeys.value.length ? qualityCalendarSourceKeys.value : null
    })
    ElMessage.success(`已生成 ${result.generated_dates} 个交易日、${result.rows} 条质量统计`)
    await loadQualityCalendar()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成质量统计失败')
  } finally {
    qualityCalendarGenerating.value = false
  }
}

async function loadDataStatusFallback() {
  dataStatus.value = await api.getDataStatus()
  repairPlan.value = await api.getDataHealthRepairPlan()
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

async function repairDatasetHealth(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  const actionableKeys = datasetActionableRepairKeys(row)
  if (!actionableKeys.length) {
    ElMessage.info('当前数据源没有可自动执行的修复项')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将执行 ${row.name} 的 ${actionableKeys.length} 个自动修复项：${actionableKeys.join('，')}。`,
      '数据修复',
      { type: 'warning', confirmButtonText: '开始修复', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  repairingHealth.value = true
  try {
    const response = await api.repairDataHealth({ action_keys: actionableKeys })
    const completed = await pollHealthRepairJob(response.job_id)
    if (completed) {
      ElMessage.success(`${row.name} 修复完成`)
      await loadData()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : `${row.name} 修复失败`)
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

function defaultQualityCalendarRange(): [string, string] {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 30)
  return [formatDateInput(start), formatDateInput(end)]
}

function formatDateInput(value: Date): string {
  return value.toLocaleDateString('en-CA')
}

function jobStatusType(status: JobStatus) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function qualityTagType(status?: string) {
  if (status === 'ok' || status === 'success' || status === 'idle' || status === 'skipped') return 'success'
  if (status === 'warning') return 'warning'
  if (status === 'missing' || status === 'unavailable' || status === 'failed' || status === 'stale') return 'danger'
  return 'info'
}

function dataOpsTaskTagType(status?: string) {
  if (status === 'running') return 'primary'
  if (status === 'disabled') return 'info'
  return qualityTagType(status)
}

function dataOpsTaskTitle(taskKey: string) {
  const titles: Record<string, string> = {
    stock_master_sync: '股票主数据同步',
    post_close_maintenance: '日终维护',
    minute5_intraday_sync: '5m 分钟线同步',
    quote_snapshot_capture: '行情快照采集',
    quote_rollup_refresh: '快照聚合刷新',
    quality_snapshot: '数据质量快照'
  }
  return titles[taskKey] ?? taskKey
}

function dataOpsTaskDetail(taskKey: string) {
  const details: Record<string, { logic: string; trigger: string; data: string; dependency: string; verification: string; failure: string }> = {
    stock_master_sync: {
      logic: '同步当前 A 股股票池和基础名称信息，为日线、分钟线、行情快照和质量检查提供统一标的范围。',
      trigger: '按 daily_time 执行，默认 08:30；也支持手动运行一次。',
      data: '读取腾讯 getBoardRankList 股票池接口；写入 ClickHouse stocks，并保留系统已有行业、上市日期等补充字段。',
      dependency: '依赖腾讯股票池接口、ClickHouse stocks 表和股票代码标准化规则。',
      verification: '检查 fetched_rows、inserted_rows、preserved_enrichment_rows，以及健康矩阵和后续任务的 expected_symbols 是否稳定。',
      failure: '腾讯股票池接口不可用、分页返回异常、ClickHouse 写入失败或 stocks 表结构不兼容。'
    },
    post_close_maintenance: {
      logic: '收盘后串联补齐 5m 分钟线、聚合修复日线、同步指数日线、写入质量快照；可作为日终数据闭环入口。',
      trigger: '交易日到达配置时间后执行一次，默认 15:10；也支持手动运行一次。',
      data: '读取 minute5_kline、daily_kline、index_daily、stocks；写入 daily_kline、index_daily、data_source_health、data_ops_task_runs、data_ops_task_heartbeats。',
      dependency: '依赖 ClickHouse、5m 同步函数、日线聚合函数、指数日线同步函数和质量检查函数。',
      verification: '查看任务进度、last_result、data_source_health 行数，以及健康矩阵中日线/分钟线/指数日线状态。',
      failure: '同步函数异常、ClickHouse 不可用、质量检查失败或 runner 心跳停留在 running 超过阈值。'
    },
    minute5_intraday_sync: {
      logic: '交易时段按配置间隔检查当日 5m K 线缺口，只同步 minute5_kline 未达到当前目标时间或 bar 数不足的标的，为尾盘策略、个股趋势和日终日线聚合提供分钟数据。',
      trigger: '交易日上午和下午时段按 interval_seconds 执行，默认 60 秒；非交易日和非交易时段跳过。',
      data: '读取 ClickHouse stocks 作为股票池，默认排除 ST；最近 7 天优先腾讯行情，失败或无数据后回退新浪、AKShare；历史日期优先新浪，再腾讯、AKShare；写入 ClickHouse minute5_kline，并记录 data_ops 心跳和运行结果。',
      dependency: '依赖腾讯 ifzq.gtimg.cn 5m K 线接口、新浪分钟行情、AKShare/东方财富分钟行情、ClickHouse stocks 和 minute5_kline。',
      verification: '检查 minute5_kline 最新桶、覆盖标的数、缺失标的样本、inserted_rows、remaining_symbols 和任务进度。',
      failure: '行情源无数据、网络超时、单轮执行超过 interval_seconds 后调度被后续轮次挤压、ClickHouse 写入失败或长时间 running 无心跳。'
    },
    quote_snapshot_capture: {
      logic: '交易时段按高频间隔采集实时行情快照，为盘中状态、快照聚合和尾盘快速数据模式提供输入。',
      trigger: '交易时段按 interval_seconds 执行，默认 10 秒；非交易时段跳过。',
      data: '读取 Tencent 实时行情；写入 stock_quote_snapshots，并记录 data_ops 心跳和运行结果。',
      dependency: '依赖实时行情源、网络稳定性、chunk 配置和 ClickHouse 写入能力。',
      verification: '检查 stock_quote_snapshots 最新时间、覆盖标的数、缺失轮次和任务进度。',
      failure: '行情源超时、chunk 过大导致失败、快照缺失率过高或 ClickHouse 写入失败。'
    },
    quote_rollup_refresh: {
      logic: '把原始行情快照合并刷新成 1m/5m 聚合层，供分钟图、尾盘快照兜底和质量检查使用。',
      trigger: '交易时段按 interval_seconds 执行，默认 60 秒；也可手动运行。',
      data: '读取 stock_quote_snapshots；写入或优化 stock_quote_snapshots_1m、stock_quote_snapshots_5m。',
      dependency: '依赖原始快照已有数据、ClickHouse 聚合/优化能力。',
      verification: '检查 1m/5m 聚合最新桶、重复键、覆盖标的数和快照数据体系健康。',
      failure: '原始快照为空、聚合表重复异常、OPTIMIZE 失败或 ClickHouse 不可用。'
    },
    quality_snapshot: {
      logic: '按配置间隔执行数据质量检查，并把健康矩阵核心结果写入历史快照，方便趋势化观察。',
      trigger: '按 interval_seconds 执行，默认 300 秒；可手动运行一次。',
      data: '读取 ClickHouse system tables、daily_kline、minute5_kline、stock_quote_snapshots、聚合表等；写入 data_source_health。',
      dependency: '依赖质量检查 SQL、ClickHouse 读写能力和数据源健康规则。',
      verification: '检查 data_source_health 新增行数、健康矩阵状态和任务 last_result.rows。',
      failure: '质量 SQL 执行失败、ClickHouse 不可用、写入 data_source_health 失败或 runner 心跳超时。'
    }
  }
  return details[taskKey] ?? {
    logic: '未登记任务逻辑。',
    trigger: '按 ClickHouse 中的任务配置执行。',
    data: '查看任务配置和运行结果确认读写范围。',
    dependency: '查看 runner 日志确认依赖。',
    verification: '查看任务状态、运行结果和心跳。',
    failure: '查看最近错误和 runner 日志。'
  }
}

function dataOpsTaskResultText(row: DataOpsTaskStatus) {
  const keys = Object.keys(row.last_result ?? {})
  if (!keys.length) return '暂无结果'
  return keys.slice(0, 3).join('，')
}

function dataOpsTaskProgressStatus(row: DataOpsTaskStatus) {
  if (row.status === 'failed' || row.status === 'stale') return 'exception'
  if (row.status === 'success') return 'success'
  return undefined
}

function qualityCalendarCell(row: DataQualityCalendarDateRow, sourceKey: string) {
  return row.sources.find((cell) => cell.source_key === sourceKey) ?? null
}

function qualityCalendarStatusText(status: string) {
  if (status === 'ok') return '正常'
  if (status === 'warning') return '告警'
  if (status === 'failed') return '失败'
  if (status === 'catching_up') return '追赶中'
  if (status === 'unchecked') return '未检查'
  return status || '-'
}

function qualityCalendarCellClass(status?: string) {
  return status ?? 'unchecked'
}

function qualityCalendarCellDetail(cell: DataQualityCalendarCell) {
  const parts = [
    `状态 ${qualityCalendarStatusText(cell.status)}`,
    `覆盖 ${formatNumber(cell.covered_symbols)}/${formatNumber(cell.expected_symbols)}`,
    `缺桶 ${formatNumber(cell.missing_buckets)}`,
    `重复 ${formatNumber(cell.duplicate_rows)}`,
    `最大断档 ${formatOptionalSeconds(cell.max_gap_seconds)}`,
    `可修复性 ${cell.repairability}`
  ]
  if (cell.latest_time) parts.push(`最新 ${cell.latest_time}`)
  return parts.join('，')
}

function dataOpsTaskScheduleValue(row: DataOpsTaskStatus) {
  if (row.schedule_kind === 'daily_time') {
    return typeof row.schedule_config.time === 'string' ? row.schedule_config.time : '15:10'
  }
  const value = Number(row.schedule_config.interval_seconds ?? 60)
  return Number.isFinite(value) ? value : 60
}

function dataOpsTaskScheduleConfig(row: DataOpsTaskStatus, value: string | number) {
  if (row.schedule_kind === 'daily_time') return { ...row.schedule_config, time: String(value) }
  return { ...row.schedule_config, interval_seconds: Number(value) }
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

function datasetHealthStatusSummary(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  const issueText = row.issues.length ? `告警 ${formatNumber(row.issues.length)} 项` : '无告警'
  return `${datasetHealthCoverageText(row)}，${issueText}`
}

function datasetQualityRules(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  return row.quality_rules ?? []
}

function datasetRepairActionKeys(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  return row.repair_action_keys ?? []
}

function datasetActionableRepairKeys(row: NonNullable<DataStatusResponse['datasets_health']>[number]) {
  const configuredKeys = datasetRepairActionKeys(row)
  return (repairPlan.value?.actions ?? [])
    .filter((action) => action.auto_repair && configuredKeys.includes(action.key))
    .map((action) => action.key)
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

.data-quality-calendar-detail {
  grid-template-columns: 1fr;
}

.quality-calendar-cell {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  color: var(--el-text-color-primary);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  justify-content: center;
  min-height: 54px;
  padding: 8px;
  text-align: left;
  width: 100%;
}

.quality-calendar-cell small {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quality-calendar-cell.ok {
  background: var(--el-color-success-light-9);
  border-color: var(--el-color-success-light-5);
}

.quality-calendar-cell.warning,
.quality-calendar-cell.catching_up {
  background: var(--el-color-warning-light-9);
  border-color: var(--el-color-warning-light-5);
}

.quality-calendar-cell.failed {
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-5);
}

.quality-calendar-cell.unchecked {
  background: #f8fafc;
  border-style: dashed;
}

.quality-calendar-selected {
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  color: #606266;
  display: flex;
  font-size: 13px;
  gap: 12px;
  margin-top: 12px;
  padding: 10px 12px;
}

.quality-calendar-selected strong {
  color: #303133;
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
