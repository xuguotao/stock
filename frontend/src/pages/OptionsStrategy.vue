<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">期权策略</h1>
      <div class="toolbar">
        <el-button type="primary">记录计划</el-button>
        <el-button>复核权限</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">允许策略</div>
        <div class="metric-value compact-value">Put / Call</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">起步额度</div>
        <div class="metric-value">5%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">义务仓上限</div>
        <div class="metric-value">20%-30%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">禁用策略</div>
        <div class="metric-value compact-value">naked call</div>
      </div>
    </div>

    <div class="investment-channel-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">准入检查</h2>
          <el-tag type="warning" effect="plain">先模拟后实盘</el-tag>
        </div>
        <el-check-tag
          v-for="item in eligibilityItems"
          :key="item"
          class="strategy-check-tag"
          checked
        >
          {{ item }}
        </el-check-tag>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">执行清单</h2>
          <el-tag effect="plain">现金预留</el-tag>
        </div>
        <el-table :data="executionRows" height="300">
          <el-table-column prop="step" label="步骤" width="110" />
          <el-table-column prop="check" label="检查项" min-width="190" />
          <el-table-column prop="limit" label="约束" min-width="160" />
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">策略边界</h2>
        <el-tag type="danger" effect="plain">风险优先</el-tag>
      </div>
      <el-table :data="strategyRows" height="320">
        <el-table-column prop="name" label="策略" width="180" />
        <el-table-column prop="useCase" label="适用场景" min-width="220" />
        <el-table-column prop="maxProfit" label="最大收益" width="120" />
        <el-table-column prop="risk" label="主要风险" min-width="220" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === '禁用' ? 'danger' : 'success'" effect="plain">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
const eligibilityItems = [
  '期权权限已开通',
  '知识测试通过',
  '模拟交易完成',
  '现金预留覆盖 sell put',
  '持仓覆盖 covered call',
]

const executionRows = [
  { step: '标的', check: '只选愿意长期持有或已经持有的 ETF/股票', limit: '不因权利金临时追标的' },
  { step: '行权价', check: 'sell put 选择愿意买入的价格，covered call 选择愿意卖出的价格', limit: '先看最大义务再看收益率' },
  { step: '到期日', check: '起步优先 1-2 个月合约', limit: '避开不理解的临近到期尾部风险' },
  { step: '仓位', check: '单笔潜在接盘金额控制在总资产 5%-10%', limit: '义务仓合计不超过 20%-30%' },
  { step: '退出条件', check: '提前写清回补、移仓、接盘或被行权后的动作', limit: '不临场加倍摊平' },
]

const strategyRows = [
  {
    name: 'cash-secured put',
    useCase: '本来愿意低价买入标的，账户现金足以覆盖潜在接盘金额',
    maxProfit: '权利金',
    risk: '标的大跌时仍可能按行权价买入，亏损可远超权利金',
    status: '允许',
  },
  {
    name: 'covered call',
    useCase: '已经持有标的，愿意在目标价卖出，换取权利金收入',
    maxProfit: '权利金+价差',
    risk: '标的大涨时收益被行权价封顶',
    status: '允许',
  },
  {
    name: 'naked call',
    useCase: '无现货覆盖却卖出看涨期权',
    maxProfit: '权利金',
    risk: '理论亏损无上限，普通账户不作为投资渠道启用',
    status: '禁用',
  },
]
</script>
