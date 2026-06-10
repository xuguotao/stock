# A股量化工具 (A-Share Quant Platform)

面向A股（沪深市场）的全栈Python量化工具，包含数据获取、策略回测、因子研究和实盘模拟交易四大模块。

## 安装

```bash
pip install -e .
```

或安装开发依赖：

```bash
pip install -e ".[dev]"
```

## 快速开始

### 1. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 Tushare token（可选）
```

### 2. 下载数据

```bash
# 下载沪深300成分股最近5年日线数据
python scripts/download_history.py

# 下载指定股票
python scripts/download_history.py --symbols 000001 600519 300750

# 指定日期范围
python scripts/download_history.py --start 2020-01-01 --end 2025-12-31 --limit 50

# 清空缓存重新下载
python scripts/download_history.py --clear-cache
```

### 3. 测试网络

```bash
python scripts/test_network.py
```

### 4. 运行测试

```bash
pytest -v          # 运行所有测试
pytest -q          # 精简输出
```

### 5. 运行尾盘策略回测

```bash
# 默认回测沪深300前50只
python scripts/run_tail_session_backtest.py

# 指定股票
python scripts/run_tail_session_backtest.py --symbols 000001 600519 300750

# 指定日期范围和资金
python scripts/run_tail_session_backtest.py --start 2023-01-01 --end 2025-06-01 --capital 200000

# 使用本地 parquet 缓存离线评估，并输出 JSON 指标
python scripts/run_tail_session_backtest.py \
  --symbols 000001 600519 300750 \
  --start 2024-01-01 \
  --end 2025-06-01 \
  --offline-cache \
  --output-json reports/tail_session/backtest_sample.json
```

### 6. 运行尾盘模拟扫描

```bash
# 交易日 14:30-15:00 窗口内运行
python scripts/run_tail_session_live.py --symbols 000001 600519

# 手动演练，不检查当前时间窗口
python scripts/run_tail_session_live.py --symbols 000001 --ignore-session --confirmations 1

# 指定日报输出目录
python scripts/run_tail_session_live.py --symbols 000001 --report-dir reports/tail_session
```

## 项目结构

```
├── config/                    # 配置
│   ├── settings.py            # Pydantic配置加载
│   ├── trading_rules.yaml     # A股交易规则
│   └── commission.yaml        # 费率结构
├── src/
│   ├── core/                  # 共享工具
│   │   ├── broker_base.py     # BaseBroker + FeeCalculator（共享交易逻辑）
│   │   ├── calendar.py        # 中国交易日历
│   │   ├── constants.py       # 市场常量
│   │   └── types.py           # 类型定义
│   ├── data/                  # 模块1: 数据获取
│   │   ├── base.py            # 抽象接口(DataSource Protocol)
│   │   ├── sina_source.py     # 新浪财经(主数据源, 直连)
│   │   ├── intraday_source.py # 分钟级K线数据源
│   │   ├── akshare_source.py  # AKShare(备用数据源)
│   │   ├── aggregator.py      # 多源聚合+自动降级
│   │   ├── cache.py           # Parquet缓存(TTL管理)
│   │   └── models.py          # 数据模型
│   ├── strategy/              # 模块2: 策略回测
│   │   ├── base.py            # Factor抽象类 + CompositeFactor
│   │   ├── factors/           # 因子库: 动量、趋势、均值回复、价值
│   │   ├── scanner.py         # 尾盘分钟级扫描器
│   │   ├── executor.py        # 尾盘模拟实盘执行器
│   │   ├── engine/            # 回测引擎
│   │   └── execution/         # 模拟经纪商(基于BaseBroker)
│   ├── research/              # 模块3: 因子研究
│   │   ├── factor_analysis/   # IC分析、分层分析、中性化
│   │   └── portfolio/         # CVXPY组合优化
│   └── trading/               # 模块4: 模拟交易
│       ├── paper_account.py   # 持久化模拟账户(基于BaseBroker)
│       ├── signal_engine.py   # 信号引擎
│       ├── risk_manager.py    # 风控管理器
│       └── scheduler.py       # 交易调度器
├── tests/                     # 测试套件 (146个测试)
│   ├── test_data/             # 数据层测试
│   ├── test_strategy/         # 策略层测试
│   ├── test_trading/          # 交易层测试
│   └── test_research/         # 研究层测试
├── scripts/
│   ├── download_history.py    # 数据下载脚本
│   ├── monitor_zijin.py       # 紫金矿业监控
│   └── test_network.py        # 网络诊断脚本
└── notebooks/                 # Jupyter研究笔记
```

## 当前状态

### ✅ Phase 1: 数据层 (已完成)
- 项目脚手架和配置系统 (Pydantic + YAML)
- Sina Finance 数据源 (直连, 代理环境可用)
- AKShare 数据源 (备用, 用于股票列表)
- Parquet 本地缓存 (TTL管理, 100x 读取加速)
- 中国交易日历 (2024-2026节假日)
- A股市场常量 (板块识别、ST检测、symbol格式化)
- 数据聚合器 (多源优先级+自动降级)

### ✅ Phase 2: 因子库 + 基础回测 (已完成)
- 动量、趋势、均值回复、价值和组合因子
- A股模拟Broker: T+1、买入手数、交易费用、印花税
- Top-N 因子调仓回测引擎
- 回测绩效指标: 收益、年化、波动率、夏普、最大回撤、胜率

### ✅ Phase 3: 因子研究管线 (已完成)
- IC / RankIC 分析
- 因子分层收益分析
- 行业和市值中性化
- CVXPY 组合优化: 最大夏普、最小方差、风险平价、等权

### ✅ Phase 4: 模拟交易系统 (已完成)
- 可持久化的模拟交易账户 (基于 BaseBroker)
- 信号引擎
- 风控管理器: 回撤、单票集中度、行业集中度、总仓位、交易次数
- 交易日和调仓日调度器

### ✅ Phase 5: 尾盘获利选股策略 (已完成)
- 日线突破筛选器 (DailyBreakoutFilter)
- 趋势确认筛选器 (DailyTrendFilter)
- 股票池过滤 (ST/次新/流动性/涨停)
- 尾盘突破因子 (TailSessionFactor)
- 次日惯性因子 (OvernightMomentumFactor)
- 回测脚本: `python scripts/run_tail_session_backtest.py`
- 分钟级K线入口: `DataAggregator.get_intraday_bars()`
- 尾盘分钟级扫描器 (IntradayScanner)
- 模拟实盘执行器 (RealTimeExecutor)
- 模拟扫描脚本: `python scripts/run_tail_session_live.py`
- 每日 Markdown 交易报告: `reports/tail_session/`
- 交易调度器扩展 (is_tail_session)

### 测试覆盖

| 模块 | 测试数 |
|------|--------|
| Data (models, cache, aggregator) | 19 |
| Strategy (factors, broker, backtest, tail session) | 70 |
| Trading (signal, risk, scheduler, paper) | 34 |
| Research (neutralization, IC, quantile, fund tail) | 14 |
| Monitoring (紫金) | 6 |
| Core behaviors | 3 |
| **总计** | **146** |

## 数据源说明

| 数据源 | 用途 | 状态 | 说明 |
|--------|------|------|------|
| **Sina Finance** | 日线K线 | ✅ 主数据源 | 直连新浪API，代理环境可用，支持1000条历史K线 |
| **Sina Finance** | 5/15/30/60分钟K线 | ✅ 已集成 | 用于尾盘扫描和模拟实盘 |
| **Sina hq** | 实时行情 | ✅ 已集成 | 交易时段返回实时价格，非交易时段返回前收价 |
| **AKShare** | 股票列表 | ✅ 备用数据源 | 用于获取全量A股列表，AKShare K线在代理下不可用 |
| **Tushare Pro** | 财务数据 | 📋 待开发 | 需要token，财务数据更准确 |

**网络说明**:
- Sina Finance 使用 `http.client` 直连，不受系统代理影响
- AKShare 使用 `requests`，受系统代理影响（已在 Clash 规则中添加东方财富直连规则）
- 如果仍然遇到问题，可以在 Clash 中暂时关闭代理

## A股交易规则

- **T+1**: 今日买入不可卖出
- **涨跌停**: 主板±10%，创业板/科创板±20%，北交所±30%
- **手数**: 买入必须100股整数倍
- **费率**: 印花税卖出0.05%，佣金双边0.025%（最低5元）
# Stock
