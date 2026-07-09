<template>
  <el-container class="shell">
    <el-aside width="228px" class="sidebar">
      <div class="brand">A 股量化后台</div>
      <el-menu :default-active="activeRouteName" @select="openPage">
        <el-menu-item
          v-for="item in navigationRoutes"
          :key="item.name"
          :index="item.name"
        >
          {{ item.label }}
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <span>本地研究与模拟交易控制台</span>
        <el-tag type="success" effect="plain">FastAPI</el-tag>
      </el-header>
      <el-main class="content">
        <RouterView v-slot="{ Component }">
          <component
            :is="Component"
            @open-backtest="openPage('backtest')"
            @open-trend="openTrend"
            @open-result="openResult"
          />
        </RouterView>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { navigationRoutes } from './router'

const route = useRoute()
const router = useRouter()
const routeNames = new Set(navigationRoutes.map((item) => item.name))

const activeRouteName = computed(() => {
  const name = typeof route.name === 'string' ? route.name : 'dashboard'
  return routeNames.has(name as (typeof navigationRoutes)[number]['name']) ? name : 'dashboard'
})

function openPage(page: string) {
  if (!routeNames.has(page as (typeof navigationRoutes)[number]['name'])) return
  void router.push({ name: page })
}

function openTrend(symbol: string) {
  void router.push({ name: 'stock-trend', params: { symbol } })
}

function openResult(payload: { page: string; jobId: string }) {
  if (!routeNames.has(payload.page as (typeof navigationRoutes)[number]['name'])) return
  void router.push({ name: payload.page, query: { job_id: payload.jobId } })
}
</script>

<style scoped>
.shell {
  min-height: 100vh;
}

.sidebar {
  border-right: 1px solid #d9dee7;
  background: #ffffff;
}

.brand {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  font-weight: 700;
  border-bottom: 1px solid #edf0f4;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #d9dee7;
  background: #ffffff;
  height: 56px;
}

.content {
  padding: 18px;
  background: #f4f6f8;
}
</style>
