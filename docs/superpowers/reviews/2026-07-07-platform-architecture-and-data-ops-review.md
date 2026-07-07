# 量化平台现状评审记录

日期：2026-07-07

## 背景

本次评审目标是快速理解当前 A 股量化平台的系统状态，为后续建设和优化确定优先级。评审范围包括后端数据层、独立数据任务、尾盘策略链路、Web 控制台、前端构建和现有测试。

本轮没有改动业务代码，只做代码阅读、局部运行验证和风险归类。

## 当前系统判断

项目已经从早期量化脚本演进为一个包含数据运维、策略研究、模拟交易和 Web 控制台的完整平台。

当前主线比较清楚：

- ClickHouse 是主数据仓，承载股票主数据、日线、分钟线、实时快照、基金尾盘数据和质量快照。
- `src/data_ops` 是独立数据任务执行面，目标是脱离 Web 后台长期运行。
- FastAPI + Vue 控制台是控制面，负责查看状态、触发任务、展示策略结果。
- 尾盘策略、基金尾盘、数据中心和任务中心是当前最活跃的业务模块。

## 验证记录

已执行的快速验证：

```bash
python -m compileall -q src scripts
python -m pytest tests/test_data_ops tests/test_strategy/test_scoring.py tests/test_strategy/test_intraday_scanner.py tests/test_web/test_health_api.py -q
cd frontend && npm run build
```

结果：

- Python 编译通过。
- 后端重点测试通过，47 个测试全部通过。
- 前端生产构建通过。
- 前端构建存在 Vite chunk 体积警告，暂不影响功能。

## 已确认缺陷

### 1. `xdxr_sync` 默认任务会在执行时崩溃

文件：

- `src/data_ops/handlers.py`

现象：

`xdxr_sync` 已经出现在默认数据任务配置中，但默认 handler 执行时会导入不存在的模块：

```python
from src.clickhouse.client import get_clickhouse_client
```

项目中不存在 `src/clickhouse/client.py`。实际 ClickHouse client 统一入口是：

```python
from src.data.clickhouse_source import ClickHouseStockDataSource
```

直接调用默认 handler 的结果：

```text
ModuleNotFoundError: No module named 'src.clickhouse'
```

影响：

- 独立 `data_ops` runner 一旦执行 `xdxr_sync`，该任务会直接失败。
- 除权除息数据同步无法稳定执行，会影响复权、历史价格连续性和回测口径。

建议：

- 改为复用 `ClickHouseStockDataSource()._client_instance()` 获取 ClickHouse client。
- 补充 handler 默认路径测试，避免只测试配置存在、不测试任务可执行。

优先级：P0。

## 架构债与后续优化候选

### 2. Web 后台聚合模块过大

文件：

- `src/web/backend/app.py`

问题：

`create_app` 同时装配数据中心、任务中心、尾盘策略、基金尾盘、模型训练、监控和多类后台任务。函数参数和 `app.state` 注入项很多，新增功能容易继续推高单文件复杂度。

建议方向：

- 按业务域拆分 router 和 service。
- 优先拆出 `data_ops`、`fund_tail`、`tail_session`、`ml_tail`、`datasets`。
- 保持现有 API 路径兼容，避免一次性重构影响前端。

优先级：P1。

### 3. 独立数据任务 runner 与 Web 进程内调度并存

文件：

- `src/data_ops/runner.py`
- `src/web/backend/data_ops_scheduler.py`
- `src/web/backend/app.py`

问题：

独立 `DataOpsRunner` 已经存在，但 Web 里仍保留标记为 deprecated 的进程内 `DataOpsScheduler`，同时还有直接创建 background task 的日常维护入口。

建议方向：

- 明确 Web 只做控制面：读取任务状态、修改任务配置、提交手动触发。
- 长期运行任务统一走 `src.data_ops.runner`。
- 逐步下线 Web 进程内调度入口，保留兼容状态展示。

优先级：P1。

### 4. SQLite 遗留路径尚未完全清理

文件：

- `src/data/sqlite_source.py`
- `src/data/market_enrichment_sync.py`
- `src/web/backend/data_sync.py`
- `src/web/backend/app.py`
- `src/web/backend/minute5_monitor.py`
- `src/web/backend/data_status.py`
- `scripts/sync_stock_db.py`
- `scripts/sync_minute5_kline.py`
- `scripts/sync_market_enrichment.py`

问题：

ClickHouse 已经是主库，但 Web 和脚本层仍保留 `stock_db_path`、SQLite 数据同步和旧检查逻辑。需要注意：`data/web/jobs.sqlite3` 是 Web 任务元数据，不属于应删除的旧行情库。

建议方向：

- 分阶段删除旧 SQLite 行情源和同步脚本。
- 保留或迁移 `JobStore`，不要误删 `data/web/jobs.sqlite3`。
- 清理 `stock_db_path` 幽灵参数。

优先级：P1。

### 5. `DataAggregator` 职责偏宽

文件：

- `src/data/aggregator.py`

问题：

`DataAggregator` 同时承担 ClickHouse 主源、腾讯实时源、Sina/AKShare 兜底、本地缓存、复权、日线、分钟线、实时行情和流动性排名。它作为兼容门面有价值，但策略代码很难明确知道自己依赖的是权威库、联网兜底还是本地缓存。

建议方向：

- 保留 `DataAggregator` 作为兼容入口。
- 新增或强化更明确的 repository/service 边界，例如日线研究仓库、分钟线仓库、实时快照仓库、股票池解析服务。
- 后续策略和 Web 新功能优先依赖更窄的接口。

优先级：P2。

### 6. 回测权重参数存在浅接口

文件：

- `src/strategy/engine/backtest.py`

问题：

`equal_weight=False` 当前与 `equal_weight=True` 的买入分配逻辑相同。参数名暗示支持非等权，但实际未实现。

建议方向：

- 如果短期不需要非等权，隐藏或删除该参数。
- 如果需要，明确实现按 score 权重、风险预算权重或其他可解释权重模型。

优先级：P2。

## 推荐修复顺序

1. P0：修复 `xdxr_sync` 默认 handler，并补回归测试。
2. P1：整理 Web 控制面和独立 data ops runner 的边界，逐步下线进程内 scheduler。
3. P1：制定 SQLite 行情库清理计划，分批删除旧入口和幽灵参数。
4. P2：收窄数据访问接口，减少新业务继续依赖宽泛 `DataAggregator`。
5. P2：明确回测权重语义，避免研究参数误导。

## 本轮执行范围

本轮只执行 P0：

- 修复 `xdxr_sync` 默认 handler 的错误导入。
- 增加测试覆盖默认 handler 的真实执行路径。
- 跑相关测试验证。

其余架构优化只记录，不在本轮混入。
