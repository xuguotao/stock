# Baostock 数据源说明

最后验证日期：2026-07-11
项目锁定版本：`baostock==0.9.3`；本机 conda `base` 已安装包元数据版本为 `0.9.1`（包内版本字符串为 `00.9.10`）。

Baostock 是通过 Python SDK 访问的历史证券与宏观数据源。它适合作为 `stock_kline_daily` 缺口的**按日期二次核验源**：可以按单标的和明确的起止日期请求，不需要像新浪 K 线接口一样回拉大量历史记录。

本说明以已安装 SDK 的公开根入口、SDK 源码与实际请求为准。Baostock 官方知识库页面 [stockKData.md](https://www.baostock.com/mainContent?file=stockKData.md) 在本次验证时返回 502，因此不能将其当作当前可用的机器可读规范。

## 安装与会话

当前项目的 `uv` 环境尚未声明 Baostock；因此下面命令在本机可用，但**不是项目生产环境的安装方案**：

```bash
conda run -n base python -c "import baostock; print(baostock.__version__)"
```

所有查询前必须建立会话，使用后必须释放：

```python
import baostock as bs

login = bs.login()  # 默认匿名账号：anonymous / 123456
if login.error_code != "0":
    raise RuntimeError(login.error_msg)

try:
    result = bs.query_trade_dates("2026-07-01", "2026-07-10")
finally:
    bs.logout()
```

`login(user_id='anonymous', password='123456')` 返回 `ResultData`；`logout(user_id='anonymous')` 返回同类结果。会话未建立时，查询会返回 `error_code != "0"`，常见错误信息为 `you don't login.`。

## 通用返回协议

全部公开查询接口返回 `baostock.data.resultset.ResultData`，而非直接返回 DataFrame。

| 成员/方法 | 含义 |
| --- | --- |
| `error_code` | 字符串状态码；`"0"` 表示成功。任何读取前必须检查。 |
| `error_msg` | 状态说明或错误原因。 |
| `fields` | 本次结果字段名列表。 |
| `next()` | 游标前进；有下一行时返回 `True`。SDK 会自动处理分页。 |
| `get_row_data()` | 读取当前行，返回字符串列表。 |
| `get_data()` | 汇总全部页为 pandas `DataFrame`。 |

源端传回的数值通常为字符串，适配器必须按字段显式转为 `date`、`Decimal`、`int` 或 `float`，不能依赖 pandas 自动推断。空结果也可能是成功响应，因此需区分“请求错误”和“该日期无数据”。

### 代码、日期和通用约束

- 证券代码使用 `sh.600000`、`sz.000524` 形式；`query_history_k_data_plus` 要求长度为 9。
- 日期使用 `YYYY-MM-DD`。未传 K 线起止日期时，SDK 默认从 `2015-01-01` 到当天；生产调用应始终显式传入边界。
- `year` 为四位年份，`quarter` 为 `1` 至 `4`；均以财报报告期查询。
- 返回字段的精确定义以实际 `result.fields` 为准；字段名保留源端原样，项目模型层再转换为统一命名。

## 接口目录

以下是 `import baostock as bs` 在本机已验证版本中可直接调用的全部公开查询入口；项目将使用可复现的 `0.9.3`。

### 交易日、证券目录与指数成分

| 接口 | 入口参数 | 返回字段 | 用途 |
| --- | --- | --- | --- |
| `query_trade_dates(start_date=None, end_date=None)` | 起止日期 | `calendar_date, is_trading_day` | A 股交易日历。 |
| `query_all_stock(day=None)` | 查询日；空值取最新 | `code, tradeStatus, code_name` | 当日可交易证券目录。 |
| `query_stock_basic(code='', code_name='')` | 可按代码或名称筛选 | `code, code_name, ipoDate, outDate, type, status` | 上市、退市与证券基本信息。 |
| `query_stock_industry(code='', date='')` | 可选代码、日期 | `updateDate, code, code_name, industry, industryClassification` | 行业分类。 |
| `query_hs300_stocks(date='')` | 成分生效日；空值最新 | `updateDate, code, code_name` | 沪深 300 成分股。 |
| `query_sz50_stocks(date='')` | 成分生效日；空值最新 | `updateDate, code, code_name` | 上证 50 成分股。 |
| `query_zz500_stocks(date='')` | 成分生效日；空值最新 | `updateDate, code, code_name` | 中证 500 成分股。 |

`query_all_stock` 的 `tradeStatus` 反映该查询日是否交易，但它不是项目 `stock_catalog` 的完整替代：项目仍应以 mootdx catalog 作为运行标的池，Baostock 用于补充核验或辅助状态判断。

### 历史 K 线

```python
result = bs.query_history_k_data_plus(
    code="sz.000524",
    fields="date,code,open,high,low,close,preclose,volume,amount,"
           "adjustflag,turn,tradestatus,pctChg,isST",
    start_date="2026-06-20",
    end_date="2026-07-10",
    frequency="d",
    adjustflag="3",
)
```

| 接口 | 入口参数 | 返回值/字段 |
| --- | --- | --- |
| `query_history_k_data_plus(code, fields, start_date=None, end_date=None, frequency='d', adjustflag='3')` | `code`：`sh.600000` 形式；`fields`：逗号分隔的请求字段，必填；`start_date`、`end_date`：日期边界；`frequency`：`d`、`w`、`m`、`5`、`15`、`30`、`60`；`adjustflag`：`1` 后复权、`2` 前复权、`3` 不复权。 | `ResultData`，仅返回 `fields` 中请求且该频率支持的字段。 |

日、周、月线常用字段：

`date, code, open, high, low, close, preclose, volume, amount, adjustflag, turn, tradestatus, pctChg, isST`

分钟线常用字段：

`date, time, code, open, high, low, close, volume, amount, adjustflag`

项目日线核验应固定使用 `frequency="d"` 与 `adjustflag="3"`，并只请求：

```text
date,open,high,low,close,volume,amount,tradestatus,isST
```

这样可精确判定某日是否存在源端记录，同时避免复权口径影响原始 OHLCV 的对比。

### 停牌占位记录

Baostock 在停牌日可能返回 OHLC 与停牌前收盘价相同、`volume=0`、`amount` 为空、`tradestatus=0` 的占位记录。该记录只能说明源端知道该交易日，**不能说明存在可回补的成交日线**。

项目适配器会保留 `tradestatus`，按需核验链路仅接受 `tradestatus=1` 的记录写入 `mootdx_stock_kline`。`tradestatus=0` 的记录按该日期 `no_data` 处理，作为“已知无交易”的证据，不写入日线主表。

### 复权与分红

| 接口 | 入口参数 | 返回字段 | 用途 |
| --- | --- | --- | --- |
| `query_adjust_factor(code, start_date=None, end_date=None)` | 代码、起止日期 | `code, dividOperateDate, foreAdjustFactor, backAdjustFactor, adjustFactor` | 复权因子。 |
| `query_dividend_data(code, year=None, yearType='report')` | 代码、年份、`yearType` | `code, dividPreNoticeDate, dividAgmPumDate, dividPlanAnnounceDate, dividPlanDate, dividRegistDate, dividOperateDate, dividPayDate, dividStockMarketDate, dividCashPsBeforeTax, dividCashPsAfterTax, dividStocksPs, dividCashStock, dividReserveToStockPs` | 分红、送转、配股及登记日信息。 |

### 季度财务指标

以下接口参数均为 `code, year=None, quarter=None`，返回一个或多个报告期记录。

| 接口 | 返回字段 |
| --- | --- |
| `query_profit_data` | `code, pubDate, statDate, roeAvg, npMargin, gpMargin, netProfit, epsTTM, MBRevenue, totalShare, liqaShare` |
| `query_operation_data` | `code, pubDate, statDate, NRTurnRatio, NRTurnDays, INVTurnRatio, INVTurnDays, CATurnRatio, AssetTurnRatio` |
| `query_growth_data` | `code, pubDate, statDate, YOYEquity, YOYAsset, YOYNI, YOYEPSBasic, YOYPNI` |
| `query_balance_data` | `code, pubDate, statDate, currentRatio, quickRatio, cashRatio, YOYLiability, liabilityToAsset, assetToEquity` |
| `query_cash_flow_data` | `code, pubDate, statDate, CAToAsset, NCAToAsset, tangibleAssetToAsset, ebitToInterest, CFOToOR, CFOToNP, CFOToGr` |
| `query_dupont_data` | `code, pubDate, statDate, dupontROE, dupontAssetStoEquity, dupontAssetTurn, dupontPnitoni, dupontNitogr, dupontTaxBurden, dupontIntburden, dupontEbittogr` |

### 业绩披露与预测

| 接口 | 入口参数 | 返回字段 |
| --- | --- | --- |
| `query_performance_express_report(code, start_date=None, end_date=None)` | 代码、公告日期区间 | `code, performanceExpPubDate, performanceExpStatDate, performanceExpUpdateDate, performanceExpressTotalAsset, performanceExpressNetAsset, performanceExpressEPSChgPct, performanceExpressROEWa, performanceExpressEPSDiluted, performanceExpressGRYOY, performanceExpressOPYOY` |
| `query_forecast_report(code, start_date=None, end_date=None)` | 代码、公告日期区间 | `code, profitForcastExpPubDate, profitForcastExpStatDate, profitForcastType, profitForcastAbstract, profitForcastChgPctUp, profitForcastChgPctDwn` |

### 宏观数据

| 接口 | 入口参数 | 返回字段 |
| --- | --- | --- |
| `query_deposit_rate_data(start_date='', end_date='')` | 发布日期区间 | `pubDate, demandDepositRate, fixedDepositRate3Month, fixedDepositRate6Month, fixedDepositRate1Year, fixedDepositRate2Year, fixedDepositRate3Year, fixedDepositRate5Year, installmentFixedDepositRate1Year, installmentFixedDepositRate3Year, installmentFixedDepositRate5Year` |
| `query_loan_rate_data(start_date='', end_date='')` | 发布日期区间 | `pubDate, loanRate6Month, loanRate6MonthTo1Year, loanRate1YearTo3Year, loanRate3YearTo5Year, loanRateAbove5Year, mortgateRateBelow5Year, mortgateRateAbove5Year` |
| `query_required_reserve_ratio_data(start_date='', end_date='', yearType='0')` | 发布日期区间、年份类型 | `pubDate, effectiveDate, bigInstitutionsRatioPre, bigInstitutionsRatioAfter, mediumInstitutionsRatioPre, mediumInstitutionsRatioAfter` |
| `query_money_supply_data_month(start_date='', end_date='')` | 发布日期区间 | `statYear, statMonth, m0Month, m0YOY, m0ChainRelative, m1Month, m1YOY, m1ChainRelative, m2Month, m2YOY, m2ChainRelative` |
| `query_money_supply_data_year(start_date='', end_date='')` | 发布日期区间 | `statYear, m0Year, m0YearYOY, m1Year, m1YearYOY, m2Year, m2YearYOY` |

## 本次可用性验证

在 2026-07-11 用匿名会话进行了以下请求：

| 验证项 | 结果 |
| --- | --- |
| `sz.000524`，日线，`2026-06-20` 至 `2026-07-10` | 源端会返回停牌占位记录；`2026-06-24` 至 `2026-07-07` 的记录均为 `tradestatus=0`，过滤后无可交易日线，与人工抽查的停牌区间一致。 |
| `sz.000524`，日线，`1993-11-18` 至 `1993-12-31` | 成功返回 32 条记录，首日为 `1993-11-18`，验证可覆盖早期历史。 |
| `sz.000524`，5 分钟线，`2026-07-09` | 请求成功，返回分钟字段集合。 |
| `query_trade_dates`、`query_all_stock`、`query_stock_basic`、行业、成分股、复权、分红、财务、披露和宏观接口 | 均可成功返回字段元数据。 |

这只能证明当前网络和匿名会话可用，不代表源端长期 SLA。接入生产任务前仍需加入超时、指数退避、单标的失败审计和独立健康检查。

## 面向项目的接入边界

1. `stock_catalog`：仍以 `mootdx_stock_catalog` 的有效标的池为唯一主池，不能以 Baostock 返回目录覆盖或删除 catalog 标的。
2. `stock_kline_daily`：Baostock 优先用于“某个标的在若干明确交易日是否有原始日线”的核验；确认有数据后才创建定向回补任务。
3. 缺口判定：Baostock 与新浪均无记录时，标记为“多源无交易证据”，而不是建议回补；两源不一致或任一请求失败时，进入人工核验。
4. 数据写入：若后续允许 Baostock 回补，必须记录 `source=baostock`、源端字段、原始日期范围和校验结果，不能静默覆盖 mootdx 记录。
5. 依赖管理：适配器使用项目 `market` 可选依赖中的 `baostock==0.9.3`，并在项目 `uv` 环境做集成测试；不要依赖开发机 conda `base` 的手工安装。

## 当前项目接入

Baostock 已接入 `stock_kline_daily` 的按需二次核验路径，不存在独立定时任务。运行已有 mootdx 日线主同步、缺口核对或定向回补时，只有当 mootdx 请求成功但未返回有效目标日期日线，系统才会调用 Baostock。

- Baostock 返回 `tradestatus=1` 的有效日线：写入 `mootdx_stock_kline`，`source='baostock'`，并保存 `available` 核验记录。
- Baostock 返回 `tradestatus=0` 的停牌占位行：不写 K 线，按 `no_data` 保存逐日核验记录。
- Baostock 成功但目标日无记录：不写 K 线，保存 `no_data` 逐日核验记录。
- Baostock 登录、请求或字段处理失败：保存 `error` 核验记录；不会把异常误判为停牌或无交易。

核验记录存入 `mootdx_daily_gap_verifications`，按 `symbol + frequency + trade_date` 保留最新结论。日线质量页优先使用该证据：一个缺口区间仅在所有缺失日均为 `no_data` 时才显示“已知无数据”；存在 `error` 时保持“待核验”。

## SDK 内部但不纳入支持范围的接口

安装包的内部模块还能找到停牌、ST、科创板、港股通、概念、地域、CPI、PPI、PMI 等函数，但这些函数没有从 `baostock` 根模块导出，版本兼容性没有得到当前 SDK 的公开 API 保证。项目第一版不应直接调用；确有需要时，应先封装兼容层并增加联网回归测试。
