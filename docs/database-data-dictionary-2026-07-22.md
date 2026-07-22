# 数据库数据字典（截至 2026-07-22）

本文以当前生产 ClickHouse 实例的实际表结构为准，记录每个数据库对象的用途与字段中文含义。它不是接口契约：字段、引擎和读取口径发生变更时，应同时更新本文。

## 阅读约定

- **正式读取入口**：新功能和策略允许依赖的表或视图。
- **审计/运行表**：用于判断任务、数据质量和发布是否可信，不直接作为策略行情输入。
- **历史备份/旧表**：仅用于追溯或人工恢复，禁止新的业务代码继续写入或读取。
- `FINAL`：读取 `ReplacingMergeTree` 表时通常应使用 `FINAL`，以消除尚未合并的历史版本。
- 时间字段均为服务器时区的 ClickHouse 时间；`UInt8` 的业务布尔值中，通常 `1=是/真`、`0=否/假`。
- 通用行情字段：`open/high/low/close` 为开高低收价格；`volume` 为成交量；`amount` 为成交额；`symbol` 为带市场后缀的证券代码（如 `000001.SZ`）。

## 一、正式原始行情与证券主数据

### `stocks`（正式读取入口）

用途：项目通用股票主数据。

| 字段 | 含义 |
|---|---|
| `symbol` | 证券代码。 |
| `name` | 证券简称。 |
| `industry` | 所属行业。 |
| `market` | 市场标识。 |
| `list_date` | 上市日期，字符串格式。 |
| `updated_at` | 本记录最后更新时间。 |

### `daily_kline`（正式读取入口）

用途：既有日线行情主表；历史策略仍可能使用。字段：`symbol`（证券代码）、`date`（交易日）、`open/high/low/close`（开高低收）、`volume`（成交量）、`amount`（成交额）、`amplitude`（振幅）、`pct_change`（涨跌幅）、`change`（涨跌额）、`turnover`（换手率）。

### `minute5_kline`（正式读取入口）

用途：既有 5 分钟 K 线主表。字段：`symbol`（证券代码）、`datetime`（K 线结束时间）、`open/high/low/close`（开高低收）、`volume`（成交量）、`amount`（成交额）、`updated_at`（最后写入时间）。

### `index_daily`（正式读取入口）

用途：指数日线。字段：`code`（指数代码）、`date`（交易日）、`open/high/low/close`（开高低收）、`volume`（成交量）、`amount`（成交额）、`pct_change`（涨跌幅）。

### `financials`（正式读取入口）

用途：证券财务与估值指标快照。

字段：`symbol`（证券代码）、`report_date`（报告期）、`pe/pb/ps`（市盈率、市净率、市销率）、`roe`（净资产收益率）、`revenue`（营业收入）、`net_profit`（净利润）、`gross_margin`（毛利率）、`debt_ratio`（资产负债率）。

### `trade_calendar`（正式读取入口）

用途：交易日历。字段：`date`（自然日期）、`is_open`（是否开市）。

## 二、Mootdx 原始数据层

### `mootdx_stock_catalog`（正式读取入口）

用途：Mootdx 股票目录的权威快照，也是同步股票池的来源。

字段：`captured_at`（目录抓取时间）、`market`（市场数字编码）、`symbol`（带市场后缀代码）、`code`（裸代码）、`name`（简称）、`is_st`（是否 ST）、`source`（来源标识）、`raw_json`（原始响应）、`is_active`（当前是否仍在目录中）、`missing_catalog_runs`（连续未出现的目录同步次数）、`last_seen_at`（最近一次在目录中出现的时间）、`deactivated_at`（失效时间）、`reactivated_at`（恢复活跃时间）。

### `mootdx_stock_kline`（正式读取入口）

用途：Mootdx 原始 K 线事实表，研究复权层的日线输入；可存日线及不同分钟频率。

字段：`datetime`（K 线时间）、`trade_date`（交易日）、`frequency`（频率，如 `daily`、`5m`）、`symbol`（证券代码）、`open/high/low/close`（开高低收）、`volume`（成交量）、`amount`（成交额）、`source`（数据源）、`ingested_at`（写入时间）、`raw_json`（原始响应）、`ingest_seq`（输入批次序号；`0` 为迁移/历史基线）。

### `mootdx_index_kline`（正式读取入口）

用途：Mootdx 指数 K 线事实表。

字段：`datetime`（K 线时间）、`trade_date`（交易日）、`frequency`（频率）、`symbol`（指数代码）、`open/high/low/close`（开高低收）、`volume`（成交量）、`amount`（成交额）、`up_count/down_count`（上涨/下跌家数，如源端提供）、`source`（来源）、`ingested_at`（写入时间）、`raw_json`（原始响应）。

### `mootdx_quote_snapshots`（正式读取入口）

用途：Mootdx 原始实时行情快照。

字段：`snapshot_at`（采集时间）、`symbol`（证券代码）、`price`（最新价）、`open`（今开）、`prev_close`（昨收）、`high/low`（最高/最低）、`volume`（成交量）、`amount`（成交额）、`change_pct`（涨跌幅）、`quote_time`（源端行情时间）、`source`（来源）、`raw_json`（原始响应）。

### `mootdx_minutes`（正式读取入口）

用途：逐笔/分时明细的原始行。

字段：`captured_at`（采集时间）、`trade_date`（交易日）、`symbol`（证券代码）、`source_method`（源端请求方法）、`row_index`（源返回行号）、`price`（成交价）、`volume`（成交量）、`raw_json`（原始行）。

### `mootdx_transactions`（正式读取入口）

用途：Mootdx 成交明细原始行。

字段：`captured_at`（采集时间）、`trade_date`（交易日，可空）、`symbol`（证券代码）、`source_method`（请求方法）、`row_index`（源返回行号）、`price`（成交价）、`volume`（成交量）、`amount`（成交额）、`raw_json`（原始行）。

### `mootdx_finance_snapshot`（正式读取入口）

用途：Mootdx 财务摘要快照。

字段：`captured_at`（采集时间）、`symbol`（证券代码）、`updated_date`（源数据更新日期）、`ipo_date`（上市日期）、`industry`（行业）、`liutongguben`（流通股本）、`zongguben`（总股本）、`zongzichan`（总资产）、`jingzichan`（净资产）、`zhuyingshouru`（主营收入）、`jinglirun`（净利润）、`meigujingzichan`（每股净资产）、`source`（来源）、`raw_json`（原始响应）。

### `mootdx_f10_catalog` 与 `mootdx_f10_detail`（正式读取入口）

用途：F10 信息目录与正文。

`mootdx_f10_catalog` 字段：`captured_at`（抓取时间）、`symbol`（证券代码）、`title`（条目标题）、`raw_json`（目录原始响应）。

`mootdx_f10_detail` 字段：`captured_at`（抓取时间）、`symbol`（证券代码）、`title`（正文标题）、`content`（正文内容）。

### `mootdx_affair_files`（正式读取入口）

用途：Mootdx 公告/事务文件清单快照。字段：`captured_at`（抓取时间）、`filename`（文件名）、`hash`（文件哈希）、`filesize`（字节数）、`raw_json`（原始元数据）。

## 三、Mootdx 同步、质量与覆盖审计

### `mootdx_ingestion_runs`（审计/运行表）

用途：所有可作为研究输入的 Mootdx 批次总账；`ingest_seq` 是复权发布的输入边界。

字段：`ingest_seq`（全局递增批次序号）、`run_id`（同步运行 ID）、`task_key`（任务类型）、`started_at/finished_at`（开始/结束时间）、`status`（`succeeded`、`failed` 等）、`row_count`（写入行数）、`error`（错误信息）、`version`（同一批次审计行版本）。

### `mootdx_sync_runs`（审计/运行表）

用途：Mootdx 同步任务的完整运行日志。

字段：`run_id`（运行 ID）、`task_key`（任务类型）、`started_at/finished_at`（起止时间）、`status`（结果状态）、`params_json`（入参 JSON）、`result_json`（结果 JSON）、`error`（错误详情）、`source_version`（同步程序/源版本）。

### `mootdx_symbol_data_status`（审计/运行表）

用途：逐证券、逐数据类型的可用性与失败退避状态。

字段：`symbol`（证券代码）、`data_kind`（数据种类）、`status`（当前状态）、`reason`（状态原因）、`first_seen_at`（首次记录时间）、`last_checked_at`（最近检查时间）、`consecutive_failures`（连续失败次数）、`last_success_at`（最近成功时间）、`source`（来源）、`raw_json`（附加诊断信息）。

### `mootdx_daily_gap_verifications`（审计/运行表）

用途：日线缺口的逐证券核验结果。

字段：`verified_at`（核验时间）、`run_id`（任务运行 ID）、`symbol`（证券代码）、`frequency`（频率）、`trade_date`（核验交易日）、`verdict`（结论，如有数据/确无数据/失败）、`source`（核验来源）、`details_json`（诊断详情）。

### `mootdx_catalog_change_events`（审计/运行表）

用途：股票目录新增、移除、ST 状态变化等事件流。

字段：`event_at`（事件时间）、`symbol`（证券代码）、`event_type`（事件类型）、`previous_json/current_json`（变更前/后快照）、`run_id`（目录同步运行 ID）、`source`（来源）。

### `mootdx_xdxr_symbol_observations`（审计/运行表）

用途：每轮 XDXR 全量抓取中，每只股票的观测结果；用于区分“无事件”与“未成功请求”。

字段：`ingest_seq`（所属输入批次）、`symbol`（证券代码）、`observed_at`（观测时间）、`status`（成功/空结果/失败）、`event_count`（本次事件数）、`event_set_hash`（事件集合哈希）、`request_ms/parse_ms`（请求/解析耗时毫秒）、`error`（错误信息）。

### `mootdx_xdxr_symbol_runs`（审计/运行表）

用途：按同步运行保存的 XDXR 单证券性能与错误审计。

字段：`run_id`（同步运行 ID）、`symbol`（证券代码）、`requested_at`（请求时间）、`status`（结果状态）、`event_rows`（写入事件行数）、`request_ms/parse_ms`（请求/解析耗时）、`error`（错误）、`raw_columns`（源端原始列名）。

## 四、XDXR 三层除权除息数据

### `mootdx_xdxr_event_versions`（正式读取入口：版本事实层）

用途：不可变的 XDXR 事件版本事实；同一事件在不同 `ingest_seq` 的内容变化均被保留。复权计算应以此表连接成功的 `mootdx_ingestion_runs`，并按输入边界取版本。

字段：`ingest_seq`（观测批次序号）、`symbol`（证券代码）、`event_date`（除权除息日期）、`category`（源端事件类别）、`name`（事件名称）、`fenhong`（每股现金分红）、`peigujia`（配股价）、`songzhuangu`（送转股比例）、`peigu`（配股比例）、`suogu`（缩股比例）、`panqianliutong/panhouliutong`（除权前/后流通股本）、`qianzongguben/houzongguben`（除权前/后总股本）、`content_hash`（事件内容哈希）、`raw_json`（源端原始记录）、`observed_at`（观测时间）、`migration_baseline`（是否迁移基线）。

### `mootdx_xdxr_current`（正式读取入口：当前投影视图）

用途：`mootdx_xdxr_event_versions` 的“当前最新事件”投影，适合运营查询；不适合作为可回放研究快照的唯一依据。

字段与版本事实层相同，但不含 `migration_baseline`；`ingest_seq` 表示该事件当前最新版本来自哪个输入批次。

### `mootdx_daily_xdxr_events_view`（正式读取入口：日线关联视图）

用途：将 Mootdx 原始日线和当前 XDXR 事件按证券、交易日关联，供数据质量排查和事件日观察；不产生复权价。

字段：`datetime/trade_date/frequency/symbol`（日线定位）、`open/high/low/close/volume/amount`（原始日线）、`source/ingested_at`（日线来源与写入时间）、`has_xdxr_event`（当日是否有任意事件）、`xdxr_event_count`（事件数）、`price_adjustment_event_count`（影响价格事件数）、`has_price_adjustment_event`（是否存在影响价格事件）、`event_categories/event_names`（类别/名称数组）、`fenhong_sum/songzhuangu_sum/peigu_sum`（当日事件字段合计）。

### `mootdx_xdxr`（旧表，待清理）

用途：旧版直接保存“当前 XDXR”的物理表。当前实际数据库中仍存在；新代码不得以它作为 XDXR 正式输入，应迁移到 `mootdx_xdxr_event_versions` 与 `mootdx_xdxr_current`。

字段：`symbol`（证券代码）、`event_date`（事件日）、`category`（类别）、`name`（名称）、`fenhong`（现金分红）、`peigujia`（配股价）、`songzhuangu`（送转比例）、`peigu`（配股比例）、`suogu`（缩股比例）、`panqianliutong/panhouliutong`（除权前/后流通股本）、`qianzongguben/houzongguben`（除权前/后总股本）、`ingested_at`（写入时间）、`raw_json`（原始记录）。

### `xdxr_info`（旧表，历史兼容）

用途：早期除权信息结构，禁止新研究逻辑读取。

字段：`symbol`（证券代码）、`year/month/day`（事件日期拆分）、`category`（类别）、`fenhong`（现金分红）、`songzhuangu`（送转比例）、`peigu`（配股比例）、`suogu`（缩股比例）、`ex_date`（由年月日物化生成的事件日期）、`updated_at`（更新时间）。

## 五、研究复权数据层

### `research_adjustment_runs`（正式读取入口：发布指针）

用途：研究复权快照的版本发布记录。消费者必须先选取 `status='published'` 的最新 `run_id`，再按该 `run_id` 读取下列三张结果表。

字段：`run_id`（快照版本 ID）、`formula_version`（复权公式版本）、`status`（发布状态）、`published_at`（发布时间）、`input_watermark`（旧时间水位，兼容保留）、`input_ingest_seq`（本快照使用的最高成功输入批次）。

### `research_adjustment_raw_bars`（正式读取入口）

用途：某个研究复权快照固定下来的原始日线副本；用于与复权因子同版本联查，避免上游后来更新改变回测输入。

字段：`run_id`（快照版本）、`formula_version`（公式版本）、`symbol`（证券代码）、`trade_date`（交易日）、`open/high/low/close`（未复权开高低收）、`volume/amount`（成交量/成交额）、`source_ingested_at`（上游原始日线写入时间）、`computed_at`（快照计算时间）。

### `research_adjustment_events`（正式读取入口）

用途：某个快照内 XDXR 事件的解析、公式输入和可用性校验结果。

字段：`run_id`（快照版本）、`formula_version`（公式版本）、`symbol`（证券代码）、`event_date`（事件日）、`category`（事件类别）、`event_name`（事件名）、`validation_status`（校验状态）、`ratio`（计算出的价格调整比率）、`theoretical_price`（理论除权价）、`pre_close`（事件日前最近收盘价）、`ex_close`（事件日收盘价）、`validation_error`（理论价与实际价误差）、`event_payload`（事件原始/计算载荷 JSON）、`computed_at`（计算时间）。

### `research_daily_adjustment_factors`（正式读取入口）

用途：每日前复权/后复权因子，是生成研究复权价格的正式因子表。

字段：`run_id`（快照版本）、`formula_version`（公式版本）、`symbol`（证券代码）、`trade_date`（交易日）、`forward_factor`（前复权因子）、`backward_factor`（后复权因子）、`eligible_event_count`（纳入计算的事件数）、`excluded_event_count`（未纳入事件数）、`quality_status`（当日因子质量状态）、`input_snapshot_at`（输入时间水位，兼容保留）、`computed_at`（计算时间）。

### `research_adjustment_refresh_audits`（审计/运行表）

用途：研究复权刷新门禁的审计流水。可解释为什么发布、空跑、阻断或失败。

字段：`refresh_id`（刷新尝试 ID）、`attempted_at`（尝试时间）、`previous_run_id`（刷新前已发布版本）、`previous_input_ingest_seq`（刷新前输入边界）、`decision`（`published`、`noop`、`blocked`、`failed`）、`block_reason`（阻断或失败原因）、`upstream_status`（新增上游任务状态 JSON）、`published_run_id`（成功时的新版本 ID）、`details_json`（构建返回详情 JSON）。

## 六、数据运维与数据质量

### `data_ops_task_config`（正式读取入口：任务配置）

用途：Data Ops 调度任务配置。

字段：`task_key`（任务键）、`enabled`（是否启用）、`schedule_kind`（调度类别）、`schedule_config`（调度参数 JSON）、`max_runtime_seconds`（最长运行秒数）、`stale_after_seconds`（心跳超时秒数）、`manual_trigger`（是否请求手工触发）、`manual_triggered_at`（请求时间）、`updated_at`（配置更新时间）。

### `data_ops_task_runs`（审计/运行表）

用途：Data Ops 任务的每次运行记录。

字段：`run_id`（运行 ID）、`task_key`（任务键）、`status`（运行状态）、`started_at/finished_at`（起止时间）、`duration_seconds`（耗时秒数）、`result`（结果 JSON/文本）、`error`（错误信息）。

### `data_ops_task_heartbeats`（审计/运行表）

用途：调度 Runner 心跳与任务占用状态。

字段：`runner_id`（执行器 ID）、`task_key`（任务键）、`heartbeat_at`（心跳时间）、`status`（运行状态）、`message`（进度或状态说明）。

### `data_quality_calendar`（正式读取入口：质量总览）

用途：按交易日、数据源汇总覆盖率和缺口的质量日历。

字段：`trade_date`（交易日）、`source_key/source_name`（来源键/名称）、`status`（质量状态）、`latest_time`（最新数据时间）、`expected_symbols/covered_symbols/coverage_ratio`（应有证券数、已覆盖数、覆盖率）、`expected_buckets/observed_buckets/missing_buckets`（应有/已观测/缺失时间桶数）、`duplicate_rows`（重复行数）、`max_gap_seconds`（最大时间缺口秒数）、`repairability`（可修复性判断）、`summary`（摘要）、`details`（详情）、`checked_at`（检查时间）。

### `data_source_health`（审计/运行表）

用途：数据源健康检查流水。

字段：`checked_at`（检查时间）、`check_name`（检查项）、`status`（状态）、`ok`（是否通过）、`message`（摘要）、`details`（详细信息）。

### `stock_data_readiness`（正式读取入口）

用途：按证券和数据维度计算研究可用性。

字段：`symbol/name/market/board`（证券标识、名称、市场、板块）、`dimension`（数据维度，如日线/5 分钟线）、`window_start/window_end`（检查窗口）、`query_trade_days`（窗口交易日数）、`first_date/latest_date`（最早/最新数据日）、`covered_days/missing_days/checked_days`（覆盖/缺失/检查天数）、`status`（可用性状态）、`repair_supported`（是否支持修复）、`repair_attempts`（修复尝试次数）、`last_repair_error`（最近修复错误）、`computed_at`（计算时间）。

### `stock_data_readiness_gaps`（正式读取入口）

用途：研究可用性检查发现的逐证券、逐日期缺口。

字段：`symbol`（证券代码）、`dimension`（数据维度）、`trade_date`（缺失交易日）、`reason`（缺失原因）、`repair_attempts`（修复次数）、`last_repair_error`（最近错误）、`computed_at`（计算时间）。

### `stock_research_status`（正式读取入口）

用途：面向研究和选股的股票最终状态标签。

字段：`symbol/name/market/board`（证券标识）、`is_st`（是否 ST）、`is_delisting_period`（是否退市整理期）、`is_delisted`（是否已退市）、`list_date`（上市日期）、`latest_trade_date`（最新交易日）、`research_eligible`（是否允许研究）、`data_ready`（数据是否齐备）、`excluded_reasons`（排除原因）、`data_gap_reasons`（缺口原因）、`daily_latest_date/daily_missing`（日线最新日/是否缺失）、`minute5_trade_date/minute5_missing`（5 分钟数据日期/是否缺失）、`source`（状态来源）、`checked_at`（检查时间）。

### `stock_universe_profiles`（正式读取入口）

用途：按日期输出可用股票池、上市时长与流动性标签。

字段：`symbol`（证券代码）、`as_of_date`（生效日期）、`computed_at`（计算时间）、`rule_version`（规则版本）、`market`（市场）、`is_st`（是否 ST）、`list_date`（上市日期）、`listing_age_days`（上市天数）、`catalog_valid`（目录是否有效）、`latest_daily_valid`（最新日线是否有效）、`recent_20d_bar_count/recent_20d_trading_days`（近 20 日 K 线数/交易日数）、`recent_20d_avg_amount/recent_20d_median_amount`（近 20 日平均/中位成交额）、`recent_20d_zero_volume_days`（近 20 日零成交天数）、`liquidity_qualified`（是否满足流动性门槛）、`liquidity_level`（流动性等级）、`universe_eligible`（是否进入股票池）、`exclusion_reasons`（排除原因数组）。

## 七、实时行情快照与分钟源测试

### `stock_quote_snapshots`（正式读取入口）

用途：项目标准化实时股票快照。

字段：`snapshot_at`（采集时间）、`symbol/name`（证券代码/名称）、`price`（最新价）、`change_pct`（涨跌幅）、`volume/amount`（成交量/成交额）、`turnover_pct`（换手率）、`pe_ttm/pb`（市盈率 TTM/市净率）、`mcap/float_mcap`（总/流通市值）、`limit_up/limit_down`（涨停/跌停价）、`source`（来源）、`quote_time`（源端行情时间）。

### `stock_quote_snapshots_1m` 与 `stock_quote_snapshots_5m`（正式读取入口）

用途：由实时快照聚合得到的 1 分钟、5 分钟行情桶。

共同字段：`bucket_start`（时间桶起点）、`symbol/name`（证券代码/名称）、`open_price/high_price/low_price/close_price`（桶内开高低收）、`change_pct`（涨跌幅）、`volume/amount`（成交量/成交额）、`turnover_pct`（换手率）、`pe_ttm/pb`（估值）、`mcap/float_mcap`（市值）、`limit_up/limit_down`（涨跌停价）、`source`（来源）、`quote_time`（源端行情时间）、`sample_count`（聚合样本数）、`updated_at`（更新时间）。

### `minute5_source_quality`（审计/运行表）

用途：5 分钟数据源的内容质量检测结果。

字段：`test_id/test_time`（测试 ID/时间）、`source`（数据源）、`symbol`（证券代码）、`trade_date`（交易日）、`bars_count`（K 线数）、`has_amount`（是否有成交额）、`amount_zero_ratio`（成交额为零比例）、`open_outside_range`（开盘价越界次数）、`high_lt_low`（最高低于最低次数）、`volume_negative/price_negative`（负成交量/负价格次数）、`duplicate_bars`（重复 K 线数）、`avg_latency_ms`（平均延迟毫秒）。

### `minute5_source_stability`（审计/运行表）

用途：5 分钟数据源的请求稳定性压测结果。

字段：`test_id/test_time`（测试 ID/时间）、`source`（数据源）、`symbol`（证券代码）、`datalen`（请求数据长度）、`request_order`（请求序号）、`http_status`（HTTP 状态码）、`success`（是否成功）、`bars_returned`（返回 K 线数）、`latency_ms`（请求延迟毫秒）、`error_message`（错误消息）。

## 八、选股、尾盘与基金功能表

### `screener_results`（正式读取入口）

用途：网格/技术指标选股结果。

字段：`id`（结果 UUID）、`screen_time`（筛选时间）、`symbol/name/industry`（证券标识）、`current_price`（现价）、`adx`（ADX 指标）、`range_ratio`（区间比例）、`volatility`（波动率）、`avg_volume`（平均成交量）、`suggested_upper/suggested_lower`（建议网格上/下界）、`grid_size`（网格大小）。

### `late_session_results`（正式读取入口）

用途：尾盘选股计算结果。

字段：`symbol/name/industry`（证券标识）、`current_price/pct_change/turnover`（现价、涨跌幅、换手率）、`late_volume_ratio`（尾盘量比）、`late_price_change`（尾盘价格变化）、`late_close_position`（收盘位置）、`trend_score`（趋势分）、`rsi_14`（14 日 RSI）、`macd_histogram`（MACD 柱）、`momentum_score`（动量分）、`total_score`（总分）、`screen_time`（筛选时间）。

### `tail_selection_signals`（正式读取入口）

用途：尾盘策略选股信号及筛选过程记录。

字段：`job_id`（任务 ID）、`trade_date`（信号日）、`mode`（策略模式）、`rank`（排序）、`symbol`（证券代码）、`status`（状态）、`filter_reason`（过滤原因）、`strength`（信号强度）、`last_price`（最新价）、`volume_ratio`（量比）、`tail_return`（尾盘收益）、`v2_score/v2_layer/v2_action`（V2 评分、层级、动作）、`updated_at`（更新时间）。

### `tail_signal_outcomes`（正式读取入口）

用途：尾盘信号的后续表现，用于回测与评估。

字段：`signal_date`（信号日）、`outcome_date`（结果日）、`symbol`（证券代码）、`signal_close`（信号日收盘价）、`next_open/next_close/next_high/next_low`（下一交易日开收高低）、`open_return/close_return/max_return/min_return`（开盘、收盘、最大、最小收益率）。

### `fund_watchlist`（正式读取入口）

用途：基金关注列表与持仓辅助信息。

字段：`fund_code/fund_name`（基金代码/名称）、`status`（状态）、`priority`（优先级）、`fund_type`（基金类型）、`enabled`（是否启用）、`include_in_advice`（是否纳入建议）、`position_cost`（持仓成本）、`position_amount`（持仓数量/金额，按业务约定）、`position_return_pct`（持仓收益率）、`note`（备注）、`created_at/updated_at`（创建/更新时间）。

### `fund_tail_nav`、`fund_tail_proxy`、`fund_tail_benchmark`（正式读取入口）

用途：基金尾盘建议所需的净值、代理资产和基准数据。

`fund_tail_nav`：`fund_code/fund_name`（基金标识）、`date`（净值日期）、`close`（单位净值或收盘价）、`updated_at`（更新时间）。

`fund_tail_proxy`：`fund_code`（基金代码）、`proxy_provider/proxy_code`（代理数据源/代码）、`date`（日期）、`close`（代理资产收盘价）、`volume`（成交量）、`updated_at`（更新时间）。

`fund_tail_benchmark`：`date`（日期）、`close`（基准收盘价）、`volume`（成交量）、`updated_at`（更新时间）。

### `fund_tail_advice_runs`（正式读取入口）

用途：每日基金尾盘建议的可追溯发布记录。

字段：`trade_date`（建议交易日）、`rows_json`（建议明细 JSON）、`markdown`（渲染文本）、`data_status_json`（输入数据状态）、`metadata_json`（运行元数据）、`updated_at`（更新时间）。

## 九、历史备份与恢复控制表

### `daily_kline_backup_20260623_fix`（历史备份）

用途：2026-06-23 日线修复前备份，禁止策略读取。字段与 `daily_kline` 完全一致：`symbol/date/open/high/low/close/volume/amount/amplitude/pct_change/change/turnover`，分别表示证券、交易日、开高低收、成交量额、振幅、涨跌幅、涨跌额和换手率。

### `minute5_kline_backup_20260617_manual`（历史备份）

用途：2026-06-17 手工操作前 5 分钟 K 线备份，禁止业务读取。字段：`symbol`（证券代码）、`datetime`（K 线时间）、`open/high/low/close`（开高低收）、`volume/amount`（成交量/成交额）。

### `minute5_kline_backup_20260621_fix`（历史备份）

用途：2026-06-21 修复前 5 分钟 K 线备份，禁止业务读取。字段：`symbol/datetime/open/high/low/close/volume/amount`（含义同上）、`updated_at`（备份行更新时间）。

### `minute5_kline_backup_20260708_codex`（历史备份）

用途：2026-07-08 修复前 5 分钟 K 线备份，禁止业务读取。字段与 `minute5_kline` 完全一致：`symbol`（证券代码）、`datetime`（K 线时间）、`open/high/low/close`（开高低收）、`volume/amount`（成交量/成交额）、`updated_at`（最后更新时间）。

### `daily_kline_repair_locks`（恢复控制表）

用途：日线修复过程的日期级互斥锁，避免同日重复修复。

字段：`trade_date`（被锁定交易日）、`acquired_at`（锁获取时间）。

## 十、当前版本化复权快照核验

截至本文生成时，最新已发布研究快照为 `d26d3285-00f2-416f-a644-2f946a05ab9d`，其 `input_ingest_seq=6`。该版本包含 3,518,716 条原始日线快照、3,518,716 条复权因子、167,994 条事件校验记录，覆盖 4,997 只股票。

建议查询当前研究复权数据时遵循以下关系：

```text
research_adjustment_runs（选最新 published run_id）
  ├─ research_adjustment_raw_bars（同 run_id 的原始日线快照）
  ├─ research_daily_adjustment_factors（同 run_id 的前/后复权因子）
  └─ research_adjustment_events（同 run_id 的事件校验说明）
```
