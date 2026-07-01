# 股票列表页统计头设计

## 背景与目标

股票列表检索页(`StockList.vue`)已上线,支持按代码/名称/行业/市场/状态检索 5207 只已入库股票,并显示每只股票的最新日线日期。`docs/superpowers/reviews/2026-07-01-stock-vs-daily-count-gap-analysis.md` 查清了 5207 vs 4960 的口径差异,并指出 245 只日线陈旧(含 229 只 ST 自 2026-06-17 起断流)。

本轮在 `StockList.vue` 头部加一个统计信息区,把"数据有没有缺口"和"库里都有什么股"一眼量化出来,呼应排查报告。

## 范围

- 在 `StockList.vue` 筛选区上方加统计头,固定展示**全库**画像与健康度。
- 纯前端实现,复用已加载的 `items`,用 `computed` 聚合,零后端改动、零额外请求。
- 不动后端、不动 `client.ts`、不动 `App.vue`。
- 不改现有"共 X 只 / 符合筛选 Y 只"汇总条(它负责筛选联动,统计头负责全库概况,职责分离)。

## 整体方案

- **位置**:`StockList.vue` 模板最顶部,在现有筛选 `el-form` 之上。结构为:统计头 → 筛选区 → 汇总条 → 表格。
- **形态**:两个区块横向排列,每区块一组扁平 stat 卡片(数字 + 标签)。
- **数据来源**:纯前端 `computed`,聚合已加载的 `items`(全量 5207 条)。
- **联动性**:统计头固定全库,不随筛选变化。

## 统计项与卡片分组

### 区块一:数据健康(突出数据缺口)

| 卡片 | 数值(示例) | 算法 |
|---|---|---|
| 股票总数 | 5207 | `items.length` |
| 最新交易日 | 2026-07-01 | `max(last_daily_date)` |
| 日线新鲜 | 4962 | `last_daily_date == 最新交易日`,绿色 |
| 日线陈旧 | 245 | `last_daily_date < 最新交易日`,红色,副标"(含 ST 229)" |

### 区块二:宇宙画像

| 卡片 | 数值(示例) | 算法 |
|---|---|---|
| 非 ST / ST / 退市 | 4971 / 229 / 7 | 非 ST = `!is_st && !isDelisted`;ST = `is_st`;退市 = 名称含"退市"。ST/退市标色 |
| 沪市 / 深市 | 2314 / 2893 | `market === 'SH'` / `market === 'SZ'` |
| 行业数 | 146 | `uniq(industry)`(过滤空串) |

## 前端实现细节

### 模板结构

在 `StockList.vue` 的 `<template>` 最顶部(`.stock-list` 容器内、筛选 `el-form` 之上)插入统计头:

```vue
<div class="stat-header">
  <div class="stat-group">
    <div class="stat-group-title">数据健康</div>
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ items.length }}</div>
        <div class="stat-label">股票总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ latestDaily || '—' }}</div>
        <div class="stat-label">最新交易日</div>
      </div>
      <div class="stat-card">
        <div class="stat-value fresh">{{ countFresh }}</div>
        <div class="stat-label">日线新鲜</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stale">{{ countStale }}</div>
        <div class="stat-label">日线陈旧(含 ST {{ countSt }})</div>
      </div>
    </div>
  </div>
  <div class="stat-group">
    <div class="stat-group-title">宇宙画像</div>
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ countNonSt }} / <span class="st">ST {{ countSt }}</span> / <span class="delisted">退市 {{ countDelisted }}</span></div>
        <div class="stat-label">非 ST / ST / 退市</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ countSH }} / {{ countSZ }}</div>
        <div class="stat-label">沪市 / 深市</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ industryCount }}</div>
        <div class="stat-label">行业数</div>
      </div>
    </div>
  </div>
</div>
```

### 新增 computed

复用已有 `items`、`latestDaily`、`countNonSt`、`countSt`、`countDelisted`。新增:

```ts
const countFresh = computed(
  () => items.value.filter((i) => i.last_daily_date === latestDaily.value).length
)
const countStale = computed(
  () => items.value.filter((i) => i.last_daily_date && i.last_daily_date < latestDaily.value).length
)
const countSH = computed(() => items.value.filter((i) => i.market === 'SH').length)
const countSZ = computed(() => items.value.filter((i) => i.market === 'SZ').length)
const industryCount = computed(
  () => new Set(items.value.map((i) => i.industry).filter(Boolean)).size
)
```

### 空数据 / 加载态

`items` 为空时(加载中或失败),`latestDaily` 为空字符串,统计头各卡片显示 `—`(数值字段用 `|| '—'` 兜底,`items.length` 为 0 时总数显示 0 也合理)。不报错、不隐藏整块。

### 样式

`.stat-header` 横向 flex,两个 `.stat-group` 左右排列;`.stat-cards` 内卡片横向排列,数字大号粗体、标签灰色小字。复用现有 `.stale` 的 `#f56c6c`;新增 `.fresh` 用 `#67c23a`、`.st` 用 `#f56c6c`、`.delisted` 用 `#909399`。卡片间留间距,区块间留更大间距或分隔线。

## 错误处理与测试

- **错误处理**:统计头纯展示已加载数据,无独立错误路径。加载失败时 `items` 为空,统计头显示 `—`,与表格区的 `el-empty` 错误态并存。
- **测试**:项目无前端测试设施,不新增单元测试。靠手动验证覆盖。
- **手动验证清单**:
  - 页面加载,统计头显示:总数 5207、最新交易日 2026-07-01、日线新鲜 4962(绿)、日线陈旧 245(红,含 ST 229)。
  - 宇宙画像:非 ST 4971 / ST 229 / 退市 7;沪市 2314 / 深市 2893;行业数 146。
  - 搜索/筛选时统计头数字**不变**(固定全库),只有下方汇总条和表格变。
  - 数字与排查报告口径一致(245 陈旧 = 229 ST 断流 + 16 停牌/退市)。

## 改动范围

只动 `frontend/src/pages/StockList.vue`:模板加统计头一段、`<script setup>` 加 5 个 computed、`<style scoped>` 加 stat 相关类。无后端、无类型、无路由改动。
