<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">基金尾盘</h1>
      <div class="toolbar">
        <el-date-picker v-model="tradeDate" type="date" value-format="YYYY-MM-DD" />
        <el-button :loading="submitting" type="primary" @click="runAdvice">刷新行情并生成建议</el-button>
        <el-button :loading="loading" @click="refreshVisibleData">刷新页面</el-button>
      </div>
    </div>

    <el-alert
      v-if="loadError"
      :title="loadError"
      type="error"
      show-icon
      :closable="false"
      class="compact-alert"
    />

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">基金池</div>
        <div class="metric-value">{{ universe.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">数据正常</div>
        <div class="metric-value">{{ normalDataCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最新代理行情</div>
        <div class="metric-value">{{ latestProxyDate ?? '-' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">代理未到交易日</div>
        <div class="metric-value">{{ staleProxyCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">建议行数</div>
        <div class="metric-value">{{ report.rows.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">报告更新</div>
        <div class="metric-value">{{ formatDateTime(report.report_updated_at) }}</div>
      </div>
    </div>

    <div class="panel compact-panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">数据可信度</h2>
        <div class="toolbar">
          <el-tag :type="trustStatus.type" effect="plain">{{ trustStatus.text }}</el-tag>
          <el-tag effect="plain">报告 {{ formatDateTime(report.report_updated_at) }}</el-tag>
        </div>
      </div>
      <div class="fund-trust-grid">
        <div class="fund-trust-item">
          <div class="metric-label">代理行情</div>
          <div class="fund-trust-value">{{ proxyFreshCount }}/{{ dataStatus.length }}</div>
          <div class="fund-trust-sub">最新 {{ latestProxyDate ?? '-' }}</div>
        </div>
        <div class="fund-trust-item">
          <div class="metric-label">基金净值</div>
          <div class="fund-trust-value">{{ navAvailableCount }}/{{ dataStatus.length }}</div>
          <div class="fund-trust-sub">最新 {{ latestNavDate ?? '-' }}</div>
        </div>
        <div class="fund-trust-item">
          <div class="metric-label">建议结果</div>
          <div class="fund-trust-value">{{ actionableRows.length }} / {{ sellAlertRows.length }} / {{ watchRows.length }}</div>
          <div class="fund-trust-sub">可操作 / 减仓提醒 / 观察等待</div>
        </div>
        <div class="fund-trust-item">
          <div class="metric-label">数据问题</div>
          <div class="fund-trust-value">{{ dataIssueRows.length }}</div>
          <div class="fund-trust-sub">{{ staleProxyCount ? `代理滞后 ${staleProxyCount}` : '代理行情正常' }}</div>
        </div>
        <div class="fund-trust-item">
          <div class="metric-label">数据源</div>
          <div class="fund-trust-value">{{ proxyRefreshSource }}</div>
          <div class="fund-trust-sub">{{ proxyRefreshTime }}</div>
        </div>
      </div>
      <div class="fund-action-strip">
        <el-tag type="success" effect="plain">可操作 {{ actionableRows.length }}</el-tag>
        <el-tag type="warning" effect="plain">减仓提醒 {{ sellAlertRows.length }}</el-tag>
        <el-tag type="info" effect="plain">观察等待 {{ watchRows.length }}</el-tag>
        <el-tag :type="dataIssueRows.length ? 'danger' : 'success'" effect="plain">数据问题 {{ dataIssueRows.length }}</el-tag>
      </div>
    </div>

    <div v-if="job" class="panel compact-panel">
      <div class="dataset-summary">
        <div>
          <div class="metric-label">当前任务</div>
          <div class="summary-title">{{ job.id }}</div>
        </div>
        <el-tag :type="statusType(job.status)" effect="plain">{{ job.status }}</el-tag>
        <el-tag v-if="report.data_refreshed" type="success" effect="plain">已刷新数据</el-tag>
        <el-tag v-if="job.error" type="danger" effect="plain">{{ job.error }}</el-tag>
      </div>
      <div class="job-progress-panel">
        <el-progress :percentage="jobProgressPercent" :status="jobProgressStatus" :stroke-width="10" />
        <div class="progress-message">{{ job.progress?.message ?? '-' }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">基金池管理</h2>
        <div class="toolbar">
          <el-select v-model="watchlistStatusFilter" style="width: 130px">
            <el-option label="全部" value="all" />
            <el-option label="持有中" value="holding" />
            <el-option label="准备买入" value="candidate" />
            <el-option label="观察中" value="watching" />
            <el-option label="暂停监控" value="paused" />
          </el-select>
          <el-button type="primary" @click="openWatchlistDialog()">新增基金</el-button>
        </div>
      </div>
      <el-table :data="filteredWatchlist" height="360" empty-text="暂无基金池数据">
        <el-table-column prop="fund_code" label="代码" width="86" fixed />
        <el-table-column prop="fund_name" label="基金" min-width="220" fixed show-overflow-tooltip />
        <el-table-column label="状态" width="104">
          <template #default="{ row }">
            <el-tag :type="watchlistStatusType(row.status)" effect="plain">
              {{ watchlistStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关注等级" width="104">
          <template #default="{ row }">{{ watchlistPriorityText(row.priority) }}</template>
        </el-table-column>
        <el-table-column label="基金类型" width="104">
          <template #default="{ row }">{{ fundTypeText(row.fund_type) }}</template>
        </el-table-column>
        <el-table-column label="参与建议" width="104">
          <template #default="{ row }">
            <el-tag :type="row.include_in_advice && row.enabled ? 'success' : 'info'" effect="plain">
              {{ row.include_in_advice && row.enabled ? '参与' : '不参与' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最新净值" width="104" align="right">
          <template #default="{ row }">{{ formatOptionalNumber(row.latest_nav) }}</template>
        </el-table-column>
        <el-table-column label="代理涨跌" width="104" align="right">
          <template #default="{ row }">
            <span :class="returnClass(row.proxy_return_pct)">
              {{ formatOptionalPercent(row.proxy_return_pct) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="预估涨跌" width="104" align="right">
          <template #default="{ row }">
            <span :class="returnClass(row.estimated_change_pct)">
              {{ formatOptionalPercent(row.estimated_change_pct) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="数据日期" width="152">
          <template #default="{ row }">
            <div class="fund-date-stack">
              <span>净值 {{ row.latest_nav_date || '-' }}</span>
              <span>代理 {{ row.latest_proxy_date || '-' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openWatchlistDialog(row)">编辑</el-button>
            <el-button link type="danger" @click="deleteWatchlistItem(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">基金尾盘建议</h2>
        <el-button :loading="submitting" @click="runAdvice">刷新行情并重算建议</el-button>
      </div>
      <el-table :data="adviceRows" height="520" :default-sort="{ prop: '操作等级', order: 'ascending' }">
        <el-table-column prop="基金代码" label="代码" width="86" fixed />
        <el-table-column prop="基金名称" label="基金" min-width="220" fixed show-overflow-tooltip />
        <el-table-column prop="今日代理涨跌率" label="涨跌" width="86" sortable />
        <el-table-column
          prop="操作等级"
          label="等级"
          width="92"
          sortable
          :filters="gradeFilters"
          :filter-method="filterGrade"
        />
        <el-table-column prop="最终操作建议" label="建议" width="110" />
        <el-table-column
          prop="卖出等级"
          label="卖出等级"
          width="104"
          sortable
          :filters="gradeFilters"
          :filter-method="filterSellGrade"
        />
        <el-table-column prop="卖出建议" label="卖出建议" width="116" />
        <el-table-column prop="卖出评分" label="卖出评分" width="104" sortable>
          <template #default="{ row }">
            <el-tag :type="sellScoreType(row['卖出评分'])" effect="plain">
              {{ formatNumber(row['卖出评分']) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="卖出原因" label="卖出原因" min-width="160" show-overflow-tooltip />
        <el-table-column prop="代理标的" label="代理标的" width="122" show-overflow-tooltip />
        <el-table-column label="匹配度" width="108" sortable sort-by="代理匹配度">
          <template #default="{ row }">
            <el-tag :type="proxyFitType(row['代理匹配等级'])" effect="plain">
              {{ formatPercent(row['代理匹配度']) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="预测加仓评分" label="评分" width="92" sortable>
          <template #default="{ row }">
            <el-tag :type="scoreType(row['预测加仓评分'])" effect="plain">
              {{ formatNumber(row['预测加仓评分']) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="3日胜率" width="100" sortable sort-by="3日预测上涨概率">
          <template #default="{ row }">{{ formatPercent(row['3日预测上涨概率']) }}</template>
        </el-table-column>
        <el-table-column label="5日胜率" width="100" sortable sort-by="5日预测上涨概率">
          <template #default="{ row }">{{ formatPercent(row['5日预测上涨概率']) }}</template>
        </el-table-column>
        <el-table-column label="5日中位收益" width="120" sortable sort-by="5日预测中位数收益">
          <template #default="{ row }">{{ formatPercent(row['5日预测中位数收益']) }}</template>
        </el-table-column>
        <el-table-column label="跌超2%" width="96" sortable sort-by="5日预测跌超2%概率">
          <template #default="{ row }">
            <el-tag :type="riskType(row['5日预测跌超2%概率'])" effect="plain">
              {{ formatPercent(row['5日预测跌超2%概率']) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="样本/可信度" width="128">
          <template #default="{ row }">
            <el-tag :type="confidenceType(predictionConfidence(row).level)" effect="plain">
              {{ predictionConfidence(row).sample }} / {{ predictionConfidence(row).level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="建议原因" label="主要扣分" min-width="160" show-overflow-tooltip />
        <el-table-column label="近5日" width="92" sortable sort-by="近5日涨跌率">
          <template #default="{ row }">{{ row['近5日涨跌率'] || '-' }}</template>
        </el-table-column>
        <el-table-column label="20日回撤" width="100" sortable sort-by="20日回撤">
          <template #default="{ row }">{{ row['20日回撤'] || '-' }}</template>
        </el-table-column>
        <el-table-column label="涨跌分位" width="100" sortable sort-by="今日涨跌分位">
          <template #default="{ row }">{{ row['今日涨跌分位'] || '-' }}</template>
        </el-table-column>
        <el-table-column label="数据状态" width="112">
          <template #default="{ row }">
            <el-tag :type="dataStateType(row.数据状态)" effect="plain">{{ row.数据状态 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="净值日期" width="112">
          <template #default="{ row }">
            <el-tag :type="dataDateType(row.NAV日期, Boolean(row.NAV日期))" effect="plain">
              {{ row.NAV日期 || '缺失' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="代理行情" width="120">
          <template #default="{ row }">
            <el-tag :type="dataDateType(row.Proxy日期, Boolean(row.Proxy日期))" effect="plain">
              {{ row.Proxy日期 || '缺失' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <div>
          <h2 class="page-title">机会发现</h2>
          <div class="metric-label">从候选基金池中筛出适合尾盘观察或小额试探的基金</div>
        </div>
        <div class="toolbar">
          <el-tag effect="plain">{{ opportunityReport.rows.length }}</el-tag>
          <el-button :loading="opportunitySubmitting" type="primary" @click="runOpportunityDiscovery">
            生成机会
          </el-button>
        </div>
      </div>
      <el-table :data="opportunityRows" height="420" :default-sort="{ prop: '预测加仓评分', order: 'descending' }">
        <el-table-column prop="基金代码" label="代码" width="86" fixed />
        <el-table-column prop="基金名称" label="基金" min-width="220" fixed show-overflow-tooltip />
        <el-table-column prop="机会类型" label="机会类型" width="124" />
        <el-table-column prop="机会等级" label="机会等级" width="104" sortable />
        <el-table-column prop="机会建议" label="机会建议" width="140" />
        <el-table-column prop="候选层级" label="候选层级" width="104" />
        <el-table-column prop="费率标签" label="费率" width="104" />
        <el-table-column prop="最短观察周期" label="观察周期" width="104" />
        <el-table-column prop="预测加仓评分" label="评分" width="92" sortable>
          <template #default="{ row }">
            <el-tag :type="scoreType(row['预测加仓评分'])" effect="plain">
              {{ formatNumber(row['预测加仓评分']) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="5日胜率" width="100" sortable sort-by="5日预测上涨概率">
          <template #default="{ row }">{{ formatPercent(row['5日预测上涨概率']) }}</template>
        </el-table-column>
        <el-table-column label="5日中位收益" width="120" sortable sort-by="5日预测中位数收益">
          <template #default="{ row }">{{ formatPercent(row['5日预测中位数收益']) }}</template>
        </el-table-column>
        <el-table-column label="跌超2%" width="96" sortable sort-by="5日预测跌超2%概率">
          <template #default="{ row }">
            <el-tag :type="riskType(row['5日预测跌超2%概率'])" effect="plain">
              {{ formatPercent(row['5日预测跌超2%概率']) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="机会原因" label="机会原因" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="128" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="row['是否已在观察池'] === '是' || row['机会类型'] === '明确排除'"
              @click="addOpportunityToWatchlist(row)"
            >
              加入观察池
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">Markdown 报告</h2>
        <el-tag v-if="job" :type="job.status === 'success' ? 'success' : job.status === 'failed' ? 'danger' : 'warning'">
          {{ job.status }}
        </el-tag>
      </div>
      <pre class="markdown-preview">{{ report.markdown || '暂无报告' }}</pre>
    </div>

    <el-dialog
      v-model="watchlistDialogVisible"
      :title="watchlistEditingCode ? '编辑基金' : '新增基金'"
      width="760px"
      class="watchlist-dialog"
    >
      <el-form :model="watchlistForm" label-width="110px">
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="基金代码">
              <el-input v-model="watchlistForm.fund_code" :disabled="Boolean(watchlistEditingCode)" />
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="基金名称">
              <el-input v-model="watchlistForm.fund_name" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="状态">
              <el-select v-model="watchlistForm.status">
                <el-option label="持有中" value="holding" />
                <el-option label="准备买入" value="candidate" />
                <el-option label="观察中" value="watching" />
                <el-option label="暂停监控" value="paused" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="关注等级">
              <el-select v-model="watchlistForm.priority">
                <el-option label="核心" value="core" />
                <el-option label="普通" value="normal" />
                <el-option label="低" value="low" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="基金类型">
              <el-select v-model="watchlistForm.fund_type">
                <el-option label="宽基" value="broad_index" />
                <el-option label="消费" value="consumer" />
                <el-option label="医药" value="medical" />
                <el-option label="海外" value="overseas" />
                <el-option label="债基" value="bond" />
                <el-option label="行业主题" value="sector" />
                <el-option label="其他" value="other" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="启用">
              <el-switch v-model="watchlistForm.enabled" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="参与建议">
              <el-switch v-model="watchlistForm.include_in_advice" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="watchlistForm.status === 'holding'" :gutter="12">
          <el-col :span="12">
            <el-form-item label="成本净值">
              <el-input
                v-model.number="watchlistForm.position_cost"
                type="number"
                inputmode="decimal"
                placeholder="如 1.2345"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="浮盈亏%">
              <el-input
                v-model.number="watchlistForm.position_return_pct"
                type="number"
                inputmode="decimal"
                placeholder="如 -12.50"
                clearable
              >
                <template #append>%</template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="持仓金额">
              <el-input
                v-model.number="watchlistForm.position_amount"
                type="number"
                inputmode="decimal"
                placeholder="如 5000"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-alert
          v-else
          title="未持有或仅观察的基金无需填写成本、金额和浮盈亏。状态改为“持有中”后再维护这些持仓信息。"
          type="info"
          show-icon
          :closable="false"
          class="watchlist-position-hint"
        />
        <el-form-item label="备注">
          <el-input v-model="watchlistForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="watchlistDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveWatchlistItem">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type FundTailDataStatusItem, type FundTailOpportunityResponse, type FundTailReportResponse, type FundTailUniverseItem, type FundWatchlistItem, type JobRecord, type JobStatus } from '../api/client'

const loading = ref(false)
const submitting = ref(false)
const loadError = ref('')
const universe = ref<FundTailUniverseItem[]>([])
const watchlist = ref<FundWatchlistItem[]>([])
const watchlistStatusFilter = ref('all')
const watchlistDialogVisible = ref(false)
const watchlistEditingCode = ref('')
const watchlistForm = ref<WatchlistForm>(emptyWatchlistForm())
const report = ref<FundTailReportResponse>({
  rows: [],
  markdown: '',
  data_refreshed: false,
  proxy_refresh: null,
  data_status: [],
  report_path: '',
  markdown_path: '',
  report_updated_at: null,
  markdown_updated_at: null
})
const opportunityReport = ref<FundTailOpportunityResponse>({
  rows: [],
  markdown: '',
  report_path: '',
  markdown_path: '',
  report_updated_at: null,
  markdown_updated_at: null
})
const activeJobId = ref('')
const job = ref<JobRecord | null>(null)
const opportunitySubmitting = ref(false)
const tradeDate = ref(new Date().toISOString().slice(0, 10))
const proxyRefreshTimer = ref<number | null>(null)
const props = defineProps<{
  jobId?: string
}>()
const gradeFilters = [
  { text: 'A', value: 'A' },
  { text: 'B', value: 'B' },
  { text: 'C', value: 'C' },
  { text: 'D', value: 'D' }
]
type AdviceRow = Record<string, unknown>
type WatchlistForm = Omit<FundWatchlistItem, 'position_return_pct'> & {
  position_return_pct: number | null
}

const dataStatus = computed<FundTailDataStatusItem[]>(() => universe.value.length ? universe.value : report.value.data_status ?? [])
const filteredWatchlist = computed(() => {
  if (watchlistStatusFilter.value === 'all') return watchlist.value
  return watchlist.value.filter((item) => item.status === watchlistStatusFilter.value)
})
const dataStatusByCode = computed(() => new Map(dataStatus.value.map((item) => [item.code, item])))
const adviceRows = computed<AdviceRow[]>(() => report.value.rows.map((row) => {
  const code = String(row['基金代码'] ?? '')
  const status = dataStatusByCode.value.get(code)
  return {
    ...row,
    NAV日期: status?.latest_nav_date ?? '',
    Proxy日期: status?.latest_proxy_date ?? '',
    数据状态: fundDataState(status)
  } as AdviceRow
}))
const opportunityRows = computed(() => opportunityReport.value.rows)
const latestProxyDate = computed(() => latestDate(dataStatus.value.map((item) => item.latest_proxy_date)))
const latestNavDate = computed(() => latestDate(dataStatus.value.map((item) => item.latest_nav_date)))
const proxyFreshCount = computed(() => dataStatus.value.filter((item) => isFreshForTradeDate(item.latest_proxy_date)).length)
const navAvailableCount = computed(() => dataStatus.value.filter((item) => item.has_nav && Boolean(item.latest_nav_date)).length)
const staleProxyCount = computed(() => dataStatus.value.filter((item) => !isFreshForTradeDate(item.latest_proxy_date)).length)
const normalDataCount = computed(() => dataStatus.value.filter((item) => fundDataState(item) === '正常').length)
const actionableRows = computed(() => adviceRows.value.filter((row) => ['尾盘加仓', '小额试探'].includes(String(row['最终操作建议'] ?? ''))))
const sellAlertRows = computed(() => adviceRows.value.filter((row) => {
  const advice = String(row['卖出建议'] ?? '')
  return advice !== '' && advice !== '不卖出'
}))
const dataIssueRows = computed(() => adviceRows.value.filter((row) => String(row['数据状态'] ?? '') !== '正常'))
const watchRows = computed(() => adviceRows.value.filter((row) => {
  const code = String(row['基金代码'] ?? '')
  return !actionableRows.value.some((item) => String(item['基金代码'] ?? '') === code)
    && !sellAlertRows.value.some((item) => String(item['基金代码'] ?? '') === code)
    && !dataIssueRows.value.some((item) => String(item['基金代码'] ?? '') === code)
}))
const trustStatus = computed(() => {
  if (!dataStatus.value.length) return { type: 'info' as const, text: '等待数据' }
  if (staleProxyCount.value > 0 || dataIssueRows.value.length > 0) return { type: 'warning' as const, text: '需要核对' }
  return { type: 'success' as const, text: '可用' }
})
const proxyRefreshSource = computed(() => String(report.value.proxy_refresh?.source ?? (report.value.data_refreshed ? 'legacy' : '-')))
const proxyRefreshTime = computed(() => String(report.value.proxy_refresh?.latest_timestamp ?? '最新刷新时间 -'))
const jobProgressPercent = computed(() => Math.max(0, Math.min(100, Number(job.value?.progress?.percent ?? 0))))
const jobProgressStatus = computed(() => {
  if (job.value?.status === 'success') return 'success'
  if (job.value?.status === 'failed') return 'exception'
  return undefined
})

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const results = await Promise.allSettled([
      api.listFundTailUniverse(),
      api.listFundTailWatchlist(),
      api.getFundTailReport(),
      api.getFundTailOpportunities()
    ])
    applyLoadResult(results)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '基金尾盘数据加载异常'
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}

function applyLoadResult(results: PromiseSettledResult<unknown>[]) {
  const [universeResult, watchlistResult, reportResult, opportunityResult] = results
  let failed = 0
  if (universeResult.status === 'fulfilled') {
    universe.value = (universeResult.value as { items: FundTailUniverseItem[] }).items
  } else {
    failed += 1
  }
  if (watchlistResult.status === 'fulfilled') {
    watchlist.value = (watchlistResult.value as { items: FundWatchlistItem[] }).items
  } else {
    failed += 1
  }
  if (reportResult.status === 'fulfilled') {
    const reportResponse = reportResult.value as FundTailReportResponse
    report.value = {
      ...reportResponse,
      data_refreshed: reportResponse.data_refreshed ?? false,
      proxy_refresh: reportResponse.proxy_refresh ?? null,
      data_status: reportResponse.data_status ?? universe.value
    }
  } else {
    failed += 1
  }
  if (opportunityResult.status === 'fulfilled') {
    opportunityReport.value = opportunityResult.value as FundTailOpportunityResponse
  } else {
    failed += 1
  }
  if (failed > 0) {
    loadError.value = `基金尾盘数据加载异常：${failed} 项接口失败，请检查后端服务或稍后刷新`
    ElMessage.warning(`基金尾盘部分数据加载失败：${failed} 项`)
  }
}

async function refreshVisibleData() {
  await loadAll()
  await refreshProxyData(true)
}

async function refreshProxyData(silent = false) {
  try {
    const response = await api.refreshFundTailProxy({ trade_date: tradeDate.value })
    universe.value = response.universe
    watchlist.value = response.items
    report.value = {
      ...report.value,
      data_refreshed: true,
      proxy_refresh: response.proxy_refresh,
      data_status: response.universe
    }
    if (!silent) ElMessage.success('基金代理行情已刷新')
  } catch (error) {
    if (!silent) ElMessage.error(error instanceof Error ? error.message : '刷新基金代理行情失败')
  }
}

function startAutoProxyRefresh() {
  if (proxyRefreshTimer.value !== null) {
    window.clearInterval(proxyRefreshTimer.value)
  }
  proxyRefreshTimer.value = window.setInterval(() => {
    void refreshProxyData(true)
  }, 60_000)
}

function emptyWatchlistForm(): WatchlistForm {
  return {
    fund_code: '',
    fund_name: '',
    status: 'watching',
    priority: 'normal',
    fund_type: 'other',
    enabled: true,
    include_in_advice: true,
    position_cost: null,
    position_amount: null,
    position_return_pct: null,
    note: ''
  }
}

function openWatchlistDialog(item?: FundWatchlistItem) {
  watchlistEditingCode.value = item?.fund_code ?? ''
  watchlistForm.value = item
    ? { ...item, position_return_pct: decimalToPercent(item.position_return_pct) }
    : emptyWatchlistForm()
  watchlistDialogVisible.value = true
}

async function saveWatchlistItem() {
  const code = watchlistForm.value.fund_code.trim().padStart(6, '0')
  if (!/^\d{6}$/.test(code)) {
    ElMessage.error('基金代码需为 6 位数字')
    return
  }
  if (!watchlistForm.value.fund_name.trim()) {
    ElMessage.error('基金名称不能为空')
    return
  }
  const payload = {
    ...watchlistForm.value,
    fund_code: code,
    fund_name: watchlistForm.value.fund_name.trim(),
    position_cost: nullableNumber(watchlistForm.value.position_cost),
    position_amount: nullableNumber(watchlistForm.value.position_amount),
    position_return_pct: percentToDecimal(watchlistForm.value.position_return_pct)
  }
  try {
    await api.upsertFundTailWatchlistItem(code, payload)
    watchlistDialogVisible.value = false
    await loadWatchlist()
    ElMessage.success('基金池已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存基金失败')
  }
}

async function deleteWatchlistItem(item: FundWatchlistItem) {
  try {
    await ElMessageBox.confirm(`确认删除 ${item.fund_name}（${item.fund_code}）？`, '删除基金', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await api.deleteFundTailWatchlistItem(item.fund_code)
    await loadWatchlist()
    ElMessage.success('基金已删除')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

async function loadWatchlist() {
  const response = await api.listFundTailWatchlist()
  watchlist.value = response.items
}

async function runAdvice() {
  submitting.value = true
  try {
    const response = await api.submitFundTailAdvice({
      trade_date: tradeDate.value,
      refresh_data: true
    })
    activeJobId.value = response.job_id
    const completed = await pollJobUntilDone(response.job_id)
    if (completed) {
      await loadAll()
      ElMessage.success('基金尾盘建议已生成')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function runOpportunityDiscovery() {
  opportunitySubmitting.value = true
  try {
    const response = await api.submitFundTailOpportunities({
      trade_date: tradeDate.value
    })
    const completed = await pollJobUntilDone(response.job_id, 'opportunity')
    if (completed) {
      await loadAll()
      ElMessage.success('基金机会发现已生成')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '机会发现提交失败')
  } finally {
    opportunitySubmitting.value = false
  }
}

async function addOpportunityToWatchlist(row: AdviceRow) {
  const code = String(row['基金代码'] ?? '').padStart(6, '0')
  const name = String(row['基金名称'] ?? '')
  if (!/^\d{6}$/.test(code) || !name) {
    ElMessage.error('机会行缺少基金代码或名称')
    return
  }
  const payload: FundWatchlistItem = {
    fund_code: code,
    fund_name: name,
    status: 'candidate',
    priority: row['机会等级'] === 'A' ? 'core' : 'normal',
    fund_type: fundTypeFromOpportunity(row),
    enabled: true,
    include_in_advice: true,
    position_cost: null,
    position_amount: null,
    position_return_pct: null,
    note: `机会发现：${String(row['机会建议'] ?? '')}；${String(row['机会原因'] ?? '')}`
  }
  try {
    await api.upsertFundTailWatchlistItem(code, payload)
    await loadWatchlist()
    opportunityReport.value = {
      ...opportunityReport.value,
      rows: opportunityReport.value.rows.map((item) => (
        String(item['基金代码'] ?? '').padStart(6, '0') === code
          ? { ...item, 是否已在观察池: '是', 机会类型: '已在观察池' }
          : item
      ))
    }
    ElMessage.success('已加入观察池')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加入观察池失败')
  }
}

async function refreshJob() {
  if (!activeJobId.value) return
  job.value = await api.getJob(activeJobId.value)
  if (job.value.status === 'success' && job.value.result) {
    applyJobResult(job.value.result)
    await loadAll()
  }
  if (job.value.status === 'failed') {
    ElMessage.error(job.value.error ?? '基金尾盘建议生成失败')
  }
}

async function loadJob(jobId: string) {
  if (!jobId) return
  activeJobId.value = jobId
  await refreshJob()
}

function applyJobResult(value: Record<string, unknown>) {
  const result = value as unknown as FundTailReportResponse
  report.value = {
    rows: result.rows ?? [],
    markdown: result.markdown ?? '',
    data_refreshed: result.data_refreshed ?? false,
    proxy_refresh: result.proxy_refresh ?? null,
    data_status: result.data_status ?? [],
    report_path: result.report_path ?? '',
    markdown_path: result.markdown_path ?? '',
    report_updated_at: result.report_updated_at ?? null,
    markdown_updated_at: result.markdown_updated_at ?? null
  }
}

async function pollJobUntilDone(jobId: string, resultType: 'advice' | 'opportunity' = 'advice') {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    job.value = await api.getJob(jobId)
    if (job.value.status === 'success' && job.value.result) {
      if (resultType === 'opportunity') applyOpportunityResult(job.value.result)
      else applyJobResult(job.value.result)
      return true
    }
    if (job.value.status === 'failed') {
      ElMessage.error(job.value.error ?? '基金尾盘建议生成失败')
      return false
    }
    await sleep(1000)
  }
  ElMessage.warning('任务仍在运行，请稍后刷新')
  return false
}

function applyOpportunityResult(value: Record<string, unknown>) {
  const result = value as unknown as FundTailOpportunityResponse
  opportunityReport.value = {
    rows: result.rows ?? [],
    markdown: result.markdown ?? '',
    report_path: result.report_path ?? '',
    markdown_path: result.markdown_path ?? '',
    report_updated_at: result.report_updated_at ?? null,
    markdown_updated_at: result.markdown_updated_at ?? null
  }
}

function fundTypeFromOpportunity(row: AdviceRow) {
  const label = String(row['基金类型标签'] ?? '')
  if (label === '宽基') return 'broad_index'
  if (label === '消费') return 'consumer'
  if (label === '医药') return 'medical'
  if (label === '海外') return 'overseas'
  if (label === '行业') return 'sector'
  return 'other'
}

function latestDate(values: Array<string | null>) {
  const dates = values.filter((value): value is string => Boolean(value))
  dates.sort()
  return dates.length ? dates[dates.length - 1] : null
}

function isFreshForTradeDate(value: string | null) {
  return Boolean(value && value >= tradeDate.value)
}

function dataDateType(value: string | null, exists: boolean) {
  if (!exists || !value) return 'danger'
  return isFreshForTradeDate(value) ? 'success' : 'warning'
}

function fundDataState(item?: FundTailDataStatusItem) {
  if (!item || !item.has_nav || !item.has_proxy) return '数据缺失'
  if (!item.latest_nav_date) return 'NAV滞后'
  if (!item.latest_proxy_date || !isFreshForTradeDate(item.latest_proxy_date)) return '代理滞后'
  return '正常'
}

function dataStateType(value: string) {
  if (value === '正常') return 'success'
  if (value === '数据缺失') return 'danger'
  return 'warning'
}

function watchlistStatusText(value: string) {
  if (value === 'holding') return '持有中'
  if (value === 'candidate') return '准备买入'
  if (value === 'watching') return '观察中'
  if (value === 'paused') return '暂停监控'
  return value
}

function watchlistStatusType(value: string) {
  if (value === 'holding') return 'success'
  if (value === 'candidate') return 'warning'
  if (value === 'paused') return 'info'
  return 'primary'
}

function watchlistPriorityText(value: string) {
  if (value === 'core') return '核心'
  if (value === 'normal') return '普通'
  if (value === 'low') return '低'
  return value
}

function fundTypeText(value: string) {
  if (value === 'broad_index') return '宽基'
  if (value === 'consumer') return '消费'
  if (value === 'medical') return '医药'
  if (value === 'overseas') return '海外'
  if (value === 'bond') return '债基'
  if (value === 'sector') return '行业主题'
  if (value === 'other') return '其他'
  return value
}

function formatOptionalNumber(value: unknown) {
  const numeric = numberValue(value)
  if (!Number.isFinite(numeric)) return '-'
  return numeric.toFixed(4)
}

function formatMoney(value: unknown) {
  const numeric = numberValue(value)
  if (!Number.isFinite(numeric)) return '-'
  return numeric.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })
}

function formatOptionalPercent(value: unknown) {
  const numeric = numberValue(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${(numeric * 100).toFixed(2)}%`
}

function returnClass(value: unknown) {
  const numeric = numberValue(value)
  if (!Number.isFinite(numeric) || numeric === 0) return ''
  return numeric > 0 ? 'positive-text' : 'negative-text'
}

function nullableNumber(value: unknown) {
  const numeric = numberValue(value)
  return Number.isFinite(numeric) ? numeric : null
}

function decimalToPercent(value: unknown) {
  const numeric = numberValue(value)
  return Number.isFinite(numeric) ? Number((numeric * 100).toFixed(2)) : null
}

function percentToDecimal(value: unknown) {
  const numeric = numberValue(value)
  return Number.isFinite(numeric) ? numeric / 100 : null
}

function predictionConfidence(row: AdviceRow) {
  const sample = Math.max(numberValue(row['5日预测样本数']), numberValue(row['3日预测样本数']))
  if (sample >= 50) return { sample, level: '高' }
  if (sample >= 20) return { sample, level: '中' }
  if (sample >= 10) return { sample, level: '低' }
  return { sample, level: '很低' }
}

function confidenceType(level: string) {
  if (level === '高') return 'success'
  if (level === '中') return 'warning'
  if (level === '低') return 'warning'
  return 'danger'
}

function scoreType(value: unknown) {
  const score = numberValue(value)
  if (score >= 70) return 'success'
  if (score >= 55) return 'warning'
  return 'info'
}

function riskType(value: unknown) {
  const risk = numberValue(value)
  if (risk >= 0.2) return 'danger'
  if (risk >= 0.1) return 'warning'
  return 'success'
}

function sellScoreType(value: unknown) {
  const score = numberValue(value)
  if (score >= 70) return 'danger'
  if (score >= 55) return 'warning'
  return 'success'
}

function proxyFitType(value: unknown) {
  const level = String(value ?? '')
  if (level === '高') return 'success'
  if (level === '中') return 'warning'
  if (level === '低') return 'warning'
  return 'danger'
}

function formatPercent(value: unknown) {
  if (typeof value === 'string' && value.trim().endsWith('%')) return value.trim()
  const numeric = numberValue(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${(numeric * 100).toFixed(2)}%`
}

function formatNumber(value: unknown) {
  const numeric = numberValue(value)
  if (!Number.isFinite(numeric)) return '-'
  return numeric.toFixed(1)
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hour}:${minute}`
}

function numberValue(value: unknown) {
  if (typeof value === 'number') return value
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return NaN
    if (trimmed.endsWith('%')) return Number(trimmed.slice(0, -1)) / 100
    return Number(trimmed)
  }
  return NaN
}

function filterGrade(value: string, row: Record<string, string>) {
  return row['操作等级'] === value
}

function filterSellGrade(value: string, row: Record<string, string>) {
  return row['卖出等级'] === value
}

function statusType(status: JobStatus) {
  return status === 'success' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info'
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

onMounted(async () => {
  await loadAll()
  await refreshProxyData(true)
  startAutoProxyRefresh()
})

onBeforeUnmount(() => {
  if (proxyRefreshTimer.value !== null) {
    window.clearInterval(proxyRefreshTimer.value)
    proxyRefreshTimer.value = null
  }
})
</script>
