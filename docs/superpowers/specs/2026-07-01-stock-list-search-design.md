# 股票列表检索页设计

## 背景与目标

数据中心仪表盘上 `股票基础信息` 显示 5207、`股票日线` 显示 4960,差 247。`docs/superpowers/reviews/2026-07-01-stock-vs-daily-count-gap-analysis.md` 已查清这是口径差异(ST 排除 + 最新日过滤)叠加一个真实管道缺口(229 只 ST 日线自 2026-06-17 起断流)。

本专项不解决数据缺口,只解决**检索**:提供一个页面,能按代码/名称/行业/市场/状态快速找到已入库的股票,看到其基础信息与最新日线日期,并能跳转到"个股趋势"页深入查看。

## 范围

- 只读检索页,数据源为已入库的 stocks 表(5207 只)。
- 检索方式:代码搜索、名称搜索、行业筛选、市场筛选、状态筛选(ST / 非 ST / 退市)。
- 点中股票:行内展开看摘要 + 「查看趋势」跳转。
- 数据新鲜度:每行带"最新日线日期"列,呼应排查报告让数据缺口可见。
- 不在本轮范围:数据质量诊断视图(方案 A)、ST 日线断流修复、新增数据字段(如 `is_st`/`delist_date` 落库)。

## 整体架构

新增一个只读检索页"股票列表",放在侧边栏"数据中心"之后。

- **前端**:新增 `frontend/src/pages/StockList.vue`,沿用 Element Plus `el-table` 风格(与 `DataCenter.vue` 一致)。`App.vue` 加菜单项 `stock-list`「股票列表」+ 对应 `v-else-if` 渲染。无 vue-router,沿用 `activePage` 切页机制。
- **后端**:在 `src/web/backend/app.py` 新增 `GET /api/stocks`,返回全量列表(含每只股票最新日线日期)。数据源 ClickHouse。
- **跳转**:行内「查看趋势」按钮 emit 到 `App.vue`,复用已有 `targetSymbol` 机制跳到 `stock-trend` 页。

数据流:`StockList.vue` 挂载 → 调 `GET /api/stocks` → 后端查 ClickHouse(stocks LEFT JOIN daily_kline 取 max date)→ 返回 JSON → 前端一次性持有,客户端搜索/筛选/排序/分页。

## 后端接口 `GET /api/stocks`

**路径**:`GET /api/stocks`(与现有 `/api/stocks/{symbol}/trend` 不冲突)。

**职责**:返回 stocks 表全量股票,每条附带最新日线日期。无查询参数(全量返回,筛选/排序/分页交前端)。

**数据源**:ClickHouse,复用现有 client 获取方式(与 `_clickhouse_stock_summary` 同源),确保和排查报告口径一致。

**查询**(一条 SQL):

```sql
select
  s.symbol,
  s.name,
  s.industry,
  s.market,
  s.list_date,
  max(d.date) as last_daily_date
from stocks s
left join daily_kline d on d.symbol = s.symbol
group by s.symbol, s.name, s.industry, s.market, s.list_date
order by s.symbol
```

LEFT JOIN 保留"有 stocks 记录但无任何日线"的股票(排查报告里那 18 只非 ST 无 bar 的情况),其 `last_daily_date` 为 `null`,前端照常展示。

**返回结构**:

```json
{
  "items": [
    {
      "symbol": "000001.SZ",
      "name": "平安银行",
      "industry": "银行",
      "market": "SZ",
      "list_date": "1991-04-03",
      "last_daily_date": "2026-06-30",
      "is_st": false
    }
  ],
  "total": 5207
}
```

**`is_st` 字段**:stocks 表无此列,后端用现有 `is_st(name)`(`src/core/constants.py:73`)在拼装响应时推导,口径与数据中心统计一致,避免前端重复实现。

**错误处理**:ClickHouse 不可达时返回 500 + `{"detail": "..."}`,不做静默降级(页面主数据失败就明确失败)。

**代码组织**:查询逻辑放 `data_status.py` 新增函数 `fetch_stock_list(client) -> list[dict]`,`app.py` 只做路由注册和调用,保持薄路由风格。

## 前端 `StockList.vue`

### 布局

1. **顶部筛选区**(一行 `el-form` inline)
   - `el-input` 搜索框:占位"代码 / 名称",输入即过滤 symbol 或 name(不区分大小写、子串匹配)。
   - `el-select`(multiple, filterable)行业:选项从已加载数据动态聚合。
   - `el-select`(multiple)市场:SZ / SH(从 market 字段聚合)。
   - `el-select` 状态:全部 / 非 ST / ST / 退市(名称含"退市")。
   - `el-button`「重置」清空所有筛选。

2. **汇总条**:显示"共 X 只 / 符合筛选 Y 只",括号标注口径"非 ST N 只 · ST M 只 · 退市 K 只",让 5207 vs 4960 口径一眼可辨。

3. **表格** `el-table`,列:

   | 列 | 字段 | 说明 |
   |---|---|---|
   | 代码 | symbol | 等宽 |
   | 名称 | name | ST/退市用 `el-tag` 标色(ST=红、退市=灰) |
   | 行业 | industry | |
   | 市场 | market | |
   | 上市日 | list_date | |
   | 最新日线 | last_daily_date | null 显示"—";早于全量数据中 `last_daily_date` 最大值则标红(该最大值即最新交易日基准,如 2026-06-30) |
   | 操作 | — | 「查看趋势」按钮 |

   行可展开(`type="expand"`):展开显示该股票全部基础信息摘要(含 is_st 推导结果、market、上市日、最新日线)。

4. **分页** `el-pagination`:前端分页,默认每页 50,可选 20/50/100。筛选后对过滤后的子集分页。

### 交互

- 搜索/筛选都是客户端即时响应(`computed` 派生 filtered list),无额外请求。
- 「查看趋势」`emit('open-trend', symbol)` → `App.vue` 设 `targetSymbol` + `activePage='stock-trend'`,复用现有机制(需在 `App.vue` 加 emit 处理,类似已有 `open-result`)。
- 加载中用 `v-loading`,错误时表格区显示 `el-empty` + 错误信息 + 「重试」按钮。

### 代码风格

对齐 `DataCenter.vue` 的 `<template>`/`<script setup lang="ts">`/`<style scoped>` 结构,复用 `src/api/client.ts` 的请求封装。

## 错误处理与测试

### 错误处理

- 后端:ClickHouse 查询失败 → 路由抛出被 FastAPI 默认异常处理转成 500,返回 `{"detail": "..."}`,前端据此显示错误态。不做静默降级。
- 前端:请求失败 → `el-empty` 占位 + 错误文案 + 「重试」按钮重新请求;`last_daily_date` 为 null → 显示"—";行业/market 为空字符串 → 显示"—"避免空白格。

### 测试

后端(`tests/test_web/test_stocks_api.py`,参考已有 `test_data_status_api.py` 的 fixture 风格):

1. `GET /api/stocks` 返回全量,`total` 与 items 长度一致,字段齐全。
2. `is_st` 推导正确:名称含 `*ST`/`ST` 的标记为 true,正常股 false。
3. LEFT JOIN 行为:一只 stocks 表里有、daily_kline 里没有的股票,`last_daily_date` 为 null 且仍出现在结果里。
4. ClickHouse 不可达时返回 500(mock client 抛异常)。

前端:项目无前端测试设施,不新增。靠后端测试 + 手动验证覆盖。

### 手动验证清单

- 页面加载 5207 条,汇总条口径数字与排查报告对得上(非 ST 4978、ST 229 量级)。
- 搜"茅台"→ 1 条;搜"000001"→ 平安银行等前缀匹配。
- 状态筛"ST"→ 229 条,最新日线列普遍停在 06-17(红色)。
- 筛"退市"→ 名称含退市的那些,last_daily_date 早于最新交易日。
- 点「查看趋势」→ 跳到个股趋势页且 symbol 正确传入。

## 入口与命名

- 侧边栏位置:"数据中心"之后,菜单项「股票列表」,路由 key `stock-list`。
- 前端文件:`frontend/src/pages/StockList.vue`。
- 后端路由:`GET /api/stocks`,查询逻辑在 `src/web/backend/data_status.py` 的 `fetch_stock_list`。
