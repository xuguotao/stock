# Baostock 按需日线核验实施计划

> 面向后续维护人员：按任务顺序执行；每项先补充失败测试，再写最小实现并运行对应验证。

**目标：** 将 Baostock 接入 mootdx 日线缺口的按需二次核验与受控回补流程，保留完整数据来源和核验证据。

**实现方式：** `BaostockSource` 将源端返回转换为项目统一日线数据。mootdx 仅在单标的日线请求成功、但未取得目标交易日有效记录时调用核验；按日保存核验结论，有数据才写入现有日线表。质量服务在原有相邻交易日推断之前优先使用核验结论。

**技术栈：** Python 3.12+、pandas、Baostock 0.9.3、ClickHouse、FastAPI、Vue 3、pytest。

---

### 任务 1：声明并测试 Baostock 适配器边界

**涉及文件：**

- 修改：`pyproject.toml`
- 新建：`src/data/baostock_source.py`
- 新建：`tests/test_data/test_baostock_source.py`

- [x] 编写适配器失败测试：验证 `000524.SZ` 转换为 `sz.000524`、请求参数固定为日线和不复权、结果转换为标准字段，以及源端错误必须抛出异常。
- [x] 运行测试，确认在适配器模块尚不存在时因导入失败而失败。
- [x] 将 `baostock==0.9.3` 加入 `market` 可选依赖；实现代码转换、登录、查询、字段转换与 `finally` 登出。
- [x] 执行 `uv run pytest tests/test_data/test_baostock_source.py -q`，全部通过。

### 任务 2：保存日期粒度的核验证据

**涉及文件：**

- 修改：`src/data/mootdx_clickhouse_sync.py`
- 修改：`tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] 增加失败测试，要求建表逻辑创建 `mootdx_daily_gap_verifications`。
- [x] 新增表字段：`verified_at`、`run_id`、`symbol`、`frequency`、`trade_date`、`verdict`、`source`、`details_json`。
- [x] 使用 `ReplacingMergeTree(verified_at)`，主键为 `(frequency, symbol, trade_date)`，保留三年。
- [x] 为核验结论建立统一的内部行构造函数，确保请求错误、非法行数量等信息可审计。

### 任务 3：核验 mootdx 日线缺失并定向回补

**涉及文件：**

- 修改：`src/data/mootdx_clickhouse_sync.py`
- 修改：`tests/test_data/test_mootdx_clickhouse_sync.py`

- [x] 编写失败测试，覆盖三类结果：Baostock 有数据、无数据、请求异常。
- [x] 向 `sync_mootdx_offline_data` 增加可注入的 `baostock_source`，用于测试和将来替换实现。
- [x] 仅当 mootdx 没有得到有效目标日期记录时调用 Baostock；mootdx 请求异常或返回非法 OHLCV 时保留原有失败语义，不触发回补。
- [x] 对 Baostock 返回行执行同一套 OHLCV 校验；通过校验后写入 `mootdx_stock_kline`，并设置 `source='baostock'`。
- [x] 按交易日写入 `available`、`no_data` 或 `error`；将各结论数量加入 `diagnostics.stock_kline_daily.baostock`。

### 任务 4：以核验证据驱动质量分类

**涉及文件：**

- 修改：`src/web/backend/mootdx_quality.py`
- 新建：`tests/test_web/test_mootdx_quality.py`

- [x] 编写失败测试：已确认无数据的缺口应为“已知无数据”，Baostock 请求错误应为“待核验”。
- [x] 读取 `mootdx_daily_gap_verifications` 中每个标的、日期的最新结论。
- [x] 区间内所有缺失日均为 `no_data` 时判为 `known_no_data`；存在 `error` 时判为 `needs_review`；存在尚未写回的 `available` 时判为 `repair_candidate`。
- [x] 保持人工“无需回补”结论的优先级最高。

### 任务 5：补充说明并完成回归验证

**涉及文件：**

- 修改：`docs/notes/baostock-data-source.md`
- 修改：`docs/notes/mootdx-data-source.md`

- [x] 说明 Baostock 只在 mootdx 日线缺失时按需调用，不建立独立定时采集和标的池。
- [x] 说明 `available`、`no_data`、`error` 的业务含义，以及 `source='baostock'` 的血缘规则。
- [x] 执行依赖锁检查、29 项定向测试和差异检查，均通过。
