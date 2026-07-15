# mootdx catalog 与日线数据质量页设计

## 目标

在 `Mootdx 数据源` 模块下增加 catalog 和日线两个质量详情页，使用户能查看当前统计、历史趋势、完整度、健康异常和可修复缺口。

## catalog 数据质量

- 当前概览：总数、沪深北分布、ST 数、最新时间和审计状态。
- 历史变更：新增、移除、名称变更、ST 变更按日统计。
- 变更明细：标的、事件类型、前后值、发现时间、同步运行 ID。
- 变更事件写入 `mootdx_catalog_change_events` append-only 表；不依赖会合并旧版本的 catalog 快照表回溯历史。

## 日线数据质量

- 当前概览：最新交易日覆盖数、应覆盖数、完整率、状态分布和质量异常数。
- 日期维度：近 30 个交易日的应覆盖、实际覆盖、缺失数和完整率。
- 标的维度：以 `stocks.list_date` 为缺失起点；无法取得上市日期时以该标的第一根 mootdx 日线为起点。
- 缺失明细只展示近期窗口内可处理的标的和缺失交易日，Web 操作只请求已有 data_ops 手动触发，不在 Web 进程执行外部网络同步。

## API 和页面

- `GET /api/data/mootdx/catalog-quality`：概览、按日变更和变更明细。
- `GET /api/data/mootdx/daily-quality`：概览、近 30 日完整度和缺失标的明细。
- `CatalogQuality.vue` 与 `DailyKlineQuality.vue` 通过独立路由访问，根监控页提供入口。

## 健康等级

- `healthy`：数据新鲜且完整率达到 99.5%。
- `degraded`：完整率 98%-99.5%，或存在暂态失败、质量过滤行、目录总量明显突变。
- `failed`：完整率低于 98%、目录为空或相应表不可读。
