# 研究复权数据层设计

## 目标与边界

为回测、回归和因子研究提供可审计的前复权、后复权日线 OHLCV；不改变线上策略、`DataAggregator`、现有 `AdjustmentService`，也不写回原始日线或 XDXR 事实表。

原始价格、原始成交量和原始成交额始终是事实记录。复权价格、复权成交量和收益率都是带公式版本与质量状态的派生数据，研究读取必须显式选择价格口径。

## 输入与输出

输入事实表：

- `mootdx_stock_kline`：`frequency='daily'` 的原始日线 OHLCV；
- `mootdx_xdxr`：Mootdx 原始公司行为事件；
- `xdxr_info`：旧源对照证据，不作为无条件权威；
- 交易日历：定位事件日前一个实际交易日。

新增派生表：

### `research_adjustment_events`

粒度为 `symbol + event_date + category + formula_version + run_id`。保存 Mootdx 原始事件关键字段、可用的旧源对照、前收盘、理论除权价、调整率、误差和事件判定。

`validation_status` 仅允许：`approved`、`unverified`、`source_mismatch`、`missing_pre_close`、`missing_ex_date_bar`、`formula_invalid`。除 `approved` 以外的事件都不进入因子计算；空值保留为空，不转换为零。

### `research_daily_adjustment_factors`

粒度为 `symbol + trade_date + formula_version + run_id`。保存 `forward_factor`、`backward_factor`、纳入/排除的事件数、`quality_status`、输入快照时间和公式版本；不复制 OHLCV。

研究读取通过原始日线与该表关联生成 `raw_*`、`forward_*`、`backward_*` 字段。首期不建立物化复权日线大表；需要大规模回归时，由读取层按指定日期范围和版本导出 Parquet 数据集。

## 事件校验与因子计算

每个 XDXR 事件依次通过：日期有效、前一交易日收盘存在、事件日原始日线存在、字段值可计算、理论除权价与事件日价格连续性可接受、可获得旧源时的关键字段对账。失败时保留事件审计和原因，不产生调整率。

同日多事件以固定、版本化的组合顺序生成单日调整率，并保存组成事件清单。价格因子应用于开高低收；与股数变动对应的成交量使用反向因子；成交额首期保留原始事实。收益率、均线、波动率等由指定口径的价格重新计算。

前复权以最新价格为锚点，事件影响此前日期；后复权以最早价格为锚点，事件影响此后日期。因而任一被采纳事件的新增或修订都要重算该股票全部日级因子，不能只更新事件当天。

## 联动刷新与发布

新增 `research_adjustment_refresh` data-ops 任务，排在日线主同步、缺口核对和 `mootdx_xdxr_sync` 之后，默认时间为交易日 17:25。

- 新增当日日线：为受影响标的扩展因子，并复核关联事件；
- 日线回补或历史修正：重校验关联事件并重算受影响标的全部因子；
- XDXR 新增或修订：重校验并重算该标的全部因子；
- 首次部署、公式升级或系统性修复：显式全量重建。

任务从上游运行审计和 `ingested_at` 水位定位变化标的。若上游日线/XDXR 任务失败、未完成或质量不达标，派生任务标记为阻塞并保留上一版有效结果，不发布部分新结果。

每次刷新先写候选 `run_id`。只有校验和因子计算完整完成后才发布为当前研究版本；失败、中断或未通过校验的候选不覆盖上一有效版本。研究读取默认只选当前已发布版本，也可显式指定历史公式版本以重现旧研究。

## 代码边界

新增模块：

- `src/data/research_adjustment_events.py`：事件归一化、同日组合与调整率纯函数；
- `src/data/research_adjustment_validation.py`：对账、价格连续性和判定纯函数；
- `src/data/research_adjustment_store.py`：ClickHouse DDL、候选写入、版本发布和读取；
- `src/data/research_adjustment_reader.py`：研究专用复权 OHLCV 读取和 Parquet 导出；
- `scripts/build_research_adjustment_data.py`：显式全量或定向构建入口；
- `src/data_ops/mootdx_tasks.py`、`src/data_ops/handlers.py`：新增派生刷新任务。

不修改 `src/data/adjustment.py`、`src/data/adjustment_service.py`、`src/data/aggregator.py`、现有策略代码或原始同步任务的写入目标。

## 验收

- 原始四个价格字段、成交量和成交额不被复权任务写入或更新；
- 不通过校验的事件不改变任何因子；
- 一条被采纳事件的修订触发同一标的全历史因子重算；
- 上游失败时研究读取仍返回上一次发布版本，并可看到阻塞原因；
- 每个研究结果可追溯到公式版本、因子运行和事件判定；
- 既有 `DataAggregator` 与策略测试保持行为不变。
