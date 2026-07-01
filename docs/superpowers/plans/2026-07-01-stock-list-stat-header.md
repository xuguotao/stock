# 股票列表页统计头 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `StockList.vue` 头部加一个全库统计区,分"数据健康"和"宇宙画像"两区块,纯前端 computed 聚合已加载的 `items`。

**Architecture:** 单文件改动:`frontend/src/pages/StockList.vue`。模板在筛选区上方插入统计头(两组卡片),`<script setup>` 新增 5 个 computed(`countFresh`/`countStale`/`countSH`/`countSZ`/`industryCount`)复用已有 `items`/`latestDaily`/`countSt`,`<style scoped>` 新增 stat 相关类。零后端、零额外请求,固定全库不随筛选联动。

**Tech Stack:** Vue 3 + Element Plus + TypeScript + Vite。

## Global Constraints

- 代码标识、命令、API 路径、表名、字段名、文件路径保留原文;UI 文案使用中文叙述。
- 统计头固定全库,不随筛选联动(筛选联动由现有汇总条负责,保留不动)。
- 纯前端实现,复用已加载的 `items`,不加后端接口、不动 `client.ts`/`App.vue`。
- 遵循外科手术式改动:只动 `StockList.vue`,匹配既有风格,不顺手重构相邻代码。
- 前端无测试设施,靠 `vue-tsc --noEmit` + `npm run build` + 手动验证覆盖。

---

## File Structure

- **Modify:** `frontend/src/pages/StockList.vue` — 唯一改动文件。
  - `<template>`:在 `.stock-list` 容器内、`<el-form class="filters">` 之上插入 `.stat-header`。
  - `<script setup lang="ts">`:新增 5 个 computed。
  - `<style scoped>`:新增 `.stat-header` / `.stat-group` / `.stat-group-title` / `.stat-cards` / `.stat-card` / `.stat-value` / `.stat-label` / `.fresh` / `.st` / `.delisted` 类。

---

## Task 1: 加统计头(模板 + computed + 样式)

**Files:**
- Modify: `frontend/src/pages/StockList.vue`

**Interfaces:**
- Consumes: 已有的 `items` (`ref<StockListItem[]>`)、`latestDaily` (`computed<string>`,空数据返回 `''`)、`countSt` (`computed<number>`)、`countNonSt` (`computed<number>`)、`countDelisted` (`computed<number>`)。`StockListItem` 字段含 `market: string`、`industry: string`、`last_daily_date: string | null`、`is_st: boolean`。
- Produces: 5 个新 computed:`countFresh`/`countStale` (`number`)、`countSH`/`countSZ` (`number`)、`industryCount` (`number`);模板新增 `.stat-header` 块。无对外接口(纯展示组件内部)。

- [ ] **Step 1: 在模板顶部插入统计头**

在 `frontend/src/pages/StockList.vue` 的 `<template>` 中,找到第 2 行 `<div class="stock-list" v-loading="loading">` 之后、第 3 行 `<el-form :inline="true" class="filters">` 之前,插入以下统计头块:

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

- [ ] **Step 2: 新增 5 个 computed**

在 `<script setup lang="ts">` 中,找到已有的 `countDelisted` computed(约第 186 行):

```ts
const countDelisted = computed(() => items.value.filter((i) => isDelisted(i.name)).length)
```

在其后追加 5 个新 computed:

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

说明:`countStale` 的 filter 条件 `i.last_daily_date && ...` 先排除 null/空串,避免空字符串参与字符串比较产生误判;`latestDaily` 为空时(空数据)所有项都不满足 `< latestDaily.value`(因 `latestDaily.value` 为 `''`,`i.last_daily_date < ''` 对非空日期为 false),`countStale` 自然为 0。

- [ ] **Step 3: 新增样式**

在 `<style scoped>` 中,找到已有的 `.stale { color: #f56c6c; }`(约第 238-240 行),在其后追加:

```css
.stat-header {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
}

.stat-group {
  flex: 1;
}

.stat-group-title {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-cards {
  display: flex;
  gap: 16px;
}

.stat-card {
  min-width: 96px;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  line-height: 1.4;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.fresh {
  color: #67c23a;
}

.st {
  color: #f56c6c;
}

.delisted {
  color: #909399;
}
```

注意:已有的 `.stale` 类(红色 `#f56c6c`)继续用于统计头"日线陈旧"卡片和表格标红,不重复定义。新增的 `.st`/`.delisted`/`.fresh` 是统计头专用色。

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 退出码 0,无新增类型错误(新增的 5 个 computed 类型推导为 `ComputedRef<number>`,模板绑定合法)。

- [ ] **Step 5: 构建**

Run: `cd frontend && npm run build`
Expected: `vue-tsc --noEmit` 通过 + `vite build` 成功产出 `dist/`。预先存在的无关警告(如 chunk-size)可接受。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/StockList.vue
git commit -m "feat(frontend): 股票列表页加全库统计头"
```

---

## Task 2: 手动验证

**Files:** 无代码改动。

- [ ] **Step 1: 确认 web 在运行**

后端 `GET /api/stocks` 可访问(`curl -s http://127.0.0.1:8000/api/stocks` 返回 JSON)。前端 dev server 在 `http://127.0.0.1:5173`(若未运行,`bash scripts/restart_web.sh`)。Vite HMR 会自动热更新;若未生效,刷新浏览器。

- [ ] **Step 2: 执行验证清单**

打开 `http://127.0.0.1:5173`,进入「股票列表」页,逐项核对:
- 统计头在筛选区上方,分"数据健康"和"宇宙画像"两区块。
- 数据健康:股票总数 5207;最新交易日 2026-07-01;日线新鲜 4962(绿色);日线陈旧 245(红色,副标"含 ST 229")。
- 宇宙画像:非 ST 4971 / ST 229(红)/ 退市 7(灰);沪市 2314 / 深市 2893;行业数 146。
- 在搜索框输入"茅台"或勾选行业筛选:统计头数字**保持不变**(固定全库),只有下方汇总条和表格变。
- 数字与排查报告口径一致(245 陈旧 = 229 ST 断流 + 16 停牌/退市)。

- [ ] **Step 3: 全量后端测试回归(确认未误动后端)**

Run: `python -m pytest tests/test_web/ -q`
Expected: 全部通过(本任务未动后端,仅确认无意外回归)。

- [ ] **Step 4: 无 bug 则无需提交;发现 bug 回 Task 1 修复后重新提交。**
