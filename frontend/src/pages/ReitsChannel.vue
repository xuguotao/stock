<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">REITs 配置</h1>
      <div class="toolbar">
        <el-button type="primary">新增候选</el-button>
        <el-button>刷新数据</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">目标仓位</div>
        <div class="metric-value">5%-10%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">候选池</div>
        <div class="metric-value">{{ candidates.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">资产类型</div>
        <div class="metric-value">分散</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">更新频率</div>
        <div class="metric-value compact-value">月度复核</div>
      </div>
    </div>

    <div class="investment-channel-grid">
      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">配置纪律</h2>
          <el-tag effect="plain">现金流资产</el-tag>
        </div>
        <el-timeline>
          <el-timeline-item
            v-for="rule in allocationRules"
            :key="rule.title"
            :timestamp="rule.title"
          >
            {{ rule.description }}
          </el-timeline-item>
        </el-timeline>
      </div>

      <div class="panel">
        <div class="page-header panel-title-row">
          <h2 class="page-title">筛选维度</h2>
          <el-tag type="success" effect="plain">不过度追新</el-tag>
        </div>
        <el-table :data="screeningRows" height="300">
          <el-table-column prop="dimension" label="维度" width="110" />
          <el-table-column prop="focus" label="关注点" min-width="170" />
          <el-table-column prop="risk" label="风险" min-width="170" />
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="page-header panel-title-row">
        <h2 class="page-title">候选池</h2>
        <el-tag effect="plain">待接入行情与分红数据</el-tag>
      </div>
      <el-table :data="candidates" height="320" empty-text="暂无候选 REITs">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="assetType" label="资产类型" width="130" />
        <el-table-column prop="cashFlow" label="现金流观察" min-width="180" />
        <el-table-column prop="valuation" label="估值/分红率" min-width="160" />
        <el-table-column prop="action" label="动作" width="120">
          <template #default="{ row }">
            <el-tag :type="row.action === '观察' ? 'info' : 'warning'" effect="plain">
              {{ row.action }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
const allocationRules = [
  { title: '仓位上限', description: 'REITs 先按总资产 5%-10% 试运行，避免把现金流资产当成股票替代品。' },
  { title: '分批买入', description: '优先二级市场分批配置，不追上市首日或短期溢价过高的品种。' },
  { title: '分散约束', description: '在消费基础设施、产业园、仓储物流、能源、公路等资产类型之间分散。' },
  { title: '收益校验', description: '不只看分红率，同时看底层资产质量、估值溢价、流动性和管理人。' },
]

const screeningRows = [
  { dimension: '资产类型', focus: '底层项目所处行业、经营期限、收入来源', risk: '单一行业周期或政策变化导致现金流波动' },
  { dimension: '现金流', focus: '出租率、收费量、电价、租约期限和分派稳定性', risk: '短期高分派可能不可持续' },
  { dimension: '估值', focus: '价格相对净资产、历史分红率和同类资产比较', risk: '高溢价买入会压低未来收益' },
  { dimension: '流动性', focus: '日均成交额、买卖价差、机构持有人结构', risk: '成交稀疏时调仓成本上升' },
  { dimension: '管理人', focus: '运营能力、信息披露质量和扩募能力', risk: '治理或运营弱会侵蚀长期回报' },
]

const candidates = [
  { name: '消费基础设施 REITs', assetType: '消费', cashFlow: '租金和客流恢复情况', valuation: '分红率与溢价率', action: '观察' },
  { name: '仓储物流 REITs', assetType: '物流', cashFlow: '出租率和续租价格', valuation: '同类资产对比', action: '观察' },
  { name: '能源基础设施 REITs', assetType: '能源', cashFlow: '电价、利用小时和补贴回款', valuation: '现金分派覆盖', action: '复核' },
]
</script>
