<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Mootdx XDXR 质量</h1>
        <p class="page-subtitle">除权除息同步运行健康、单标的审计和事实表覆盖情况。</p>
      </div>
      <div class="toolbar">
        <el-button @click="router.push({ name: 'mootdx-monitor' })">返回数据源</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-select v-model="statusFilter" clearable placeholder="运行状态" style="width: 140px"><el-option label="成功" value="success" /><el-option label="失败" value="failed" /></el-select>
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      <el-button :disabled="!dateRange && !statusFilter" @click="clearFilters">清空</el-button>
      <span class="filter-hint">默认展示最近 30 次运行</span>
    </div>

    <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false" class="load-error"><template #default><el-button text type="primary" @click="load">重试</el-button></template></el-alert>

    <template v-if="snapshot?.latest_run">
      <section class="summary-grid">
        <article class="metric-card primary"><span>最新运行</span><strong>{{ statusLabel(snapshot.latest_run.status) }}</strong><small>{{ formatTime(snapshot.latest_run.finished_at ?? snapshot.latest_run.started_at) }}</small></article>
        <article class="metric-card"><span>标的处理</span><strong>{{ formatNumber(snapshot.latest_run.success_symbols) }} 成功</strong><small>请求 {{ formatNumber(snapshot.latest_run.requested_symbols) }} / 目标 {{ formatNumber(snapshot.latest_run.target_symbols) }}</small></article>
        <article class="metric-card"><span>空结果 / 错误</span><strong>{{ formatNumber(snapshot.latest_run.empty_symbols) }} / {{ formatNumber(snapshot.latest_run.error_symbols) }}</strong><small>空结果不等于同步失败</small></article>
        <article class="metric-card"><span>事件写入</span><strong>{{ formatNumber(snapshot.latest_run.event_rows) }}</strong><small>本次解析出的除权除息记录</small></article>
        <article class="metric-card"><span>总耗时</span><strong>{{ formatDuration(snapshot.latest_run.duration_seconds) }}</strong><small>请求 {{ formatDuration(snapshot.latest_run.request_seconds) }} · 解析 {{ formatDuration(snapshot.latest_run.parse_seconds) }}</small></article>
        <article class="metric-card"><span>写入耗时</span><strong>{{ formatDuration(snapshot.latest_run.write_seconds) }}</strong><small>当前同步任务未持久化时显示 —</small></article>
      </section>

      <section class="panel health-panel">
        <div class="section-header"><div><h2>最新运行健康</h2><p>用于快速识别源端故障、熔断和异常标的。</p></div><el-tag :type="statusType(snapshot.latest_run.status)" effect="plain">{{ statusLabel(snapshot.latest_run.status) }}</el-tag></div>
        <div class="health-grid">
          <div><span>熔断</span><strong :class="{ danger: snapshot.latest_run.circuit_breaker_triggered }">{{ snapshot.latest_run.circuit_breaker_triggered ? '已触发' : '未触发' }}</strong></div>
          <div><span>请求 / 解析</span><strong>{{ formatDuration(snapshot.latest_run.request_seconds) }} / {{ formatDuration(snapshot.latest_run.parse_seconds) }}</strong></div>
          <div><span>失败标的样本</span><strong class="sample">{{ snapshot.latest_run.failed_symbols_sample.join('、') || '无' }}</strong></div>
        </div>
        <p v-if="snapshot.latest_run.error" class="run-error">{{ snapshot.latest_run.error }}</p>
      </section>

      <section class="panel">
        <div class="section-header"><div><h2>事实表摘要</h2><p>仅统计 Mootdx XDXR 事实表，不读取旧数据源体系。</p></div></div>
        <div class="fact-grid"><div><span>覆盖标的</span><strong>{{ formatNumber(snapshot.data_summary.symbols) }}</strong></div><div><span>事件总数</span><strong>{{ formatNumber(snapshot.data_summary.events) }}</strong></div><div><span>最新入库</span><strong>{{ formatTime(snapshot.data_summary.latest_ingested_at) }}</strong></div><div><span>送股字段为空</span><strong>{{ formatNumber(snapshot.data_summary.null_suogu) }}</strong></div></div>
      </section>

      <section class="history-layout">
        <section class="panel trend-panel">
          <div class="section-header"><div><h2>最近运行趋势</h2><p>柱高表示总耗时；颜色表示运行结果。</p></div></div>
          <div class="trend" aria-label="最近运行耗时趋势"><button v-for="run in reversedRuns" :key="run.run_id" class="trend-item" type="button" :title="`${formatTime(run.started_at)} ${formatDuration(run.duration_seconds)}`" @click="openRun(run)"><span class="bar-wrap"><i :class="['bar', run.status]" :style="{ height: barHeight(run.duration_seconds) }"></i></span><small>{{ shortDate(run.started_at) }}</small></button></div>
        </section>
        <section class="panel run-summary"><h2>运行结果分布</h2><div class="status-counts"><div><span>成功</span><strong>{{ successfulRuns }}</strong></div><div><span>失败</span><strong class="danger">{{ failedRuns }}</strong></div><div><span>合计</span><strong>{{ snapshot.runs.length }}</strong></div></div></section>
      </section>

      <section class="panel">
        <div class="section-header"><div><h2>运行历史</h2><p>点击一行查看该次运行的每标的审计记录。</p></div><span class="muted">{{ snapshot.runs.length }} 次</span></div>
        <el-table :data="snapshot.runs" v-loading="loading" height="420" empty-text="尚无 XDXR 运行记录" @row-click="openRun">
          <el-table-column label="开始时间" min-width="165"><template #default="{ row }">{{ formatTime(row.started_at) }}</template></el-table-column>
          <el-table-column label="状态" width="95"><template #default="{ row }"><el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="耗时" width="100" align="right"><template #default="{ row }">{{ formatDuration(row.duration_seconds) }}</template></el-table-column>
          <el-table-column label="请求/成功/空/错" min-width="175" align="right"><template #default="{ row }">{{ formatNumber(row.requested_symbols) }} / {{ formatNumber(row.success_symbols) }} / {{ formatNumber(row.empty_symbols) }} / {{ formatNumber(row.error_symbols) }}</template></el-table-column>
          <el-table-column label="事件" width="100" align="right"><template #default="{ row }">{{ formatNumber(row.event_rows) }}</template></el-table-column>
          <el-table-column label="熔断" width="92"><template #default="{ row }"><el-tag :type="row.circuit_breaker_triggered ? 'danger' : 'info'" effect="plain">{{ row.circuit_breaker_triggered ? '已触发' : '未触发' }}</el-tag></template></el-table-column>
          <el-table-column label="错误" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ row.error || '—' }}</template></el-table-column>
        </el-table>
      </section>
    </template>

    <el-empty v-else-if="!loading && !loadError" description="尚无 XDXR 运行记录"><el-button type="primary" @click="load">刷新</el-button></el-empty>

    <el-drawer v-model="drawer" :title="detail ? `运行审计 · ${detail.run_id}` : '运行审计'" size="min(920px, 88%)" @closed="detail = null">
      <div v-loading="detailLoading" class="drawer-content">
        <template v-if="detail">
          <div class="detail-summary"><el-tag :type="statusType(detail.status)" effect="plain">{{ statusLabel(detail.status) }}</el-tag><span>总耗时 {{ formatDuration(detail.duration_seconds) }}</span><span>请求 {{ formatDuration(detail.request_seconds) }}</span><span>解析 {{ formatDuration(detail.parse_seconds) }}</span><span>写入 {{ formatDuration(detail.write_seconds) }}</span></div>
          <p v-if="detail.error" class="run-error">{{ detail.error }}</p>
          <div class="detail-filters"><el-button v-for="option in detailStatusOptions" :key="option.value" size="small" :type="detailStatus === option.value ? 'primary' : 'default'" plain @click="selectDetailStatus(option.value)">{{ option.label }}</el-button></div>
          <el-table :data="detail.items" height="calc(100vh - 250px)" empty-text="该筛选下没有审计记录">
            <el-table-column prop="symbol" label="代码" width="110" /><el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="itemStatusType(row.status)" effect="plain">{{ itemStatusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column prop="event_rows" label="事件" width="75" align="right" /><el-table-column label="请求" width="90" align="right"><template #default="{ row }">{{ formatMilliseconds(row.request_ms) }}</template></el-table-column><el-table-column label="解析" width="90" align="right"><template #default="{ row }">{{ formatMilliseconds(row.parse_ms) }}</template></el-table-column><el-table-column label="错误" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.error || '—' }}</template></el-table-column><el-table-column label="原始列" min-width="185" show-overflow-tooltip><template #default="{ row }">{{ row.raw_columns.join(', ') || '—' }}</template></el-table-column>
          </el-table>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { api, type MootdxXdxrQualityResponse, type MootdxXdxrRun, type MootdxXdxrRunDetail } from '../api/client'

const router = useRouter()
const snapshot = ref<MootdxXdxrQualityResponse | null>(null)
const loading = ref(false)
const loadError = ref('')
const dateRange = ref<[string, string] | null>(null)
const statusFilter = ref('')
const drawer = ref(false)
const detailLoading = ref(false)
const detail = ref<MootdxXdxrRunDetail | null>(null)
const detailStatus = ref('')
const detailStatusOptions = [{ value: '', label: '全部' }, { value: 'success', label: '成功' }, { value: 'empty', label: '空结果' }, { value: 'error', label: '错误' }]

const successfulRuns = computed(() => snapshot.value?.runs.filter(item => item.status === 'success').length ?? 0)
const failedRuns = computed(() => snapshot.value?.runs.filter(item => item.status === 'failed').length ?? 0)
const reversedRuns = computed(() => [...(snapshot.value?.runs ?? [])].reverse())
const maxDuration = computed(() => Math.max(1, ...(snapshot.value?.runs.map(item => item.duration_seconds ?? 0) ?? [1])))

function formatNumber(value?: number) { return new Intl.NumberFormat('zh-CN').format(value ?? 0) }
function formatTime(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false }) }
function shortDate(value?: string | null) { if (!value) return '—'; return value.slice(5, 10) }
function formatDuration(value?: number | null) { if (value === null || value === undefined) return '—'; if (value < 1) return `${Math.round(value * 1000)} ms`; if (value < 60) return `${value.toFixed(2)} s`; return `${Math.floor(value / 60)}m ${(value % 60).toFixed(0)}s` }
function formatMilliseconds(value?: number | null) { return value === null || value === undefined ? '—' : `${Math.round(value)} ms` }
function statusLabel(value: string) { return value === 'success' ? '成功' : value === 'failed' ? '失败' : value }
function statusType(value: string) { return value === 'success' ? 'success' : value === 'failed' ? 'danger' : 'warning' }
function itemStatusLabel(value: string) { return ({ success: '成功', empty: '空结果', error: '错误' } as Record<string, string>)[value] ?? value }
function itemStatusType(value: string) { return value === 'success' ? 'success' : value === 'error' ? 'danger' : 'warning' }
function barHeight(value?: number | null) { return `${Math.max(8, Math.round(((value ?? 0) / maxDuration.value) * 118))}px` }
function clearFilters() { dateRange.value = null; statusFilter.value = ''; void load() }
async function load() { loading.value = true; loadError.value = ''; try { snapshot.value = await api.getMootdxXdxrQuality({ limit: 30, startDate: dateRange.value?.[0], endDate: dateRange.value?.[1], status: statusFilter.value || undefined }) } catch (error) { snapshot.value = null; loadError.value = error instanceof Error ? error.message : '加载 XDXR 质量失败'; ElMessage.error(loadError.value) } finally { loading.value = false } }
async function openRun(run: MootdxXdxrRun) { drawer.value = true; detailLoading.value = true; detail.value = null; detailStatus.value = ''; try { detail.value = (await api.getMootdxXdxrRunDetail(run.run_id, { limit: 500 })).item } catch (error) { const message = error instanceof Error ? error.message : '加载运行审计失败'; ElMessage.error(message); drawer.value = false } finally { detailLoading.value = false } }
async function selectDetailStatus(status: string) { if (!detail.value) return; detailStatus.value = status; detailLoading.value = true; try { detail.value = (await api.getMootdxXdxrRunDetail(detail.value.run_id, { status: status || undefined, limit: 500 })).item } catch (error) { ElMessage.error(error instanceof Error ? error.message : '加载审计筛选失败') } finally { detailLoading.value = false } }
onMounted(load)
</script>

<style scoped>
.page-header,.toolbar,.filter-bar,.section-header,.health-grid,.fact-grid,.detail-summary,.detail-filters { display:flex; align-items:center; gap:12px; }.page-header,.section-header { justify-content:space-between; align-items:flex-start; }.page-header { margin-bottom:18px; }.page-title,.section-header h2,.run-summary h2 { margin:0; }.page-title { font-size:22px; }.page-subtitle,.section-header p,.filter-hint,.muted { margin:6px 0 0; color:#667085; font-size:13px; }.toolbar,.filter-bar { flex-wrap:wrap; }.filter-bar { padding:12px; margin-bottom:16px; border:1px solid #d9dee7; background:#fff; }.filter-hint { margin:0 0 0 auto; }.load-error { margin-bottom:16px; }.summary-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin-bottom:18px; }.metric-card,.panel { border:1px solid #d9dee7; background:#fff; }.metric-card { min-height:105px; padding:14px; }.metric-card.primary { border-top:3px solid #2f7af8; }.metric-card span,.metric-card small,.health-grid span,.fact-grid span,.status-counts span { display:block; color:#667085; font-size:12px; }.metric-card strong { display:block; margin:8px 0 5px; color:#1d2939; font-size:20px; }.panel { padding:16px; }.health-panel,.trend-panel { border-top:3px solid #2f7af8; }.health-grid { display:grid; grid-template-columns:1fr 1fr 2fr; gap:16px; margin-top:16px; }.health-grid strong { display:block; margin-top:6px; color:#344054; }.sample { overflow-wrap:anywhere; }.danger { color:#d92d20 !important; }.run-error { margin:14px 0 0; padding:10px 12px; border-left:3px solid #f04438; background:#fff4f2; color:#b42318; overflow-wrap:anywhere; }.fact-grid { display:grid; grid-template-columns:repeat(4,1fr); margin-top:14px; }.fact-grid > div,.status-counts > div { padding:4px 14px; border-right:1px solid #e4e7ed; }.fact-grid > div:last-child,.status-counts > div:last-child { border:0; }.fact-grid strong,.status-counts strong { display:block; margin-top:7px; color:#1d2939; font-size:20px; }.history-layout { display:grid; grid-template-columns:minmax(0,2.4fr) minmax(220px,.8fr); gap:18px; margin:18px 0; }.trend { display:flex; align-items:end; height:165px; gap:5px; margin-top:14px; padding:10px 0 0; border-bottom:1px solid #e4e7ed; overflow-x:auto; }.trend-item { display:grid; flex:1 0 22px; height:100%; padding:0; border:0; background:transparent; cursor:pointer; }.bar-wrap { display:flex; height:130px; align-items:end; justify-content:center; }.bar { display:block; width:14px; background:#67c23a; }.bar.failed { background:#f56c6c; }.bar:not(.success):not(.failed) { background:#e6a23c; }.trend small { margin-top:5px; color:#98a2b3; font-size:10px; transform:rotate(-45deg); white-space:nowrap; }.status-counts { display:grid; gap:12px; margin-top:18px; }.drawer-content { min-height:200px; }.detail-summary { flex-wrap:wrap; margin-bottom:14px; color:#667085; font-size:13px; }.detail-filters { margin:14px 0; }.el-empty { padding:72px 0; } @media (max-width:1100px) { .summary-grid { grid-template-columns:repeat(3,1fr); }.history-layout { grid-template-columns:1fr; } } @media (max-width:700px) { .summary-grid,.fact-grid,.health-grid { grid-template-columns:1fr 1fr; }.filter-hint { width:100%; margin:0; }.fact-grid > div { border:0; border-bottom:1px solid #e4e7ed; } }
</style>
