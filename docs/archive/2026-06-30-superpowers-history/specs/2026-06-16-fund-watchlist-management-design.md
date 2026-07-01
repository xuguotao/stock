# 基金监控池管理设计

## 背景

当前基金尾盘模块的监控清单主要来自 `scripts/backtest_fund_tail_advice.py` 中的静态 `FUNDS` 配置。这个方式不方便在页面上增删基金，也无法区分已持仓、准备买入、观察中和暂停监控。用户希望把已持仓和未持仓基金统一管理，并继续服务每天尾盘加仓、建仓、暂停和减仓判断。

第一版采用 ClickHouse 作为基金池主数据源。持仓信息先手动维护，后续再扩展截图或 CSV 导入。

## 目标

- 提供一个基金监控池管理界面，支持已持仓和未持仓基金统一管理。
- 让每日基金尾盘建议默认读取“参与每日建议”的基金，而不是只依赖静态代码清单。
- 支持手动维护基础持仓字段，为后续补仓、建仓、卖出建议提供上下文。
- 保持第一版实现简单，不引入交易流水和自动成本计算。

## 非目标

- 第一版不做支付宝、券商截图识别。
- 第一版不做真实交易流水、成本自动计算、收益自动核算。
- 第一版不替代现有基金尾盘预测模型，只提供可管理的基金池输入。

## 数据模型

新增 ClickHouse 表 `fund_watchlist`，建议使用 `ReplacingMergeTree(updated_at)`。

核心字段：

- `fund_code String`：基金代码，主键维度之一。
- `fund_name String`：基金名称。
- `status String`：状态，取值为 `holding`、`candidate`、`watching`、`paused`。
- `priority String`：关注等级，取值为 `core`、`normal`、`low`。
- `fund_type String`：基金类型，取值为 `broad_index`、`consumer`、`medical`、`overseas`、`bond`、`sector`、`other`。
- `enabled UInt8`：是否启用。
- `include_in_advice UInt8`：是否参与每日尾盘建议。
- `position_cost Nullable(Float64)`：手动维护的持仓成本。
- `position_amount Nullable(Float64)`：手动维护的持仓金额。
- `position_return_pct Nullable(Float64)`：手动维护的持仓收益率。
- `note String`：计划动作或备注。
- `created_at DateTime`、`updated_at DateTime`。

状态语义：

- `holding`：已持仓，建议重点看补仓、暂停、减仓。
- `candidate`：准备买入，建议重点看是否建仓。
- `watching`：观察中，参与机会观察，可按开关决定是否进入每日建议。
- `paused`：暂停监控，默认不参与每日建议。

## 后端设计

在 `src/data/fund_tail_repository.py` 扩展基金池管理方法：

- `ensure_watchlist_table()`
- `list_watchlist()`
- `upsert_watchlist_item(item)`
- `delete_watchlist_item(fund_code)`：第一版可物理删除；如果后续需要历史保留，再改为软删除。
- `seed_watchlist_from_static_funds(fund_names, proxy_specs)`：当表为空时，用当前静态 `FUNDS` 初始化。

在 `src/web/backend/fund_tail.py` 增加适配函数和 Pydantic 请求模型：

- `FundWatchlistItemRequest`
- `list_fund_watchlist(repository)`
- `upsert_fund_watchlist_item(repository, request)`
- `delete_fund_watchlist_item(repository, code)`

在 `src/web/backend/app.py` 增加 API：

- `GET /api/fund-tail/watchlist`
- `POST /api/fund-tail/watchlist`
- `PUT /api/fund-tail/watchlist/{code}`
- `DELETE /api/fund-tail/watchlist/{code}`

每日建议接入：

- `FundTailAdviceRequest.fund_codes` 为空时，优先读取 ClickHouse `fund_watchlist` 中 `enabled=1 and include_in_advice=1 and status!='paused'` 的基金。
- 如果 watchlist 表为空，则回退到当前静态 `FUNDS`，同时可初始化表，避免页面和脚本断档。
- 如果用户显式传入 `fund_codes`，仍按传入列表执行，用于临时分析。

## 前端设计

在 `frontend/src/pages/FundTail.vue` 中新增“基金池管理”区域，保留当前建议表。

主要能力：

- 表格展示：代码、基金名称、状态、关注等级、类型、参与建议、持仓成本、持仓金额、持仓收益率、备注、数据状态。
- 筛选：全部、持有中、准备买入、观察中、暂停监控。
- 编辑：行内编辑或弹窗编辑均可，第一版优先弹窗，降低表格复杂度。
- 新增基金：输入基金代码、名称、状态、类型和是否参与建议。
- 删除基金：二次确认后删除。

建议表联动：

- 顶部“生成基金尾盘建议”默认使用参与建议的基金池。
- 管理表中 `暂停监控` 或 `不参与建议` 的基金不进入默认建议。
- 建议表可继续显示全部报告结果，但后续可增加状态筛选。

## 数据流

1. 页面加载时请求 `GET /api/fund-tail/watchlist` 和现有基金报告接口。
2. 如果 ClickHouse 基金池为空，后端从静态 `FUNDS` 初始化并返回。
3. 用户在管理界面新增或编辑基金，前端调用 upsert API。
4. 用户生成每日建议时，后端读取启用且参与建议的基金代码。
5. 建议结果继续写入现有 CSV、Markdown，并返回给页面展示。

## 错误处理

- ClickHouse 不可用：基金池 API 返回明确错误；现有报告读取不受影响。
- 新增基金代码格式错误：后端拒绝，前端提示“基金代码需为 6 位数字”。
- 重复新增：按 upsert 处理，更新原记录。
- 删除参与建议的基金：前端二次确认。
- watchlist 为空：自动初始化静态清单，避免空白。

## 测试计划

后端测试：

- ClickHouse repository 能创建、读取、更新、删除 watchlist 项。
- watchlist 为空时可从静态 `FUNDS` 初始化。
- 每日建议在未传 `fund_codes` 时读取参与建议的基金。
- `paused` 或 `include_in_advice=0` 的基金不会进入默认建议。

前端测试：

- 基金尾盘页面包含基金池管理区域。
- 状态、关注等级、类型、参与建议字段可见。
- 生成建议使用默认基金池逻辑。

回归测试：

- 现有基金尾盘报告读取不受影响。
- 现有 `fund_codes` 显式传参仍可运行。
- `pytest -q` 和 `npm run build` 通过。
