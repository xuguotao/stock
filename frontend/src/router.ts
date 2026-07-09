import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import DataCenter from './pages/DataCenter.vue'
import Dashboard from './pages/Dashboard.vue'
import FundTail from './pages/FundTail.vue'
import Jobs from './pages/Jobs.vue'
import Minute5Quality from './pages/Minute5Quality.vue'
import OptionsStrategy from './pages/OptionsStrategy.vue'
import ReitsChannel from './pages/ReitsChannel.vue'
import SignalReview from './pages/SignalReview.vue'
import StockList from './pages/StockList.vue'
import StockReadiness from './pages/StockReadiness.vue'
import StockTrend from './pages/StockTrend.vue'
import TailBacktest from './pages/TailBacktest.vue'
import TailLiveSelection from './pages/TailLiveSelection.vue'
import TailModelLab from './pages/TailModelLab.vue'
import TailReplayBacktest from './pages/TailReplayBacktest.vue'
import WatchlistMonitor from './pages/WatchlistMonitor.vue'

export const navigationRoutes = [
  { name: 'dashboard', label: '总览' },
  { name: 'data', label: '数据中心' },
  { name: 'minute5-quality', label: '5m质量巡检' },
  { name: 'stock-list', label: '股票列表' },
  { name: 'stock-readiness', label: '策略数据就绪度' },
  { name: 'tail-live', label: '今日尾盘选股' },
  { name: 'watchlist-monitor', label: '观察池监控' },
  { name: 'stock-trend', label: '个股趋势' },
  { name: 'reits-channel', label: 'REITs 配置' },
  { name: 'options-strategy', label: '期权策略' },
  { name: 'signal-review', label: '策略复盘' },
  { name: 'tail-replay', label: '尾盘时段回测' },
  { name: 'tail-model-lab', label: '尾盘模型实验' },
  { name: 'backtest', label: '尾盘回测' },
  { name: 'fund-tail', label: '基金尾盘' },
  { name: 'jobs', label: '任务中心' }
] as const

const legacyPageNames = new Set(navigationRoutes.map((route) => route.name))

function firstQueryValue(value: unknown): string {
  if (Array.isArray(value)) return typeof value[0] === 'string' ? value[0] : ''
  return typeof value === 'string' ? value : ''
}

function legacyPageRedirect(query: RouteLocationNormalized['query']) {
  const page = firstQueryValue(query.page)
  if (!legacyPageNames.has(page as (typeof navigationRoutes)[number]['name'])) return null

  const nextQuery = { ...query }
  delete nextQuery.page

  if (page === 'stock-trend') {
    const symbol = firstQueryValue(nextQuery.symbol)
    delete nextQuery.symbol
    return {
      name: page,
      params: symbol ? { symbol } : {},
      query: nextQuery,
      replace: true
    }
  }

  return {
    name: page,
    query: nextQuery,
    replace: true
  }
}

export function normalizeLegacyPageQuery(to: RouteLocationNormalized) {
  return legacyPageRedirect(to.query)
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: (to) => legacyPageRedirect(to.query) ?? { name: 'dashboard' } },
    { path: '/dashboard', name: 'dashboard', component: Dashboard },
    { path: '/data', name: 'data', component: DataCenter },
    { path: '/minute5-quality', name: 'minute5-quality', component: Minute5Quality },
    { path: '/stocks', name: 'stock-list', component: StockList },
    { path: '/stock-readiness', name: 'stock-readiness', component: StockReadiness },
    {
      path: '/stock-trend/:symbol?',
      name: 'stock-trend',
      component: StockTrend,
      props: (route) => ({
        symbol: firstQueryValue(route.params.symbol) || firstQueryValue(route.query.symbol)
      })
    },
    {
      path: '/tail-live',
      name: 'tail-live',
      component: TailLiveSelection,
      props: (route) => ({
        jobId: firstQueryValue(route.query.job_id) || firstQueryValue(route.query.jobId)
      })
    },
    { path: '/watchlist-monitor', name: 'watchlist-monitor', component: WatchlistMonitor },
    { path: '/reits-channel', name: 'reits-channel', component: ReitsChannel },
    { path: '/options-strategy', name: 'options-strategy', component: OptionsStrategy },
    { path: '/signal-review', name: 'signal-review', component: SignalReview },
    {
      path: '/tail-replay',
      name: 'tail-replay',
      component: TailReplayBacktest,
      props: (route) => ({
        jobId: firstQueryValue(route.query.job_id) || firstQueryValue(route.query.jobId)
      })
    },
    { path: '/tail-model-lab', name: 'tail-model-lab', component: TailModelLab },
    {
      path: '/tail-backtest',
      name: 'backtest',
      component: TailBacktest,
      props: (route) => ({
        jobId: firstQueryValue(route.query.job_id) || firstQueryValue(route.query.jobId)
      })
    },
    {
      path: '/fund-tail',
      name: 'fund-tail',
      component: FundTail,
      props: (route) => ({
        jobId: firstQueryValue(route.query.job_id) || firstQueryValue(route.query.jobId)
      })
    },
    { path: '/jobs', name: 'jobs', component: Jobs },
    { path: '/:pathMatch(.*)*', redirect: { name: 'dashboard' } }
  ]
})

router.beforeEach((to) => normalizeLegacyPageQuery(to) ?? true)
