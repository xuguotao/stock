<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">可用股票池</h1>
        <p class="page-subtitle">统一观察目录、日线与流动性标签，筛选不会改变实际执行股票池。</p>
      </div>
      <div class="toolbar">
        <el-button @click="router.push({ name: 'mootdx-monitor' })">返回数据源</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <section class="panel universe-panel">
      <div class="section-header">
        <div>
          <h2>股票池快照</h2>
          <p>基准交易日 {{ profileSummary.as_of_date ?? '-' }}，计算于 {{ profileSummary.computed_at ?? '-' }}。</p>
        </div>
        <div class="snapshot-actions">
          <el-tag effect="plain">规则版本 {{ profileSummary.rule_version || '-' }}</el-tag>
          <el-button size="small" :loading="profilesLoading" :disabled="!profileSummary.symbols" @click="loadProfiles(1)">刷新标的列表</el-button>
        </div>
      </div>
      <p class="rule-summary">规则：{{ ruleSummary }}</p>

      <div class="funnel" aria-label="可用股票池漏斗">
        <button v-for="item in funnel" :key="item.key" class="funnel-step" type="button" @click="applyFunnelFilter(item.key)">
          <span>{{ item.label }}</span>
          <strong>{{ formatNumber(item.value) }}</strong>
          <small>{{ funnelSummary(item.key) }}</small>
        </button>
      </div>

      <div class="filter-bar">
        <div class="filter-controls">
          <el-select v-model="selectedFilters.market" multiple collapse-tags collapse-tags-tooltip clearable placeholder="市场" aria-label="市场筛选">
            <el-option label="深市" value="SZ" /><el-option label="沪市" value="SH" /><el-option label="北交所" value="BJ" />
          </el-select>
          <el-select v-model="selectedFilters.is_st" multiple collapse-tags collapse-tags-tooltip clearable placeholder="ST 状态" aria-label="ST 状态筛选">
            <el-option label="非 ST" value="0" /><el-option label="ST" value="1" />
          </el-select>
          <el-select v-model="selectedFilters.latest_daily_valid" multiple collapse-tags collapse-tags-tooltip clearable placeholder="日线状态" aria-label="日线状态筛选">
            <el-option label="最新日线有效" value="1" /><el-option label="最新日线缺失" value="0" />
          </el-select>
          <el-select v-model="selectedFilters.trading_days" multiple collapse-tags collapse-tags-tooltip clearable placeholder="近 20 日成交" aria-label="近二十日成交筛选">
            <el-option label="少于 15 日" value="lt_15" /><el-option label="15 日及以上" value="gte_15" />
          </el-select>
          <el-select v-model="selectedFilters.average_amount" multiple collapse-tags collapse-tags-tooltip clearable placeholder="日均成交额" aria-label="日均成交额筛选">
            <el-option label="低于 1,000 万" value="lt_10m" /><el-option label="1,000 万至 5,000 万" value="10_50m" /><el-option label="5,000 万以上" value="gte_50m" />
          </el-select>
          <el-select v-model="selectedFilters.liquidity_level" multiple collapse-tags collapse-tags-tooltip clearable placeholder="流动性等级" aria-label="流动性等级筛选">
            <el-option label="高流动性" value="high" /><el-option label="中流动性" value="medium" /><el-option label="低流动性" value="low" />
          </el-select>
          <el-select v-model="selectedFilters.exclusion_reason" multiple collapse-tags collapse-tags-tooltip clearable placeholder="排除原因" aria-label="排除原因筛选">
            <el-option v-for="item in baseProfile?.distributions.exclusion_reasons ?? []" :key="item.key" :label="exclusionLabel(item.key)" :value="item.key" />
          </el-select>
        </div>
        <div class="filter-result">
          <span>当前命中</span>
          <strong>{{ formatNumber(profileSummary.symbols) }}</strong><span>只</span>
          <el-button text :disabled="!selectedFilterChips.length" @click="clearFilters">清空筛选</el-button>
        </div>
      </div>

      <section class="pool-explorer" aria-label="排除原因标的分布">
        <aside class="reason-tree">
          <div class="explorer-heading"><h3>排除原因</h3><span>可多选精确筛选</span></div>
          <el-tree ref="reasonTreeRef" :data="reasonTree" node-key="id" show-checkbox check-strictly :default-expanded-keys="defaultExpandedReasons" :props="treeProps" @check="handleTreeCheck">
            <template #default="{ data }"><span class="tree-node"><span>{{ data.label }}</span><strong>{{ formatNumber(data.count) }}</strong></span></template>
          </el-tree>
          <div class="tree-footer"><span>已选 {{ treeCheckedPaths.length }} 个路径</span><el-button text :disabled="!treeCheckedPaths.length" @click="clearTreeSelection">清空选择</el-button></div>
        </aside>

        <section class="profile-list">
          <div class="explorer-heading"><div><h3>命中标的</h3><p>{{ selectedFilterChips.length ? '按所选条件交叉筛选' : '选择左侧原因查看受影响标的' }}</p></div><strong>{{ formatNumber(profileTotal) }} 只</strong></div>
          <div v-if="selectedFilterChips.length" class="selected-chips explorer-chips" aria-label="已选筛选条件"><el-tag v-for="chip in selectedFilterChips" :key="`${chip.field}:${chip.value}`" closable effect="plain" @close="removeFilter(chip.field, chip.value)">{{ chip.label }}</el-tag></div>
          <el-table :data="profileRows" height="472" highlight-current-row empty-text="当前筛选没有命中标的" @row-click="selectProfile">
            <el-table-column prop="symbol" label="代码" width="110" /><el-table-column prop="name" label="名称" min-width="105" show-overflow-tooltip /><el-table-column label="市场" width="72"><template #default="{ row }">{{ marketLabel(row.market) }}</template></el-table-column><el-table-column label="日线" width="92"><template #default="{ row }"><el-tag :type="row.latest_daily_valid ? 'success' : 'danger'" effect="plain">{{ row.latest_daily_valid ? '有效' : '缺失' }}</el-tag></template></el-table-column><el-table-column prop="recent_20d_trading_days" label="近20日成交" width="104" align="right" /><el-table-column label="日均成交额" width="126" align="right"><template #default="{ row }">{{ formatAmount(row.recent_20d_avg_amount) }}</template></el-table-column><el-table-column label="命中原因" min-width="175" show-overflow-tooltip><template #default="{ row }">{{ row.exclusion_reasons.map(exclusionLabel).join('、') || '最终可用' }}</template></el-table-column>
          </el-table>
          <div class="profile-pagination"><span>第 {{ profilePage }} / {{ profilePageCount }} 页</span><el-pagination v-model:current-page="profilePage" v-model:page-size="profilePageSize" :total="profileTotal" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @current-change="loadProfiles" @size-change="changePageSize" /></div>
        </section>

        <aside class="profile-detail">
          <div class="explorer-heading"><h3>标的说明</h3></div>
          <template v-if="selectedProfile"><h4>{{ selectedProfile.symbol }} {{ selectedProfile.name }}</h4><div class="detail-tags"><el-tag effect="plain">{{ marketLabel(selectedProfile.market) }}</el-tag><el-tag :type="selectedProfile.latest_daily_valid ? 'success' : 'danger'" effect="plain">{{ selectedProfile.latest_daily_valid ? '日线有效' : '日线缺失' }}</el-tag><el-tag effect="plain">{{ selectedProfile.is_st ? 'ST' : '非 ST' }}</el-tag></div><dl><div><dt>近20日成交天数</dt><dd>{{ selectedProfile.recent_20d_trading_days }} 日</dd></div><div><dt>日均成交额</dt><dd>{{ formatAmount(selectedProfile.recent_20d_avg_amount) }}</dd></div><div><dt>流动性等级</dt><dd>{{ liquidityLabel(selectedProfile.liquidity_level) }}</dd></div><div><dt>标签基准日</dt><dd>{{ selectedProfile.as_of_date ?? '-' }}</dd></div></dl><h5>命中原因</h5><div class="reason-tags"><el-tag v-for="reason in selectedProfile.exclusion_reasons" :key="reason" type="warning" effect="plain">{{ exclusionLabel(reason) }}</el-tag><span v-if="!selectedProfile.exclusion_reasons.length">已纳入默认股票池</span></div></template>
          <p v-else class="empty-detail">从中部列表选择一只股票，查看其标签和排除原因。</p>
        </aside>
      </section>
    </section>

    <section class="panel change-workspace">
      <div class="section-header"><div><h2>目录变更</h2><p>按发现日期定位目录快照差异；日期和类型选择会联动下方明细。</p></div></div>
      <div class="change-layout">
        <aside class="change-date-list"><div class="change-list-heading"><span>发现日期</span><span>变更数</span></div><button v-for="row in snapshot?.daily_changes ?? []" :key="row.date" type="button" :class="['change-date-row', { active: selectedChangeDate === row.date }]" @click="selectChangeDate(row.date)"><span>{{ row.date }}</span><strong>{{ formatNumber(changeTotal(row)) }}</strong><small>新增 {{ formatNumber(row.added) }} · 移除 {{ formatNumber(row.removed) }} · 名称 {{ formatNumber(row.name_changed) }}</small></button><p v-if="!(snapshot?.daily_changes ?? []).length" class="empty-detail">尚无目录变更事件。</p></aside>
        <section class="change-details"><div class="change-detail-header"><div><h3>{{ selectedChangeDate ? `${selectedChangeDate} 发现的变更` : '全部发现日期的变更' }}</h3><p>点击行查看变更前后的事实记录。</p></div><el-button text :disabled="!selectedChangeDate" @click="selectChangeDate(null)">查看全部日期</el-button></div><div class="change-type-filters"><el-button v-for="item in changeTypeOptions" :key="item.key" :type="selectedChangeType === item.key ? 'primary' : 'default'" plain size="small" @click="selectChangeType(item.key)">{{ item.label }} {{ formatNumber(changeTypeCount(item.key)) }}</el-button></div><el-table v-loading="changeEventsLoading" :data="changeEvents" height="410" empty-text="当前日期和类型下没有变更事件" @row-click="openEvent"><el-table-column prop="event_at" label="发现时间" min-width="170" /><el-table-column prop="symbol" label="代码" width="120" /><el-table-column label="类型" width="120"><template #default="{ row }"><el-tag effect="plain">{{ eventLabel(row.event_type) }}</el-tag></template></el-table-column><el-table-column label="变更摘要" min-width="280"><template #default="{ row }">{{ eventSummary(row) }}</template></el-table-column><el-table-column prop="run_id" label="运行 ID" min-width="210" show-overflow-tooltip /></el-table></section>
      </div>
    </section>

    <el-drawer v-model="drawer" title="目录变更详情" size="48%"><pre class="json-preview">{{ JSON.stringify(selectedEvent, null, 2) }}</pre></el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { api, type MootdxCatalogQualityResponse, type MootdxUniverseProfileFilter, type MootdxUniverseProfilesResponse } from '../api/client'

type FilterKey = 'market' | 'is_st' | 'latest_daily_valid' | 'trading_days' | 'average_amount' | 'liquidity_level' | 'exclusion_reason' | 'reason_market' | 'universe_eligible'
type Filters = Record<FilterKey, string[]>
type ReasonTreeNode = { id: string; label: string; count: number; paths: string[]; children?: ReasonTreeNode[] }

const router = useRouter()
const snapshot = ref<MootdxCatalogQualityResponse | null>(null)
const observedProfile = ref<MootdxCatalogQualityResponse['universe_profile'] | null>(null)
const ruleSummary = ref('近 20 日至少 15 个成交日，日均成交额至少 1,000 万，排除 ST 和北交所')
const loading = ref(false)
const profilesLoading = ref(false)
const drawer = ref(false)
const selectedEvent = ref<MootdxCatalogQualityResponse['events'][number] | null>(null)
const changeEvents = ref<MootdxCatalogQualityResponse['events']>([])
const changeEventsLoading = ref(false)
const selectedChangeDate = ref<string | null>(null)
const selectedChangeType = ref('all')
const profileRows = ref<MootdxUniverseProfilesResponse['items']>([])
const selectedProfile = ref<MootdxUniverseProfilesResponse['items'][number] | null>(null)
const profileTotal = ref(0)
const profilePage = ref(1)
const profilePageSize = ref(50)
const reasonTreeRef = ref<{ setCheckedKeys: (keys: string[]) => void } | null>(null)
const treeCheckedPaths = ref<string[]>([])
const selectedFilters = ref<Filters>({ market: [], is_st: [], latest_daily_valid: [], trading_days: [], average_amount: [], liquidity_level: [], exclusion_reason: [], reason_market: [], universe_eligible: [] })
let refreshTimer: number | undefined

const baseProfile = computed(() => snapshot.value?.universe_profile ?? null)
const displayProfile = computed(() => observedProfile.value ?? baseProfile.value)
const profileSummary = computed(() => (observedProfile.value ?? baseProfile.value)?.summary ?? { as_of_date: null, computed_at: null, rule_version: 0, symbols: 0, catalog_valid: 0, latest_daily_valid: 0, liquidity_qualified: 0, universe_eligible: 0 })
const funnel = computed(() => [
  { key: 'all', label: '目录总数', value: profileSummary.value.symbols },
  { key: 'catalog_valid', label: '目录有效', value: profileSummary.value.catalog_valid },
  { key: 'latest_daily_valid', label: '日线有效', value: profileSummary.value.latest_daily_valid },
  { key: 'liquidity_qualified', label: '流动性达标', value: profileSummary.value.liquidity_qualified },
  { key: 'universe_eligible', label: '最终可用', value: profileSummary.value.universe_eligible }
])
const activeFilters = computed<MootdxUniverseProfileFilter[]>(() => Object.entries(selectedFilters.value).filter(([, values]) => values.length).map(([field, values]) => ({ field, values })))
const selectedFilterChips = computed(() => activeFilters.value.flatMap(({ field, values }) => values.map(value => ({ field: field as FilterKey, value: String(value), label: filterLabel(field as FilterKey, String(value)) }))))
const changeTypeOptions = [{ key: 'all', label: '全部' }, { key: 'added', label: '新增' }, { key: 'removed', label: '移除' }, { key: 'name_changed', label: '名称变更' }, { key: 'st_changed', label: 'ST 变更' }, { key: 'market_changed', label: '市场变更' }]
const profilePageCount = computed(() => Math.max(1, Math.ceil(profileTotal.value / profilePageSize.value)))
const treeProps = { label: 'label', children: 'children' }
const reasonTree = computed<ReasonTreeNode[]>(() => {
  const counts = new Map((baseProfile.value?.distributions.exclusion_reasons ?? []).map(item => [item.key, item.count]))
  const markets = new Map<string, Array<{ market: string; count: number }>>()
  for (const item of baseProfile.value?.distributions.exclusion_reason_markets ?? []) markets.set(item.reason, [...(markets.get(item.reason) ?? []), { market: item.market, count: item.count }])
  return [...counts.entries()].map(([reason, count]) => {
    const children = (markets.get(reason) ?? []).map(item => ({ id: `${reason}::${item.market}`, label: marketLabel(item.market), count: item.count, paths: [`${reason}::${item.market}`] }))
    return { id: reason, label: exclusionLabel(reason), count, paths: children.flatMap(item => item.paths), children }
  })
})
const defaultExpandedReasons = computed(() => reasonTree.value.slice(0, 1).map(item => item.id))

function formatNumber(value?: number) { return new Intl.NumberFormat('zh-CN').format(value ?? 0) }
function formatAmount(value?: number) { return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format((value ?? 0) / 10_000)} 万` }
function funnelSummary(key: string) { const summary = profileSummary.value; if (key === 'all') return '目录快照总量'; if (key === 'catalog_valid') return `排除 ${formatNumber(summary.symbols - summary.catalog_valid)} 只目录不合格标的`; if (key === 'latest_daily_valid') return `较目录有效缺少 ${formatNumber(summary.catalog_valid - summary.latest_daily_valid)} 只`; if (key === 'liquidity_qualified') return '满足成交规则，不以最新日线为前提'; return '同时满足目录、日线与流动性规则' }
function eventLabel(type: string) { return ({ added: '新增', removed: '移除', name_changed: '名称变更', st_changed: 'ST 变更', market_changed: '市场变更' } as Record<string, string>)[type] ?? type }
function eventSummary(event: MootdxCatalogQualityResponse['events'][number]) { const before = event.previous.name ?? '-'; const after = event.current.name ?? '-'; return event.event_type === 'added' ? `纳入目录：${after}` : event.event_type === 'removed' ? `移出目录：${before}` : `${before} -> ${after}` }
function marketLabel(value: string) { return ({ SZ: '深市', SH: '沪市', BJ: '北交所' } as Record<string, string>)[value] ?? value }
function liquidityLabel(value: string) { return ({ high: '高流动性', medium: '中流动性', low: '低流动性' } as Record<string, string>)[value] ?? value }
function exclusionLabel(value: string) { return ({ st: 'ST 标的', market_excluded: '市场未纳入', listing_age_below_minimum: '上市时间不足', latest_daily_missing: '最新日线缺失', insufficient_trading_days: '成交天数不足', low_average_amount: '日均成交额不足' } as Record<string, string>)[value] ?? value }
function filterLabel(field: FilterKey, value: string) { if (field === 'market') return marketLabel(value); if (field === 'liquidity_level') return liquidityLabel(value); if (field === 'exclusion_reason') return exclusionLabel(value); if (field === 'reason_market') { const [reason, market] = value.split('::'); return `${exclusionLabel(reason)} / ${marketLabel(market)}` }; return ({ 'is_st:0': '非 ST', 'is_st:1': 'ST', 'latest_daily_valid:1': '最新日线有效', 'latest_daily_valid:0': '最新日线缺失', 'trading_days:lt_15': '近20日少于15日成交', 'trading_days:gte_15': '近20日15日及以上成交', 'average_amount:lt_10m': '日均低于1,000万', 'average_amount:10_50m': '日均1,000万至5,000万', 'average_amount:gte_50m': '日均5,000万以上', 'universe_eligible:1': '最终可用' } as Record<string, string>)[`${field}:${value}`] ?? value }
function openEvent(row: MootdxCatalogQualityResponse['events'][number]) { selectedEvent.value = row; drawer.value = true }
function changeTotal(row: MootdxCatalogQualityResponse['daily_changes'][number]) { return Number(row.added ?? 0) + Number(row.removed ?? 0) + Number(row.name_changed ?? 0) + Number(row.st_changed ?? 0) + Number(row.market_changed ?? 0) }
function changeTypeCount(type: string) { const row = (snapshot.value?.daily_changes ?? []).find(item => item.date === selectedChangeDate.value); if (type === 'all') return row ? changeTotal(row) : changeEvents.value.length; const field = type as keyof MootdxCatalogQualityResponse['daily_changes'][number]; return Number(row?.[field] ?? 0) }
async function loadChangeEvents() { changeEventsLoading.value = true; try { const response = await api.getMootdxCatalogChangeEvents(selectedChangeDate.value ?? undefined, selectedChangeType.value === 'all' ? undefined : selectedChangeType.value); changeEvents.value = response.items } catch (error) { ElMessage.error(error instanceof Error ? error.message : '加载目录变更明细失败') } finally { changeEventsLoading.value = false } }
function selectChangeDate(value: string | null) { selectedChangeDate.value = value; selectedChangeType.value = 'all'; void loadChangeEvents() }
function selectChangeType(value: string) { selectedChangeType.value = value; void loadChangeEvents() }
function clearFilters() { Object.keys(selectedFilters.value).forEach(key => { selectedFilters.value[key as FilterKey] = [] }); clearTreeSelection() }
function removeFilter(field: FilterKey, value: string) { selectedFilters.value[field] = selectedFilters.value[field].filter(item => item !== value) }
function setFilter(field: FilterKey, value: string) { selectedFilters.value[field] = [value] }
function handleTreeCheck(_node: ReasonTreeNode, detail: { checkedKeys: string[] }) { const selected = new Set(detail.checkedKeys); const paths = reasonTree.value.flatMap(node => selected.has(node.id) ? node.paths : (node.children ?? []).filter(child => selected.has(child.id)).flatMap(child => child.paths)); treeCheckedPaths.value = [...new Set(paths)]; selectedFilters.value.reason_market = treeCheckedPaths.value }
function clearTreeSelection() { treeCheckedPaths.value = []; selectedFilters.value.reason_market = []; reasonTreeRef.value?.setCheckedKeys([]) }
function selectProfile(row: MootdxUniverseProfilesResponse['items'][number]) { selectedProfile.value = row }
function applyFunnelFilter(key: string) { clearFilters(); if (key === 'latest_daily_valid') selectedFilters.value.latest_daily_valid = ['1']; if (key === 'liquidity_qualified') selectedFilters.value.liquidity_level = ['high', 'medium']; if (key === 'universe_eligible') selectedFilters.value.universe_eligible = ['1'] as string[] }
function updateRuleSummary(config?: Record<string, unknown>) { if (!config) return; const lookback = Number(config.lookback_days ?? 20); const days = Number(config.min_trading_days ?? 15); const amount = Number(config.min_average_amount ?? 10_000_000); const market = config.include_beijing ? '包含北交所' : '排除北交所'; ruleSummary.value = `近 ${lookback} 日至少 ${days} 个成交日，日均成交额至少 ${formatAmount(amount)}，排除 ST，${market}` }
async function loadProfiles(page?: number) { if (page) profilePage.value = page; profilesLoading.value = true; try { const response = await api.getMootdxUniverseProfiles(activeFilters.value, profilePageSize.value, (profilePage.value - 1) * profilePageSize.value); observedProfile.value = response.profile; profileRows.value = response.items; profileTotal.value = response.total; selectedProfile.value = response.items.find(item => item.symbol === selectedProfile.value?.symbol) ?? response.items[0] ?? null } catch (error) { ElMessage.error(error instanceof Error ? error.message : '加载股票池标签失败') } finally { profilesLoading.value = false } }
function changePageSize() { profilePage.value = 1; void loadProfiles(1) }
async function load() {
  loading.value = true
  try {
    const [qualityResult, tasksResult] = await Promise.allSettled([api.getMootdxCatalogQuality(), api.getDataOpsTasks()])
    if (qualityResult.status !== 'fulfilled') throw qualityResult.reason
    snapshot.value = qualityResult.value
    observedProfile.value = null
    selectedChangeDate.value = qualityResult.value.daily_changes[0]?.date ?? null
    if (tasksResult.status === 'fulfilled') {
      const profileTask = tasksResult.value.items.find(item => item.task_key === 'stock_universe_profile_refresh')
      updateRuleSummary(profileTask?.schedule_config)
    }
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '加载目录质量失败') }
  finally { loading.value = false }
  await loadProfiles(1)
  await loadChangeEvents()
}

watch(activeFilters, () => { profilePage.value = 1; window.clearTimeout(refreshTimer); refreshTimer = window.setTimeout(() => { void loadProfiles(1) }, 220) }, { deep: true })
onBeforeUnmount(() => window.clearTimeout(refreshTimer))
onMounted(load)
</script>

<style scoped>
.page-header, .toolbar, .section-header, .snapshot-actions, .filter-bar, .filter-result, .explorer-heading, .profile-pagination, .tree-footer { display: flex; align-items: center; gap: 12px; }
.page-header, .section-header { justify-content: space-between; align-items: flex-start; }
.page-header { margin-bottom: 18px; }
.toolbar, .snapshot-actions { flex-wrap: wrap; justify-content: flex-end; }
.page-title, .section-header h2, .explorer-heading h3, .profile-detail h4, .profile-detail h5 { margin: 0; }
.page-title { font-size: 22px; }
.page-subtitle, .section-header p, .rule-summary, .explorer-heading p, .empty-detail { margin: 6px 0 0; color: #667085; font-size: 13px; line-height: 1.5; }
.panel { border: 1px solid #d9dee7; background: #fff; padding: 16px; }
.panel + .panel { margin-top: 18px; }
.universe-panel { border-top: 3px solid #2f7af8; }
.rule-summary { padding: 10px 12px; margin-top: 12px; background: #f5f8ff; color: #365b98; }
.funnel { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin: 16px 0; }
.funnel-step { min-height: 92px; padding: 12px; text-align: left; background: #fff; border: 1px solid #d9dee7; cursor: pointer; }
.funnel-step:hover { border-color: #2f7af8; background: #f7faff; }
.funnel-step span, .funnel-step small { display: block; color: #667085; font-size: 12px; }
.funnel-step strong { display: block; margin: 7px 0 5px; font-size: 23px; color: #1d2939; }
.filter-bar { justify-content: space-between; padding: 14px 0; border-top: 1px solid #e4e7ed; border-bottom: 1px solid #e4e7ed; }
.filter-controls { display: grid; flex: 1; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 8px; }
.filter-result { white-space: nowrap; color: #667085; font-size: 13px; }
.filter-result strong { color: #1d2939; font-size: 24px; }
.selected-chips { display: flex; flex-wrap: wrap; gap: 7px; padding-top: 12px; }
.pool-explorer { display: grid; grid-template-columns: minmax(210px, .85fr) minmax(500px, 2.6fr) minmax(220px, .95fr); margin-top: 18px; border: 1px solid #d9dee7; min-height: 610px; }
.reason-tree, .profile-list, .profile-detail { min-width: 0; padding: 14px; }
.reason-tree, .profile-list { border-right: 1px solid #e4e7ed; }
.explorer-heading { justify-content: space-between; min-height: 28px; }
.explorer-heading h3 { font-size: 15px; }
.explorer-heading > span, .explorer-heading > strong { color: #365b98; font-size: 13px; }
.tree-node { display: flex; justify-content: space-between; width: 100%; gap: 8px; color: #475467; }
.tree-node strong { color: #344054; font-size: 13px; }
.reason-tree :deep(.el-tree) { margin-top: 10px; background: transparent; }
.reason-tree :deep(.el-tree-node__content) { height: 30px; }
.tree-footer { justify-content: space-between; padding-top: 12px; margin-top: 12px; border-top: 1px solid #e4e7ed; color: #667085; font-size: 12px; }
.profile-list { display: flex; flex-direction: column; }
.explorer-chips { padding: 8px 0; }
.profile-pagination { justify-content: space-between; margin-top: 12px; color: #667085; font-size: 12px; }
.profile-detail h4 { margin-top: 12px; font-size: 17px; color: #1d2939; }
.detail-tags, .reason-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.profile-detail dl { margin: 16px 0; border-top: 1px solid #e4e7ed; }
.profile-detail dl div { display: flex; justify-content: space-between; gap: 8px; padding: 9px 0; border-bottom: 1px solid #e4e7ed; }
.profile-detail dt { color: #667085; font-size: 12px; }
.profile-detail dd { margin: 0; color: #344054; font-size: 12px; text-align: right; }
.profile-detail h5 { font-size: 13px; color: #344054; }
.reason-tags > span { color: #667085; font-size: 13px; }
.empty-detail { margin-top: 16px; }
.change-workspace { margin-top: 18px; }
.change-layout { display: grid; grid-template-columns: minmax(265px, .72fr) minmax(0, 2.5fr); margin-top: 16px; border-top: 1px solid #e4e7ed; }
.change-date-list { padding: 12px 14px 12px 0; border-right: 1px solid #e4e7ed; }
.change-list-heading { display: flex; justify-content: space-between; padding: 0 10px 8px; color: #667085; font-size: 12px; }
.change-date-row { display: grid; grid-template-columns: 1fr auto; width: 100%; gap: 4px 12px; padding: 10px; border: 1px solid transparent; border-left: 3px solid transparent; background: transparent; color: #344054; text-align: left; cursor: pointer; }
.change-date-row:hover { background: #f7faff; }
.change-date-row.active { border-color: #d7e5ff; border-left-color: #2f7af8; background: #f2f7ff; }
.change-date-row strong { color: #1d2939; font-size: 16px; }
.change-date-row small { grid-column: 1 / -1; color: #667085; font-size: 12px; }
.change-details { min-width: 0; padding: 12px 0 0 16px; }
.change-detail-header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.change-detail-header h3 { margin: 0; font-size: 16px; }
.change-detail-header p { margin: 5px 0 0; color: #667085; font-size: 13px; }
.change-type-filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 0; }
.json-preview { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; }
@media (max-width: 1180px) { .pool-explorer { grid-template-columns: minmax(190px, .8fr) minmax(460px, 2fr); }.profile-detail { grid-column: 1 / -1; border-top: 1px solid #e4e7ed; }.reason-tree { border-right: 1px solid #e4e7ed; } }
@media (max-width: 980px) { .funnel { grid-template-columns: repeat(3, minmax(0, 1fr)); }.filter-bar { align-items: stretch; flex-direction: column; }.filter-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }.pool-explorer, .change-layout { grid-template-columns: 1fr; }.reason-tree, .profile-list { border-right: 0; border-bottom: 1px solid #e4e7ed; }.profile-detail { grid-column: auto; }.change-date-list { padding-right: 0; border-right: 0; border-bottom: 1px solid #e4e7ed; }.change-details { padding-left: 0; } }
@media (max-width: 620px) { .page-header { flex-direction: column; }.funnel, .filter-controls { grid-template-columns: 1fr; }.filter-result { justify-content: space-between; }.snapshot-actions { justify-content: flex-start; }.profile-pagination { align-items: flex-start; flex-direction: column; } }
</style>
