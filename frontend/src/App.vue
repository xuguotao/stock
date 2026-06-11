<template>
  <el-container class="shell">
    <el-aside width="228px" class="sidebar">
      <div class="brand">A 股量化后台</div>
      <el-menu :default-active="activePage" @select="activePage = $event">
        <el-menu-item index="dashboard">总览</el-menu-item>
        <el-menu-item index="data">数据中心</el-menu-item>
        <el-menu-item index="backtest">尾盘回测</el-menu-item>
        <el-menu-item index="fund-tail">基金尾盘</el-menu-item>
        <el-menu-item index="jobs">任务中心</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <span>本地研究与模拟交易控制台</span>
        <el-tag type="success" effect="plain">FastAPI</el-tag>
      </el-header>
      <el-main class="content">
        <Dashboard v-if="activePage === 'dashboard'" @open-backtest="activePage = 'backtest'" />
        <DataCenter v-else-if="activePage === 'data'" />
        <TailBacktest v-else-if="activePage === 'backtest'" />
        <FundTail v-else-if="activePage === 'fund-tail'" />
        <Jobs v-else />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import DataCenter from './pages/DataCenter.vue'
import Dashboard from './pages/Dashboard.vue'
import FundTail from './pages/FundTail.vue'
import Jobs from './pages/Jobs.vue'
import TailBacktest from './pages/TailBacktest.vue'

const activePage = ref('dashboard')
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
