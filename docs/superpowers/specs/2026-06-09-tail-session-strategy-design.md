# 尾盘获利选股策略设计文档

> 日期：2026-06-09
> 状态：设计确认
> 范围：Phase 1（日线突破 + 尾盘确认）+ Phase 2（分钟级实时扫描）

## 1. 概述

**目标**：在 A 股尾盘时段（14:30-15:00）识别强势股，买入后次日早盘卖出，利用 T+1 惯性冲高获利。

**核心逻辑**：
- 日线突破筛选候选池（趋势确认）
- 尾盘放量/价格异动确认买入信号（择时）
- 次日早盘强制平仓（纪律执行）

**用途**：
- 先回测验证历史表现
- 后模拟实盘运行（每日自动扫描）

## 2. 选股条件

### 2.1 日线级筛选（Phase 1）

| 条件 | 规则 | 说明 |
|------|------|------|
| 突破 | 创 20 日新高 或 MA5 上穿 MA20 | 趋势确认 |
| 上升斜率 | 近 5 日收盘价线性回归斜率 > 0 | 短期趋势向上 |
| ST 排除 | `is_st(name) == False` | 排除特殊处理股 |
| 次新股排除 | 上市天数 ≥ 60 | 排除流动性差的次新股 |
| 涨停排除 | 当日涨幅 < 10%（主板）/ 20%（创业板） | 涨停无法买入 |
| 流动性排除 | 近 20 日日均成交额 ≥ 500 万 | 排除僵尸股 |

### 2.2 尾盘择时确认（Phase 1 + Phase 2）

| 条件 | Phase 1（日线近似） | Phase 2（分钟级精确） |
|------|---------------------|----------------------|
| 尾盘价格 | 收盘价 > 日内均价 | 14:00-15:00 收阳线 |
| 尾盘放量 | 当日成交量 > 20 日均量 1.2 倍 | 5 分钟量 > 均量 1.5 倍 |
| 连续确认 | — | 连续 3 次 5 分钟扫描通过 |

## 3. 仓位管理

| 参数 | 值 | 说明 |
|------|------|------|
| 单只上限 | 总资金 20% | 最多持 5 只 |
| 总仓位上限 | 80% | 留 20% 现金缓冲 |
| 分配方式 | 等权 | 信号强度不区分权重 |
| 行业限制 | 单行业 ≤ 40% | 避免行业集中风险 |

## 4. 卖出逻辑

| 条件 | 动作 |
|------|------|
| 止盈 | 次日涨幅 ≥ +3% 立即卖出 |
| 止损 | 次日跌幅 ≥ -2% 立即卖出 |
| 强制平仓 | 次日 10:00 无论盈亏全部卖出 |
| 执行优先级 | 止损 > 止盈 > 强制平仓 |

**时间线**：
```
T 日 14:50 → 确认信号
T 日 14:55 → 市价买入
T+1 日 9:30 → 开盘监控
T+1 日 9:30-10:00 → 止盈/止损触发或强制平仓
```

## 5. 架构设计

### 5.1 模块关系

```
┌─────────────────────────────────────────────────┐
│                  TailSessionStrategy             │
│  ┌──────────────┐    ┌────────────────────────┐ │
│  │ DailyBreakout │───→│  IntradayConfirmation   │ │
│  │ Filter (P1)   │    │  (P1: 日线 / P2: 分钟)  │ │
│  └──────────────┘    └────────────────────────┘ │
│                      ↓                           │
│               ┌─────────────┐                    │
│               │ SignalEngine │───→ Buy/Sell      │
│               └─────────────┘                    │
└──────────────────────┬──────────────────────────┘
                       ↓
         ┌─────────────────────────────┐
         │     RiskManager             │
         │  (单只/总仓位/行业/回撤)     │
         └──────────────┬──────────────┘
                        ↓
         ┌─────────────────────────────┐
         │     SimulatedBroker /       │
         │     PaperAccount            │
         └─────────────────────────────┘
```

### 5.2 新增文件清单

**Phase 1**（基于现有日线数据）：

| 文件 | 说明 | 依赖 |
|------|------|------|
| `src/strategy/factors/tail_session.py` | `TailSessionFactor` — 尾盘突破因子 | `Factor` base, `calendar` |
| `src/strategy/filters.py` | `DailyBreakoutFilter` — 日线筛选器 | 无 |
| `src/strategy/filters.py` | `StockPoolFilter` — ST/次新/流动性过滤 | `constants.is_st` |
| `src/strategy/factors/overnight_momentum.py` | `OvernightMomentumFactor` — 次日惯性因子 | `Factor` base |
| `tests/test_strategy/test_tail_session.py` | 回测测试 | 全部 |
| `scripts/run_tail_session_backtest.py` | 回测运行脚本 | `BacktestEngine` |

**Phase 2**（需要分钟级数据）：

| 文件 | 说明 | 依赖 |
|------|------|------|
| `src/data/intraday_source.py` | 分钟级 K 线数据源 | `SinaSource`, `AKShareSource` |
| `src/strategy/scanner.py` | `IntradayScanner` — 实时扫描器 | `intraday_source` |
| `src/strategy/executor.py` | `RealTimeExecutor` — 执行器 | `scanner`, `PaperAccount` |
| `src/strategy/reports.py` | Markdown 日报生成 | `TailSessionSignal`, `BrokerTrade` |
| `src/trading/scheduler.py` | 新增 `is_tail_session()` | 已有 `TradingScheduler` |
| `scripts/run_tail_session_live.py` | 模拟实盘脚本 | 全部 |

### 5.3 与现有代码的集成点

| 现有模块 | 复用方式 | 改动 |
|----------|----------|------|
| `BacktestEngine` | 直接复用 | 新增 `TailSessionFactor` 作为因子传入 |
| `SimulatedBroker` | 直接复用 | 无改动 |
| `RiskManager` | 直接复用 | 新增止盈止损参数 |
| `PaperAccount` | 直接复用 | 无改动 |
| `TradingScheduler` | 扩展 | 新增 `is_tail_session()` 方法 |
| `FeeCalculator` | 直接复用 | 无改动 |
| `DataAggregator` | 扩展 | 新增 `get_intraday_bars()` 方法 |

## 6. 回测流程

```python
# 1. 加载数据
bars = aggregator.get_bars_batch(symbols, start, end, frequency="daily")

# 2. 构建因子
factor = TailSessionFactor(
    breakout_window=20,
    trend_window=5,
    volume_ratio_threshold=1.2,
)

# 3. 运行回测
engine = BacktestEngine(
    bars=bars,
    factors=[factor],
    top_n=5,
    rebalance_days=1,  # 每天重新选股
    initial_capital=100_000,
    equal_weight=True,
    min_score=1.0,  # 可选：排名前过滤弱原始因子值
)
result = engine.run()

# 4. 查看结果
print(result.metrics)
# {
#   "total_return": 15.3,
#   "annualized_return": 22.1,
#   "sharpe_ratio": 1.45,
#   "max_drawdown": -8.2,
#   "win_rate": 58.3,
# }
```

## 7. 模拟实盘流程

```python
# 每日定时任务
scheduler = TradingScheduler()
scanner = IntradayScanner(aggregator)
executor = RealTimeExecutor(paper_account, risk_manager)

# 14:30 开始扫描
if scheduler.is_tail_session() and scheduler.is_trading_day():
    candidates = scanner.scan(symbols, trade_date)  # 扫描股票池
    signals = scanner.confirm(candidates) # 确认买入信号
    trades = executor.execute_buy_signals(signals, prices, trade_date)
    write_tail_session_report(
        output_dir="reports/tail_session",
        trade_date=trade_date,
        scanned_count=len(symbols),
        candidates=candidates,
        confirmed=signals,
        trades=trades,
        account_summary=paper_account.summary(),
    )

# 次日 9:30 卖出
if scheduler.is_market_hours():
    executor.sell_positions(prices, trade_date)  # 止盈/止损/强制平仓
```

## 8. 数据需求

### 8.1 Phase 1（当前可用）

| 数据 | 来源 | 状态 |
|------|------|------|
| 日线 OHLCV | Sina/AKShare | ✅ 已有 |
| 股票列表 | Sina/AKShare | ✅ 已有 |
| 上市日期 | 需要从 AKShare 获取 | 📋 待补充 |

### 8.2 Phase 2（需要新增）

| 数据 | 来源 | 状态 |
|------|------|------|
| 5 分钟 K 线 | Sina (`scale=5`) | ✅ 已实现 |
| 30 分钟 K 线 | Sina (`scale=30`) | ✅ 已实现 |
| 分时均价（VWAP） | 从 5 分钟 K 线计算 | 📋 待补充 |

## 9. 风险与约束

| 风险 | 应对措施 |
|------|----------|
| 数据延迟 | 使用 Sina 直连，不受代理影响 |
| 流动性不足 | 过滤日均成交额 < 500 万的股票 |
| 滑点 | 回测中加 0.1% 滑点模拟 |
| 涨跌停无法成交 | 涨停排除 + 回测中检查涨跌停 |
| 节假日误交易 | 复用 `TradingCalendar` 过滤 |
| 策略过拟合 | 回测分训练集/测试集，不在测试集上调参 |

## 10. 验收标准

### Phase 1
- [x] `TailSessionFactor` 单元测试通过
- [x] 回测脚本可运行，输出完整指标
- [ ] 夏普比率 > 0.8，胜率 > 50%
- [x] README 更新使用文档
- [x] 支持本地 parquet 缓存离线回测，避免研究循环依赖实时网络
- [x] 支持构建稳定研究数据集：`python scripts/build_research_dataset.py`
- [x] 支持按成交额构建流动性研究池：`python scripts/build_liquid_research_dataset.py`
- [x] 支持离线参数网格评估：`python scripts/evaluate_tail_session_grid.py`
- [x] 支持最小入场分数门槛：`--min-score` / `--min-scores`

**存储策略**：
- Parquet 是研究回测主存储，用于批量读取 K 线面板数据。
- MySQL 可作为后续元数据、任务状态、实盘信号和交易记录库；不作为 pandas 回测的主读路径。
- 研究数据集默认输出到 `data/research/*.parquet`，manifest 记录样本范围、股票数、缺失股票和来源缓存文件。

**当前无门槛样本结果（2024-01-01 至 2025-06-01，10 只高流动性代表股）**：
- 总收益：2.59%
- 夏普：-0.006
- 胜率：44.54%
- 最大回撤：-13.32%
- 交易数：1450

该样本未达到夏普和胜率验收阈值，当前实现可作为策略研究和模拟执行框架，但不能据此认定策略有效。

**最小入场分数网格结果（20 日突破，5 日趋势，量比 1.2，top_n=5）**：
- `min_score=1.0`：总收益 11.78%，夏普 0.788，最大回撤 -5.77%，交易 240 笔
- `min_score=0.4`：总收益 9.08%，夏普 0.543，最大回撤 -7.89%，交易 343 笔
- `min_score=0.0`：总收益 2.87%，夏普 0.009，最大回撤 -14.06%，交易 1253 笔

该结果说明弱信号过滤比单纯调整突破窗口更有效，但胜率仍低，且样本只有 10 只股票，不能据此认定策略已具备真实交易有效性。

**近期流动性池结果（2025-01-01 至 2026-06-10，自动成交额 top30，min_score=1.0，top_n=5）**：
- 总收益 12.22%，年化收益 8.76%，夏普 0.378，最大回撤 -17.6%，交易 903 笔
- 对照：主板前 50 只近似池同配置总收益 -28.38%，夏普 -1.215，最大回撤 -38.94%

该对照说明股票池构建是当前策略效果的一阶变量；每日尾盘选股应优先使用流动性池，而不是 `get_csi300_symbols()` 当前的主板近似列表。

**历史参数网格 smoke 结果（10/20 日突破窗口，其他参数固定）**：
- 20 日突破：总收益 2.59%，夏普 -0.006，胜率 44.54%，交易 1450 笔
- 10 日突破：总收益 2.31%，夏普 -0.022，胜率 45.43%，交易 1432 笔

单纯调整突破窗口没有改善夏普；后续应继续扩大离线样本、做样本外切分和风控出场验证。

### Phase 2
- [x] 5 分钟 K 线数据获取测试通过
- [x] `IntradayScanner` 单元测试通过
- [x] 模拟实盘单次扫描脚本可运行
- [ ] 模拟实盘可连续运行 5 个交易日无报错
- [x] 每日自动生成交易报告
- [x] 每日尾盘可输出最终选股名单：`--selection-only --output-json --output-csv`
- [x] 每日尾盘扫描可使用流动性股票池：`--universe liquid-cache`
