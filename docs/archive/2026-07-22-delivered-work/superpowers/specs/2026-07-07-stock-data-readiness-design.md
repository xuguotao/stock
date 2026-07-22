# 策略数据就绪度页面设计

日期：2026-07-07

## 目标

提供一个 Web 页面，让策略研究者快速知道：**给定回测时间窗口，哪些股票的数据是完整的，可以直接用于策略回测和因子挖掘。** 当数据不完整时，支持定向多数据源自动回补。

## 核心概念

- **初始池**：由离线脚本自行计算，不依赖 `stock_research_status.research_eligible`。计算规则：从 `stocks` 表取 SH/SZ 市场、非ST、非退市、上市满 60 个交易日的股票
- **各维度独立就绪状态**：不同数据粒度有不同的就绪判定，一只股票可以日线就绪但 5m 未就绪
- **数据就绪度**：给定回测窗口 N 天和多维度要求，初始池中有多少股票数据完整可用
- **连续可回测天数**：从最新有数据的日期往前推，连续有数据的交易日天数（遇到缺口停止）

## 架构

### 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  前端: StockHealth.vue (独立页面, 菜单项)                      │
├──────────────────────────────────────────────────────────────┤
│  后端 API: src/web/backend/stock_health.py                   │
│    GET  /api/stock-health/summary                            │
│    GET  /api/stock-health                                    │
│    POST /api/stock-health/repair                             │
│    GET  /api/stock-health/repair/{job_id}                    │
├──────────────────────────────────────────────────────────────┤
│  data_ops 任务模块:                                           │
│    src/data_ops/handlers.py — 新增 compute_readiness handler  │
│    src/data_ops/handlers.py — 新增 repair_data handler        │
│    src/data_ops/models.py — 注册到 default_task_configs()     │
├──────────────────────────────────────────────────────────────┤
│  数据存储: ClickHouse stock_data_readiness 表                 │
└──────────────────────────────────────────────────────────────┘
```

### 设计原则

- **离线预计算 + 快速查询**：不实时计算，页面只读预计算结果
- **独立页面**：不扩展现有数据中心，新建独立路由和组件
- **自动检测 + 受控回补**：系统自动发现缺口并尝试修复，但限制重试次数防止死循环
- **集成 data_ops**：所有离线任务通过 data_ops 模块调度运行，不写独立脚本
- **各维度独立判断**：初始池计算不依赖 `research_eligible`，各维度独立判断就绪状态

## 数据模型

### ClickHouse 新增表：`stock_data_readiness`

```sql
CREATE TABLE IF NOT EXISTS stock_data_readiness (
    symbol String,
    name String,
    market LowCardinality(String),
    board LowCardinality(String),

    -- 日线
    daily_contiguous_days UInt16,
    daily_latest_date Nullable(Date),
    daily_status LowCardinality(String),  -- ready / gap_repairable / gap_unrepairable / no_data
    daily_repair_attempts UInt8,           -- 回补尝试次数

    -- 5分钟线
    minute5_contiguous_days UInt16,
    minute5_latest_date Nullable(Date),
    minute5_status LowCardinality(String),
    minute5_repair_attempts UInt8,

    -- 行情快照
    snapshot_contiguous_days UInt16,
    snapshot_latest_date Nullable(Date),
    snapshot_status LowCardinality(String),
    snapshot_repair_attempts UInt8,

    -- 除权除息
    xdxr_contiguous_days UInt16,
    xdxr_latest_date Nullable(Date),
    xdxr_status LowCardinality(String),
    xdxr_repair_attempts UInt8,

    computed_at DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY symbol
```

**关键指标 `contiguous_days`**：从最新有数据的日期往前推，连续有数据的交易日天数。遇到缺口就停止计数。

示例：
- 000001 日线最新到 7/7，7/1-7/7 全部连续 → `daily_contiguous_days = 5`
- 如果 7/3 缺失 → `daily_contiguous_days = 2`（只有 7/7 和 7/6）

**各维度计算说明**：

| 维度 | 计算方式 | 说明 |
|------|----------|------|
| daily | 从 `daily_kline` 计算连续有数据的交易日 | 核心维度，决定回测深度 |
| minute5 | 从 `minute5_kline` 计算连续有数据的交易日 | 尾盘策略依赖此维度 |
| snapshot | 从 `stock_quote_snapshots` 计算最近有快照的交易日天数 | 快照只保留短周期，`contiguous_days` 反映近期快照覆盖 |
| xdxr | 从 `xdxr_info` 检查该股票是否有除权除息记录 | 不是连续天数概念，`contiguous_days` 设为该股票历史除权次数；`ready` 表示 xdxr 数据存在 |

### 计算逻辑（data_ops handler）

**初始池计算**（不依赖 `research_eligible`）：

```python
# 从 stocks 表直接计算
SELECT symbol, name, market, list_date
FROM stocks FINAL
WHERE market IN ('SH', 'SZ')
  AND name NOT LIKE '%ST%'
  AND name NOT LIKE '%退%'
  AND list_date <= :cutoff_date  # 上市满 60 个交易日
```

**各维度就绪判定**：

对每只初始池股票、每个维度：

1. 获取最新有数据的日期 `latest_date`
2. 从 `trade_calendar` 获取 `latest_date` 之前的交易日序列
3. 逐个检查是否有数据，连续计数直到遇到缺口
4. 写入 `stock_data_readiness` 表

**维度状态字段**：每只股票每个维度有独立的状态：

| 状态 | 含义 |
|------|------|
| `ready` | 数据完整，可用于回测 |
| `gap_repairable` | 有缺口但可通过数据源回补 |
| `gap_unrepairable` | 有缺口且无法回补（停牌、数据源无此数据等） |
| `no_data` | 完全无数据（新上市、长期停牌等） |

## 后端 API

### `GET /api/stock-health/summary`

返回统计摘要，用于页面顶部统计卡片。

响应：

```json
{
    "total_eligible": 5323,
    "ready_counts": {
        "90": { "all_dims": 5200, "daily_only": 5300, "minute5_only": 5250 },
        "180": { "all_dims": 4892, "daily_only": 5100, "minute5_only": 4950 },
        "360": { "all_dims": 4651, "daily_only": 4800, "minute5_only": 4700 },
        "500": { "all_dims": 4523, "daily_only": 4650, "minute5_only": 4580 },
        "all": { "all_dims": 3602, "daily_only": 3800, "minute5_only": 3700 }
    },
    "unrepairable_count": 23,
    "last_computed_at": "2026-07-07T18:00:00"
}
```

### `GET /api/stock-health`

分页查询股票健康度。

参数：
- `lookback`：回测天数 (90/180/360/500/all)
- `dimensions`：需要的维度，逗号分隔 (daily,minute5,snapshot,xdxr)
- `status`：过滤状态 (all/ready/not_ready/unrepairable)
- `market`：市场过滤 (SH/SZ)
- `board`：板块过滤 (MAIN/CHINEXT/STAR)
- `sort_by`：排序字段 (symbol/name/daily_days/minute5_days)
- `sort_order`：排序方向 (asc/desc)
- `page`：页码
- `page_size`：每页条数

响应：

```json
{
    "total": 431,
    "page": 1,
    "page_size": 50,
    "stocks": [
        {
            "symbol": "000001",
            "name": "平安银行",
            "market": "SZ",
            "board": "MAIN",
            "ready": false,
            "dimensions": {
                "daily": {
                    "contiguous_days": 178,
                    "latest_date": "2026-07-07",
                    "status": "gap_repairable",
                    "repair_attempts": 1,
                    "gap_dates": ["2026-07-03", "2026-07-04"]
                },
                "minute5": {
                    "contiguous_days": 180,
                    "latest_date": "2026-07-07",
                    "status": "ready",
                    "repair_attempts": 0,
                    "gap_dates": []
                },
                "snapshot": {
                    "contiguous_days": 5,
                    "latest_date": "2026-07-07",
                    "status": "ready",
                    "repair_attempts": 0,
                    "gap_dates": []
                },
                "xdxr": {
                    "contiguous_days": 180,
                    "latest_date": "2026-07-07",
                    "status": "ready",
                    "repair_attempts": 0,
                    "gap_dates": []
                }
            },
            "repairable": true
        }
    ]
}
```

**字段说明**：
- 各维度 `status`：`ready` / `gap_repairable` / `gap_unrepairable` / `no_data`
- 股票级 `ready`：所有选中维度的 `status == ready` 且 `contiguous_days >= lookback` 时为 `true`
- `repairable`：至少有一个维度的 `status == gap_repairable`（可以回补）
- `gap_dates`：最多返回最近 30 个缺失日期；超过 30 个时只返回前 30 个，并附加 `"gap_dates_truncated": true`

### `POST /api/stock-health/repair`

触发回补任务。

请求体：

```json
{
    "symbols": ["000001", "000002"],
    "dimensions": ["daily", "minute5"]
}
```

响应：

```json
{
    "job_id": "repair-20260707-180000",
    "status": "started"
}
```

### `GET /api/stock-health/repair/{job_id}`

查询回补任务状态。

响应：

```json
{
    "job_id": "repair-20260707-180000",
    "status": "running",
    "progress": {
        "total": 2,
        "completed": 1,
        "current": "000002"
    },
    "results": [
        { "symbol": "000001", "status": "success", "repaired_days": 2 }
    ]
}
```

## 回补机制

### 回补限制（防止死循环）

- **单股票单维度最大重试次数**：3 次。超过后标记为 `gap_unrepairable`，不再自动尝试
- **单次批量回补上限**：100 只股票，避免一次触发过多请求
- **回补间隔**：每只股票回补之间间隔 1 秒
- **每日自动回补上限**：500 只股票/天，防止异常情况下无限消耗数据源配额
- **手动覆盖**：用户可在页面手动重置 `repair_attempts` 计数器，强制重新尝试

### 不可修复股票的展示

在页面统计区域增加一个"不可修复"统计卡片：

```
┌────────────┐
│  不可修复   │
│    23      │
│  需要关注   │
└────────────┘
```

点击后筛选出所有包含 `gap_unrepairable` 维度状态的股票，表格中高亮显示。

用户可以看到：
- 哪些股票无法修复
- 具体哪个维度无法修复
- 已经尝试了多少次
- 手动重置按钮（确认数据源已恢复后重试）

### 数据源优先级

| 维度 | 数据源优先级 | 回补方式 |
|------|-------------|---------|
| 日线 | 腾讯 → 新浪 → AKShare | `DataAggregator.get_daily_bars()` |
| 5分钟线 | 腾讯 → 新浪 | `DataAggregator.get_intraday_bars()` |
| 行情快照 | 腾讯 | 实时获取，不支持历史回补 |
| 除权除息 | tdxrs | `sync_xdxr_info()` |

### 回补流程

1. 用户在页面点击"回补"按钮
2. 后端检查 `repair_attempts < 3` 且未超每日上限
3. 创建回补任务，注册到 `data_ops` 任务系统
4. 异步执行：按数据源优先级依次尝试
5. 回补成功 → 重置 `repair_attempts`，触发重新计算
6. 回补失败 → `repair_attempts += 1`；若达到上限，标记为 `gap_unrepairable`
7. 前端轮询任务状态，完成后刷新页面

### 批量回补

- 页面顶部有"一键回补所有可修复股票"按钮
- 按优先级依次回补，避免并发请求打爆数据源
- 每次回补间隔 0.5-1 秒

## 前端页面

### 文件结构

- `frontend/src/pages/StockHealth.vue` — 页面组件
- `frontend/src/api/client.ts` — 新增 API 调用函数

### 导航

App.vue 菜单增加"数据就绪度"项，放在"数据中心"后面。

### 页面布局

```
┌──────────────────────────────────────────────────────────┐
│  策略数据就绪度                                           │
├──────────────────────────────────────────────────────────┤
│  统计卡片                                                 │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ │
│  │  90天  │ │ 180天  │ │ 360天  │ │ 500天  │ │  全量  │ │
│  │  5200  │ │  4892  │ │  4651  │ │  4523  │ │  3602  │ │
│  │ 97.7%  │ │ 91.9%  │ │ 87.4%  │ │ 85.0%  │ │ 67.6%  │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ │
│  ┌────────────┐                                          │
│  │  不可修复   │  ← 点击筛选出所有 gap_unrepairable 股票    │
│  │    23      │                                          │
│  └────────────┘                                          │
├──────────────────────────────────────────────────────────┤
│  筛选栏                                                   │
│  回测天数: [180 ▼]  维度: [✓日线] [✓5m] [□快照] [□除权]    │
│  状态: [未就绪 ▼]  市场: [全部 ▼]  板块: [全部 ▼]          │
│  [一键回补]                                               │
├──────────────────────────────────────────────────────────┤
│  表格                                                     │
│  Symbol │ 名称 │ 市场 │ 日线 │ 5m │ 快照 │ 除权 │ 操作    │
│  000001 │ 平安  │ SZ  │ 178  │ 180│ 180  │ 180  │ [回补] │
│  ⚠️ 002 │ 某某  │ SH  │ 不可修│ -- │ --   │ --   │ [重置] │  ← 不可修复行高亮
│  ...                                                     │
│  展开详情: 缺失日期列表, 回补次数, 回补历史                  │
└──────────────────────────────────────────────────────────┘
```

### 交互

- 点击统计卡片 → 切换表格的 lookback 过滤条件
- 点击"不可修复"卡片 → 筛选出所有包含 `gap_unrepairable` 的股票
- 点击表头 → 排序
- 点击行 → 展开详情（缺失日期、回补次数、回补历史）
- 点击"回补"按钮 → 触发单只股票回补（仅 `gap_repairable` 状态可用）
- 点击"重置"按钮 → 重置 `repair_attempts` 计数器，强制重新尝试
- 点击"一键回补" → 批量回补所有 `gap_repairable` 股票（上限 100 只）

## 离线任务（data_ops 模块）

### `compute_readiness` handler

在 `src/data_ops/handlers.py` 新增 handler，注册到 `src/data_ops/models.py` 的 `default_task_configs()`。

功能：
1. 从 `stocks` 表自行计算初始池（SH/SZ、非ST、非退市、上市满 60 个交易日）
2. 对每只股票、每个维度计算 `contiguous_days` 和 `status`
3. 写入 `stock_data_readiness` 表

调度：
- 定时：通过 data_ops 调度，每天盘后运行
- 手动触发：通过任务中心或 API
- 回补后自动触发

### `repair_data` handler

在 `src/data_ops/handlers.py` 新增 handler。

功能：
1. 从 `stock_data_readiness` 读取有缺口且 `repair_attempts < 3` 的股票
2. 按数据源优先级依次尝试回补
3. 成功 → 重置 `repair_attempts`，触发 `compute_readiness`
4. 失败 → `repair_attempts += 1`
5. 检查每日回补上限（500 只/天）

### 核心计算模块

`src/data/stock_data_readiness.py`：

- `compute_initial_pool()` — 从 stocks 表计算初始池，不依赖 research_eligible
- `compute_contiguous_days(client, symbol, dimension, latest_date)` — 计算连续可回测天数
- `determine_status(contiguous_days, repair_attempts)` — 判定维度状态
- `persist_readiness(client, rows)` — 写入 ClickHouse

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `frontend/src/pages/StockHealth.vue` | 新增 | 策略数据就绪度页面 |
| `frontend/src/api/client.ts` | 修改 | 新增 API 调用函数 |
| `frontend/src/App.vue` | 修改 | 菜单增加"数据就绪度" |
| `src/web/backend/stock_health.py` | 新增 | 后端 API 路由 |
| `src/web/backend/app.py` | 修改 | 注册 stock_health router |
| `src/data/stock_data_readiness.py` | 新增 | 数据就绪度核心计算逻辑 |
| `src/data_ops/handlers.py` | 修改 | 新增 compute_readiness 和 repair_data handler |
| `src/data_ops/models.py` | 修改 | 注册新任务到 default_task_configs |
| `tests/test_web/test_stock_health.py` | 新增 | API 测试 |
| `tests/test_data_ops/test_readiness_handlers.py` | 新增 | data_ops handler 测试 |
