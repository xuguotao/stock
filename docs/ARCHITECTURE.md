# A 股量化工具架构说明

## 项目定位

本项目是面向 A 股研究和模拟交易的 Python 量化工具。当前能力覆盖四条主线：

- 数据获取与本地缓存：从 Sina/AKShare 等数据源获取行情、股票列表和实时行情。
- 离线研究：构建 research parquet 数据集，进行因子计算、IC 分析、分层分析和参数网格评估。
- 策略回测：基于日频 bars、因子评分、组合调仓和 A 股交易规则模拟回测。
- 模拟交易：尾盘分钟级扫描、信号确认、风险检查、纸面账户和日报输出。

项目应把 Qlib 这类外部研究平台视为“研究/预测适配器”，而不是替代现有的 A 股交易工程层。

## 顶层模块

```text
config/                 配置、费率、交易规则
src/core/               通用类型、交易日历、基础 Broker 逻辑
src/data/               数据源、缓存、研究数据集、bars repository
src/strategy/           因子、评分选股、回测、尾盘扫描、报告
src/research/           因子研究、组合优化、专项研究
src/trading/            信号引擎、模拟账户、风控、调度
scripts/                CLI 入口和定时任务入口
tests/                  pytest 测试
data/                   本地缓存和研究数据
reports/                回测、选股、TimesFM、监控等输出
frontend/               Vue + ECharts 后台控制台
```

## Web 后台

第一期 Web 后台采用 FastAPI + Vue 3 + ECharts：

- `src.web.backend.app`：FastAPI 应用工厂，提供健康检查、数据中心、任务中心和尾盘回测 API。
- `src.web.backend.jobs`：SQLite 任务元数据存储，记录任务参数、状态、结果、错误和时间戳。
- `src.web.backend.datasets`：扫描本地 research parquet，读取 manifest、parquet metadata 和符号列表，服务数据中心页面。
- `src.web.backend.backtests`：尾盘回测 API 模型和执行器，复用现有 `BacktestEngine`、`TailSessionFactor` 和 research dataset 读取能力。
- `src.web.backend.fund_tail`：基金尾盘 Web 适配层，复用现有基金尾盘研究函数和本地 CSV 输入，提供基金池状态、最新报告读取和建议任务生成。
- `frontend/`：Vue 3 + TypeScript + Element Plus + ECharts 控制台，当前包含总览、数据中心、任务中心、尾盘回测和基金尾盘页面。

Web 层只做编排、可视化和任务状态管理，不复制策略逻辑。数据中心只读取本地 `data/research/*.parquet` 的摘要和符号列表，不负责联网下载。尾盘回测页面通过 `dataset_id` 选择数据集，由后端在配置的 `dataset_root` 下解析成本地路径，前端不直接依赖文件系统布局。基金尾盘页面通过本地 `data/fund_tail/*.csv` 生成报告，不在 Web 请求里执行联网下载。耗时任务通过 job 记录追踪；第一期支持进程内后台任务，后续可替换为独立 worker 或队列。

## 数据层

核心接口：

- `src.data.base.DataSource`：数据源协议，定义日线、股票列表、实时行情和财务数据接口。
- `src.data.aggregator.DataAggregator`：多数据源聚合器，负责缓存优先、失败降级和批量读取。
- `src.data.cache.DataCache`：TTL 型 Parquet 缓存，主要服务联网数据获取。
- `src.data.research_dataset`：把 per-symbol cache 合并为稳定的 research parquet 数据集。
- `src.data.bar_repository.CacheBarRepository`：不检查 TTL 的本地 bars 读取仓库，用于离线回测、live 股票池和市场宽度计算。

推荐边界：

- 联网数据获取走 `DataAggregator`。
- 离线研究和可复现实验优先走 research parquet。
- 需要直接读取本地 bars cache 时走 `CacheBarRepository`，不要在脚本里重复写 parquet 扫描逻辑。

## 策略评分与选股

核心接口：

- `src.strategy.base.Factor`：因子抽象。输入 MultiIndex `(date, symbol)` bars，输出同索引单列因子值。
- `src.strategy.scoring.FactorScoreEngine`：统一的因子组合评分服务。
- `src.strategy.scoring.Selection`：标准选股结果，包含 `date`、`rank`、`symbol`、`score`。

评分流程：

```text
bars + factors + weights
  -> factor.compute()
  -> min raw score filter
  -> date-level rank normalization
  -> weighted composite score
  -> daily top-N Selection
```

现在以下路径复用同一个评分契约：

- `BacktestEngine._compute_composite_score`
- `SignalEngine._compute_composite`
- `strategy.tail_session.history.build_historical_selection_rows`

这层是后续接 Qlib 的关键边界。Qlib 模型只要产出 `(date, symbol, score)`，就可以适配为 `Factor` 或直接转成 `Selection`，下游回测、报告和模拟交易无需知道分数来自 Qlib 还是本地因子。

## 回测层

核心模块：

- `src.strategy.engine.backtest.BacktestEngine`
- `src.strategy.engine.backtest.BacktestResult`
- `src.strategy.execution.broker.SimulatedBroker`
- `src.strategy.execution.order.Order`

当前回测模型：

1. 按交易日遍历 bars。
2. 到调仓日时，用历史 bars 计算组合分数。
3. 选 top-N。
4. 卖出不在 top-N 的持仓。
5. 用剩余现金等权买入新选股。
6. 记录每日净值、收益、持仓和成交。

注意事项：

- 当前回测偏“日频因子调仓”，不是完整事件撮合系统。
- `equal_weight=False` 目前没有独立权重逻辑，仍等同等权。
- 若后续做 Qlib 融合，建议先把 Qlib 预测分数接入该回测路径，避免同时引入 Qlib 回测器和当前回测器造成口径分裂。

## 尾盘策略

尾盘策略包含两类语义：

- 日频历史研究：`TailSessionFactor` 用日线 close、volume、MA、市场宽度等条件构造尾盘风格分数。
- 分钟级 live 扫描：`IntradayScanner` 用 5 分钟 bars 判断尾盘量价确认。

相关模块：

- `src.strategy.factors.tail_session.TailSessionFactor`
- `src.strategy.scanner.IntradayScanner`
- `src.strategy.executor.RealTimeExecutor`
- `src.strategy.reports`
- `src.strategy.tail_session.backtest`
- `src.strategy.tail_session.history`
- `src.strategy.tail_session.live`

建议保持这两类语义分开：历史日频因子用于研究和回测；分钟级 scanner 用于模拟交易日内选股。二者可以共享报告和选股排序，但不要假设它们是完全等价的信号。

## 交易与风控

核心模块：

- `src.core.broker_base.BaseBroker`：买卖、持仓、T+1、费用、组合市值的共享逻辑。
- `src.strategy.execution.broker.SimulatedBroker`：回测 Broker，支持 `Order`/`OrderResult` 和涨跌停校验。
- `src.trading.paper_account.PaperAccount`：持久化纸面账户。
- `src.trading.risk_manager.RiskManager`：实时风控。
- `src.trading.scheduler.TradingScheduler`：交易日和交易时段判断。

当前边界：

- 回测使用 `SimulatedBroker.submit_order()`。
- live 模拟交易使用 `PaperAccount.buy/sell()`。
- 两者共享 `BaseBroker`，但订单接口尚未完全统一。

后续优化方向是定义更小的 `OrderExecutor`/`PortfolioAccount` 协议，让策略执行层不关心底层账户是回测还是纸面账户。

## CLI 与工作流

主要入口：

- `scripts/download_history.py`：下载历史数据到 cache。
- `scripts/build_research_dataset.py`：构建 research parquet。
- `scripts/build_liquid_research_dataset.py`：按流动性构建研究池。
- `scripts/run_tail_session_backtest.py`：尾盘日频策略回测和历史选股报告。
- `scripts/evaluate_tail_session_grid.py`：尾盘参数网格评估。
- `scripts/run_tail_session_live.py`：尾盘 live 扫描和纸面交易。
- `scripts/compute_timesfm_features.py`：TimesFM 预测因子实验。

当前优化原则：

- `scripts/` 保留为 CLI 入口。
- 可复用业务逻辑下沉到 `src/`。当前尾盘回测的数据加载、输出写入位于 `src.strategy.tail_session.backtest`；live 扫描的股票池解析、市场宽度和报价兜底位于 `src.strategy.tail_session.live`。
- 新增工作流不要直接扫描 parquet 文件或直接调用私有回测方法，应使用 `CacheBarRepository` 和 `FactorScoreEngine`。

## 测试结构

测试覆盖当前主要模块：

- `tests/test_data/`
- `tests/test_strategy/`
- `tests/test_research/`
- `tests/test_trading/`
- `tests/test_scripts/`

架构重构时优先增加面向契约的测试，例如：

- 数据仓库返回标准 MultiIndex bars。
- 评分引擎对 raw score、rank、top-N 的处理稳定。
- CLI 包装函数调用 src 层业务模块后仍保持输出兼容。

## Qlib 融合建议

建议分三步接入：

1. 数据适配：从 research parquet 导出 Qlib 所需数据格式，或提供 Qlib 数据生成脚本。
2. 分数适配：把 Qlib 模型预测结果转成项目内标准 `(date, symbol, score)`。
3. 策略验证：把 Qlib 分数接入 `FactorScoreEngine` 或直接生成 `Selection`，用当前 `BacktestEngine` 和报告体系验证。

不建议第一步就替换以下模块：

- `DataAggregator`
- `PaperAccount`
- `RiskManager`
- `TradingScheduler`
- 尾盘分钟级 `IntradayScanner`

这些模块包含项目的 A 股工程约束，Qlib 更适合作为研究和模型预测后端。
