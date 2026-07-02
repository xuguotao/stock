# 腾讯股票数据接口调研文档

## 结论

当前没有找到腾讯官方公开维护的股票数据 API 文档。本文记录的是从腾讯行情中心页面和项目现有代码中确认过的实际接口，属于“页面反查接口”和“非官方稳定接口”，后续接入时必须做健康检查、字段校验和兜底降级。

基于 2026-07-01 的验证结果，腾讯更适合作为本项目实时行情、分钟线和股票池扫描的主数据源。AKShare 不应作为这些高频链路的优先来源，只适合作为低频补充或兜底。

## 来源

- 腾讯行情中心页面：`https://stockapp.finance.qq.com/`
- 腾讯行情中心页面引用的前端包：`https://st.gtimg.com/quotes_center/assets/index.1bf0389c.js`
- 项目现有腾讯数据源：`src/data/tencent_source.py`
- Stockbar 开源项目：`https://github.com/VGEAREN/Stockbar`
  - `StockMonitor/Services/DataService.swift`
  - `StockMonitor/Services/ChartService.swift`
  - `StockMonitor/Views/SettingsView.swift`
- `ArSrNa/tencent-stock-api` 开源项目：`https://github.com/ArSrNa/tencent-stock-api`
  - `src/stock.ts`
  - `src/type.ts`
  - `__tests__/stock.test.ts`

## 接口总览

| 场景 | 推荐级别 | 接口 | 当前判断 |
| --- | --- | --- | --- |
| 全 A 股票池/排行列表 | 主接口候选 | `https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList` | 可分页返回全 A，实测 `total=5528` |
| 股票搜索 | 主接口候选 | `https://proxy.finance.qq.com/ifzqgtimg/appstock/smartbox/search/get` | Stockbar 使用该接口做 A 股、港股、美股搜索主来源 |
| 实时行情快照 | 主接口 | `https://qt.gtimg.cn/q={symbols}` | 项目已接入，字段丰富，支持批量 |
| 实时行情 UTF-8 入口 | 优先候选 | `https://sqt.gtimg.cn/utf8/q={symbols}` | 与 `qt.gtimg.cn` 字段结构一致，返回 UTF-8，2026-07-02 小样本延迟更低 |
| 港股实时行情 | 可复用 | `https://qt.gtimg.cn/q=r_{hkSymbol}` | Stockbar 使用该接口获取港股实时行情 |
| 指数实时行情 | 可复用 | `https://qt.gtimg.cn/q=sh000001,sz399001,hkHSI` | `ArSrNa/tencent-stock-api` 覆盖上证、深证、恒指示例 |
| 当日 1 分钟分时 | 主接口 | `https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}` | 项目已接入，可由累计量额差分得到分钟量额 |
| 多周期分钟 K 线 | 主接口 | `https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},{period},,{count}` | 项目当前稳定使用 `m5` |
| 日/周/月复权 K 线 | 辅助接口 | `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},{period},,{endDate},{count},{fq}` | 可用于价格/复权/成交量校验，不含历史成交额 |
| 板块排行 | 辅助接口 | `https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank` | 返回板块/行业排行，不是股票池接口 |
| 旧排行接口 | 不建议主用 | `https://stock.gtimg.cn/data/view/prank.php` | 当前测试部分参数返回空，保留为历史线索 |

## 通用约定

### 股票代码格式

腾讯接口多数使用市场前缀 + 6 位代码：

| 腾讯格式 | 项目格式 | 示例 |
| --- | --- | --- |
| `sz000001` | `000001.SZ` | 平安银行 |
| `sh600000` | `600000.SH` | 浦发银行 |
| `bj920699` | `920699.BJ` | 北交所股票 |
| `hk00700` | 港股内部格式 | 腾讯控股 |
| `r_hk00700` | 港股实时查询格式 | 腾讯 `qt.gtimg.cn` 港股实时行情 |
| `sh000001` | 指数代码 | 上证指数 |
| `sz399001` | 指数代码 | 深证成指 |
| `hkHSI` | 指数代码 | 恒生指数 |

接入时应统一走项目已有的 `format_symbol` 规则，避免页面、接口和 ClickHouse 中出现多套代码格式。

### 请求头建议

```http
User-Agent: Mozilla/5.0
Referer: https://stockapp.finance.qq.com/mstats/
```

`qt.gtimg.cn`、`web.ifzq.gtimg.cn`、`ifzq.gtimg.cn` 当前也可以使用：

```http
Referer: https://gu.qq.com/
```

### 编码入口

实时行情有两个常用入口：

| 入口 | 编码 | 说明 |
| --- | --- | --- |
| `https://qt.gtimg.cn/q={symbols}` | GBK | 当前项目使用，需转码 |
| `https://sqt.gtimg.cn/utf8/q={symbols}` | UTF-8 | 2026-07-02 实测可用，字段结构与 `qt.gtimg.cn` 一致 |

后续代码可以评估把 `sqt.gtimg.cn/utf8` 作为实时行情主入口或备选入口，减少 GBK 解码带来的兼容问题。

## 全 A 股票池/排行列表

### 用途

用于获取当前腾讯可见的全 A 股票集合，并可同时拿到实时排行字段。适合作为股票基础信息的主候选来源，但它不是完整的静态基础资料接口，缺少上市日期、申万行业等长期字段。

### URL

```text
GET https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList
```

### 参数

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `_appver` | `11.17.0` | 腾讯页面使用的版本参数 |
| `board_code` | `aStock` | A 股全市场 |
| `sort_type` | `priceRatio` | 排序字段，页面按涨跌幅排序时使用 |
| `direct` | `down` | 排序方向 |
| `offset` | `0` | 分页起始位置 |
| `count` | `100` | 每页数量，2026-07-02 实测 `100/150/200` 可用，`300+` 返回参数错误 |

### 验证样例

```text
https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList?_appver=11.17.0&board_code=aStock&sort_type=priceRatio&direct=down&offset=0&count=5
```

2026-07-01 实测：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "total": 5528,
    "rank_list": [
      {
        "code": "bj920699",
        "name": "海达尔",
        "stock_type": "GP",
        "state": "",
        "zxj": "92.93",
        "zdf": "29.99",
        "volume": "36836.00",
        "turnover": "30966",
        "hsl": "17.65",
        "zsz": "42.40",
        "ltsz": "19.40",
        "pe_ttm": "78.11"
      }
    ]
  }
}
```

### 关键字段

| 字段 | 含义 | 项目使用建议 |
| --- | --- | --- |
| `code` | 腾讯代码，含市场前缀 | 转成 `symbol` 和 `code` |
| `name` | 股票名称 | 写入 `StockInfo.name` |
| `stock_type` | 证券类型 | 只保留普通股票时可用于过滤 |
| `state` | 状态字段 | 用于停牌/异常状态观察，需继续积累样本 |
| `zxj` | 最新价 | 可用于快照校验 |
| `zdf` | 涨跌幅 | 可用于快照校验 |
| `volume` | 成交量 | 可用于实时快照，不建议写入基础信息表 |
| `turnover` | 成交额 | 可用于实时快照，不建议写入基础信息表 |
| `zsz` | 总市值 | 可用于估值快照 |
| `ltsz` | 流通市值 | 可用于估值快照 |
| `pe_ttm` | TTM 市盈率 | 可用于估值快照 |

### 映射到 `StockInfo`

| `StockInfo` 字段 | 腾讯字段 | 处理方式 |
| --- | --- | --- |
| `symbol` | `code` | `sz000001` -> `000001.SZ` |
| `code` | `code` | 去掉市场前缀 |
| `name` | `name` | 原样保存 |
| `industry` | 无 | 由其他源补充，或保留历史值 |
| `list_date` | 无 | 由其他源补充，或保留历史值 |
| `is_st` | `name` | 名称包含 `ST`、`*ST` 时推断 |

### 接入建议

1. 使用 `offset/count` 分页拉取，直到累计条数达到 `data.total` 或返回空列表。
2. 推荐 `count=100` 或 `count=200`。2026-07-02 实测 `count=300/400/500` 返回 `参数错误:count too large`。
3. 每页校验 `code=0`、`data.rank_list` 为数组、核心字段 `code/name` 存在。
4. 入库前去重，主键按标准化后的 `symbol`。
5. 对于腾讯没有的 `industry/list_date`，不要用空值覆盖数据库已有非空值。
6. 记录每次拉取的 `total`、实际条数、重复条数、无效条数，用于数据中心展示。

## 股票搜索

### 来源说明

Stockbar 使用该接口作为股票搜索主来源，覆盖 A 股、港股、美股。该接口不是全量股票池接口，但适合后台管理页面、手工添加股票、代码/名称校验等交互场景。

### URL

```text
GET https://proxy.finance.qq.com/ifzqgtimg/appstock/smartbox/search/get?q={keyword}
```

### 示例

```text
https://proxy.finance.qq.com/ifzqgtimg/appstock/smartbox/search/get?q=平安银行
```

返回结构：

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "stock": [
      ["sz", "000001", "平安银行", "", "GP-A"]
    ]
  }
}
```

更多实测样例：

| 查询词 | 返回示例 | 说明 |
| --- | --- | --- |
| `000001` | `["sz", "000001", "平安银行", "", "GP-A"]` | A 股股票 |
| `000001` | `["sh", "000001", "上证指数", "", "ZS"]` | 指数也会返回，需要过滤 |
| `000001` | `["jj", "000001", "华夏成长混合", "", "KJ"]` | 基金也会返回，需要过滤 |
| `腾讯` | `["hk", "00700", "腾讯控股", "", "GP"]` | 港股 |
| `腾讯` | `["us", "TCEHY.PS", "腾讯控股(ADR)", "", "GP"]` | 美股 ADR |
| `AAPL` | `["us", "AAPL.OQ", "苹果", "", "GP"]` | 美股 |
| `浦发银行` | `["sh", "600000", "浦发银行", "", "GP-A"]` | A 股股票 |

### 字段含义

`data.stock` 是二维数组。Stockbar 的解析规则是：

| 位置 | 含义 | 示例 |
| --- | --- | --- |
| `0` | 市场 | `sh`、`sz`、`bj`、`hk`、`us`、`jj` |
| `1` | 代码 | `000001`、`00700`、`AAPL.OQ` |
| `2` | 名称 | `平安银行` |
| `3` | 未确认 | 常见为空字符串 |
| `4` | 类型 | `GP-A`、`GP-A-KCB`、`GP`、`ZS`、`KJ` |

### 项目接入建议

- 后台手工搜索股票时优先使用该接口。
- 股票基础信息全量同步不能依赖该接口，因为它只按关键词返回有限结果。
- A 股股票应先按 `market in {"sh","sz","bj"}` 过滤，再排除 `ZS`、`KJ` 等非股票类型。注意北交所搜索结果可能是 `market=bj` 且 `type=GP`，不能简单要求类型必须以 `GP-A` 开头。
- 搜索结果可能包含指数、基金、美股 ADR，必须按用途过滤。
- 美股代码如 `AAPL.OQ`，如果后续支持美股，需要单独定义代码归一化规则。

## 实时行情快照

### 用途

用于批量获取股票实时价格、成交量、成交额、涨跌幅、估值、市值、涨跌停等字段。项目当前已经在 `TencentQuoteSource.fetch_realtime_quotes` 中使用该接口。

`ArSrNa/tencent-stock-api` 项目也只封装了这个接口，它的价值主要是补充了 A 股/指数返回字段的结构化命名。

### URL

```text
GET https://qt.gtimg.cn/q={symbol1},{symbol2},...
```

UTF-8 入口：

```text
GET https://sqt.gtimg.cn/utf8/q={symbol1},{symbol2},...
```

### 示例

```text
https://qt.gtimg.cn/q=sz000001,sh600000
https://sqt.gtimg.cn/utf8/q=sz000001,sh600000
```

`qt.gtimg.cn` 返回 GBK 文本，`sqt.gtimg.cn/utf8` 返回 UTF-8 文本。两者格式类似：

```text
v_sz000001="51~平安银行~000001~10.16~10.05~...";
```

### 项目当前解析字段

项目当前解析逻辑见 `src/data/tencent_source.py` 的 `parse_tencent_quote_text`。

| 下标 | 项目字段 | 含义 |
| --- | --- | --- |
| `1` | `name` | 股票名称 |
| `2` | `symbol` | 6 位代码 |
| `3` | `price` | 最新价 |
| `4` | `prev_close` | 昨收 |
| `5` | `open` | 今开 |
| `30` | `timestamp` | 行情时间 |
| `31` | `change_amt` | 涨跌额 |
| `32` | `change_pct` | 涨跌幅 |
| `33` | `high` | 最高 |
| `34` | `low` | 最低 |
| `36` | `volume` | 成交量 |
| `37` | `amount` | 成交额，项目当前乘以 `10000` 转为元 |
| `38` | `turnover_pct` | 换手率 |
| `39` | `pe_ttm` | TTM 市盈率 |
| `43` | `amplitude_pct` | 振幅 |
| `44` | `mcap` | 总市值，项目当前乘以 `100000000` |
| `45` | `float_mcap` | 流通市值，项目当前乘以 `100000000` |
| `46` | `pb` | 市净率 |
| `47` | `limit_up` | 涨停价 |
| `48` | `limit_down` | 跌停价 |
| `49` | `vol_ratio` | 量比 |
| `52` | `pe_static` | 静态市盈率 |

### A 股/指数补充字段字典

`ArSrNa/tencent-stock-api` 对 `qt.gtimg.cn` 的 A 股/指数响应做了更完整的结构化解析。结合 2026-07-02 对 `sz000001`、`sh600000`、`sh000001`、`sz399001` 以及 789 只样本的验证，A 股/指数通常返回 87 或 88 个 `~` 分隔字段。

| 下标 | 含义 | 说明 |
| --- | --- | --- |
| `0` | 市场/类型编号 | A 股样例为 `51`，指数样例为 `1` |
| `1` | 名称 | 股票或指数名称 |
| `2` | 代码 | 6 位代码 |
| `3` | 最新价 | 当前价 |
| `4` | 昨收 | 前收盘价 |
| `5` | 今开 | 开盘价 |
| `6` | 成交量 | 单位按腾讯返回值保存，A 股通常可视为手 |
| `7` | 外盘 | 外盘成交量 |
| `8` | 内盘 | 内盘成交量 |
| `9-18` | 买一到买五 | 奇数位价格、偶数位数量 |
| `19-28` | 卖一到卖五 | 奇数位价格、偶数位数量 |
| `29` | 最近逐笔成交 | A 股样例常为空，指数为 0 |
| `30` | 行情时间 | A 股格式 `YYYYMMDDHHMMSS` |
| `31` | 涨跌额 | 最新价 - 昨收 |
| `32` | 涨跌幅 | 百分比数值 |
| `33` | 最高价 | 当日最高 |
| `34` | 最低价 | 当日最低 |
| `35` | 价格/量/额复合字段 | 形如 `price/volume/amount` |
| `36` | 成交量 | 与 `35` 中的成交量一致 |
| `37` | 成交额 | 单位通常为万，项目当前乘以 `10000` 转元 |
| `38` | 换手率 | 百分比数值 |
| `39` | 市盈率 | 对股票是 PE，对指数也可能返回估值口径 |
| `41` | 最高价重复字段 | 通常等于 `33` |
| `42` | 最低价重复字段 | 通常等于 `34` |
| `43` | 振幅 | 百分比数值 |
| `44` | 流通市值候选 | 实测平安银行为 `1971.61` |
| `45` | 总市值候选 | 实测平安银行为 `1971.64` |
| `46` | 市净率 | PB |
| `47` | 涨停价 | 指数返回 `-1` |
| `48` | 跌停价 | 指数返回 `-1` |
| `49` | 量比 | 股票/指数均可能返回 |
| `52` | 市盈率静态/动态候选 | 与字段来源口径存在社区差异，需继续校验 |
| `53` | 市盈率静态/动态候选 | 与字段来源口径存在社区差异，需继续校验 |
| `61` | 证券类型 | 例如 `GP-A`、`ZS` |

### 市值字段风险

当前项目里 `src/data/tencent_source.py` 将 `44` 解析为 `mcap`，将 `45` 解析为 `float_mcap`。但 `ArSrNa/tencent-stock-api` 将 `44` 命名为流通市值、`45` 命名为总市值；2026-07-02 对平安银行的实测也支持这个判断：

```text
44 = 1971.61
45 = 1971.64
```

平安银行总股本略大于流通股本，因此 `45` 更像总市值，`44` 更像流通市值。这个问题需要单独修正代码和历史快照字段解释，不能只改文档。

### 接入注意

- 返回文本不是 JSON，必须按 `~` 分隔解析。
- 批量数量需要限制。easyquotation 等社区库常用限制是每批 60 只，但项目当前默认 `realtime_chunk_size=800`；真实稳定批量必须结合失败率和响应时间压测，不能直接把社区限制当硬限制。
- 成交额单位要持续用数据质量规则校验，避免再次出现 `amount` 单位漂移。
- A 股/指数和港股返回字段长度不同，A 股/指数样例为 88 个字段，港股/恒指样例为 78 个字段，不能共用同一套字段下标解释。
- 如果接入指数，需要通过字段 `61` 或查询代码区分 `ZS`，避免把指数混入股票池。

## 港股实时行情

### 来源说明

Stockbar 使用腾讯 `qt.gtimg.cn` 获取港股实时行情。它的港股查询格式和 A 股不同，需要在港股代码前加 `r_`。

另一个形式是直接使用 `hk00700`。`ArSrNa/tencent-stock-api` 测试中使用 `hk00700` 获取腾讯控股，2026-07-02 实测可返回 `v_hk00700`。Stockbar 使用 `r_hk00700`，返回变量名为 `v_r_hk00700`。

### URL

```text
GET https://qt.gtimg.cn/q=r_hk00700
```

批量查询：

```text
GET https://qt.gtimg.cn/q=r_hk00700,r_hk03690
```

返回格式：

```text
v_r_hk00700="1~腾讯控股~00700~342.00~345.00~...";
```

Stockbar 解析字段：

| 下标 | 含义 |
| --- | --- |
| `1` | 名称 |
| `2` | 港股代码 |
| `3` | 最新价 |
| `4` | 昨收 |
| `30` | 更新时间 |

2026-07-02 对 `hk00700` 和 `hkHSI` 的验证显示，港股/恒指返回字段约 78 个，字段含义与 A 股不完全一致：

| 下标 | 港股样例含义 | 说明 |
| --- | --- | --- |
| `3` | 最新价 | 港股价格保留 3 位小数 |
| `4` | 昨收 | 前收盘价 |
| `5` | 今开 | 开盘价 |
| `6` | 成交量 | 港股样例为成交股数 |
| `30` | 更新时间 | 格式 `YYYY/MM/DD HH:MM:SS` |
| `31` | 涨跌额 | 最新价 - 昨收 |
| `32` | 涨跌幅 | 百分比数值 |
| `33` | 最高价 | 当日最高 |
| `34` | 最低价 | 当日最低 |
| `35` | 最新价重复字段 | 港股这里不是 `price/volume/amount` 复合字段 |
| `36` | 成交量重复字段 | 与 `6` 接近 |
| `37` | 成交额 | 港股样例为原始金额，不是 A 股的万元口径 |
| `43` | 振幅 | 百分比数值 |
| `44/45` | 市值字段候选 | 港股样例两个值相同，仍需单独确认 |

### 接入判断

当前项目聚焦 A 股时，该接口不是优先事项。但如果后续扩展港股观察或跨市场自选股，Stockbar 的实现说明腾讯港股实时接口可以复用。

## 指数实时行情

### 来源说明

`ArSrNa/tencent-stock-api` 的测试覆盖了 `sh000001`、`sz399001`、`hkHSI`，说明 `qt.gtimg.cn` 可用于主要指数实时行情。

### 示例

```text
GET https://qt.gtimg.cn/q=sh000001,sz399001,hkHSI
```

样例代码：

| 代码 | 名称 | 返回类型 |
| --- | --- | --- |
| `sh000001` | 上证指数 | `ZS` |
| `sz399001` | 深证成指 | `ZS` |
| `hkHSI` | 恒生指数 | 港股指数 |

### 接入判断

指数行情可以用于市场环境、宽基温度、数据健康参照，但不能进入股票基础信息表。后续如果做市场总览，建议单独建 `market_index_quotes` 或类似结构。

## 当日 1 分钟分时

### 用途

获取单只股票当日 1 分钟分时数据。腾讯返回的是累计成交量和累计成交额，项目当前通过相邻分钟差分得到单分钟成交量和成交额。

### URL

```text
GET https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}
```

也支持 JSONP 包装形式，Stockbar 使用的是：

```text
GET https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data_{symbol}&code={symbol}
```

带 `_var` 时，返回内容会变成：

```text
min_data_sz000001={...json...}
```

### 示例

```text
https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sz000001
```

返回结构：

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "sz000001": {
      "data": {
        "date": "20260701",
        "data": [
          "0930 10.05 7036 7071180.00",
          "0931 10.01 32203 32298494.00"
        ]
      }
    }
  }
}
```

单行格式：

```text
HHMM price cumulative_volume cumulative_amount
```

沪深 A 股和港股样例通常是 4 列。2026-07-02 实测北交所 `bj920699` 返回 3 列：

```text
0930 94.00 476
```

因此解析时必须按列数分支：有第 4 列时使用累计成交额差分；没有第 4 列时不能直接生成真实分钟成交额，只能置空或使用价格乘成交量估算并标记为估算值。

### 项目解析规则

| 输出字段 | 来源 |
| --- | --- |
| `datetime` | `date + HHMM` |
| `open/high/low/close` | 当前分钟价格，当前实现都使用同一个 `price` |
| `volume` | 当前累计成交量 - 上一分钟累计成交量 |
| `amount` | 当前累计成交额 - 上一分钟累计成交额 |

### 接入注意

- 该接口只适合当日分时，不适合作为长期历史分钟线回放来源。
- 必须过滤非 A 股正常交易时间。
- 如果中途重拉，需要按 `(symbol, datetime)` 幂等覆盖或去重。
- 同一接口也支持港股，例如 `code=hk00700`，返回结构和 A 股一致，时间轴按港股交易时间展开。
- 北交所分时可能缺少累计成交额字段，不能和沪深 A 股共用同一套强校验规则。

## 多周期分钟 K 线

### 用途

获取单只股票分钟 K 线。项目当前已经在 `TencentQuoteSource.fetch_intraday_bars` 中稳定使用 `m5`，2026-07-02 额外验证 `m1`、`m15` 可用。其他周期需要接入前再压测。

### URL

```text
GET https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},{period},,{count}
```

参数：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `symbol` | `sz000001` | 腾讯代码 |
| `period` | `m1`、`m5`、`m15`、`m30`、`m60` | 分钟周期 |
| `count` | `5`、`320` | 返回条数 |

### 示例

```text
https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sz000001,m1,,5
https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sz000001,m5,,320
https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sz000001,m15,,5
```

返回结构中核心节点：

```text
data.{symbol}.{period}
```

单条 K 线通常是数组：

```text
[datetime, open, close, high, low, volume, extra, turnover_pct]
```

项目当前解析：

| 输出字段 | 来源 |
| --- | --- |
| `datetime` | 第 0 位，格式 `YYYYMMDDHHMM` |
| `open` | 第 1 位 |
| `close` | 第 2 位 |
| `high` | 第 3 位 |
| `low` | 第 4 位 |
| `volume` | 第 5 位 |
| `amount` | 当前项目用 `close * volume * 100` 估算 |

### 接入注意

- 当前项目中的 `amount` 是估算值，不是接口直接提供的真实成交额。
- 如果系统需要严格成交额，优先使用 1 分钟累计成交额差分后再聚合到 5 分钟。
- `count` 决定返回条数，接入任务中应避免每次全量拉过多历史。
- `m1` 的历史窗口来自 `mkline`，但当日 1 分钟成交额更建议使用 `minute/query` 的累计成交额差分。

## 日/周/月复权 K 线

### 用途

获取单只股票或指数的日、周、月 K 线，并支持前复权、后复权。该接口适合做价格、复权和成交量校验，但返回 K 线不包含历史成交额字段，不能作为本项目日线成交额的唯一来源。

### URL

```text
GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},{period},,{endDate},{count},{fq}
```

参数：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `symbol` | `sz000001`、`sh000001`、`hk00700` | 腾讯代码 |
| `period` | `day`、`week`、`month` | K 线周期 |
| `endDate` | 空字符串、`2026-06-30` | 结束日期，空表示最新 |
| `count` | `5`、`30`、`350` | 返回条数 |
| `fq` | `qfq`、`hfq` | 前复权、后复权 |

### 示例

```text
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000001,day,,,5,qfq
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000001,day,,2026-06-30,5,qfq
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk00700,day,,,350,qfq
```

返回结构核心节点：

```text
data.{symbol}.{fq}{period}
```

不同市场的 key 规则不同：

| 市场 | 请求复权参数 | 返回 key |
| --- | --- | --- |
| 沪深 A 股 | `qfq` | `qfqday`、`qfqweek`、`qfqmonth` |
| 沪深 A 股 | `hfq` | `hfqday`、`hfqweek`、`hfqmonth` |
| 指数 | `qfq`/`hfq` | `day`、`week`、`month` |
| 港股 | `qfq`/`hfq` | `day`、`week`、`month` |

例如 `qfqday`：

```json
[
  ["2026-06-25", "10.470", "10.420", "10.590", "10.410", "1083999.000"]
]
```

单条 K 线：

| 位置 | 含义 |
| --- | --- |
| `0` | 日期 |
| `1` | 开盘 |
| `2` | 收盘 |
| `3` | 最高 |
| `4` | 最低 |
| `5` | 成交量 |

### 接入注意

- 2026-07-02 实测 `day` 和指定 `endDate` 可用。
- 返回中通常还包含 `qt` 节点，即当前实时行情快照，不应和历史 K 线混写。
- 该接口缺少历史成交额 `amount`，所以不能直接替代当前日线主数据源。
- 可作为复权价格校验、成交量校验、指数 K 线补充来源。
- 港股日/周 K 线可能在第 6 位带公司行动对象，例如回购信息；解析 OHLCV 时不要假设每行永远只有 6 个元素。

## 板块排行接口

### 用途

用于获取板块/行业排行及领涨股票，不是股票基础信息接口。

### URL

```text
GET https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank
```

### 示例参数

| 参数 | 示例 |
| --- | --- |
| `l` | `10` |
| `p` | `1` |
| `t` | `01/averatio` |
| `ordertype` | 空字符串 |
| `o` | `0` |

返回样例字段：

```json
{
  "bd_name": "综合Ⅱ",
  "bd_code": "pt01801231",
  "bd_zdf": "6.83",
  "nzg_code": "sh600673",
  "nzg_name": "东阳光",
  "nzg_zdf": "10.01"
}
```

### 判断

该接口可以作为后续行业/板块热度观察的候选，但不应混入股票基础信息同步链路。

## 旧排行接口

腾讯页面前端包中仍能看到旧接口线索：

```text
https://stock.gtimg.cn/data/view/prank.php
```

历史参数示例：

```text
t=rankash/chr
t=rankasz/chr
```

2026-07-01 测试时，部分旧参数返回 `data:''`，不建议作为新实现主接口。除非 `getBoardRankList` 后续失效，否则不投入接入。

## 数据质量规则

接入腾讯接口时，建议每个任务至少写入以下质量指标，供数据中心和数据日历展示：

| 指标 | 说明 |
| --- | --- |
| `request_count` | 请求次数 |
| `success_count` | 成功请求次数 |
| `failed_count` | 失败请求次数 |
| `total_reported` | 接口声明总数，例如 `data.total` |
| `rows_fetched` | 实际获取行数 |
| `rows_valid` | 通过字段校验的行数 |
| `rows_duplicate` | 标准化后重复行数 |
| `rows_invalid` | 缺少 `code/name/datetime` 等核心字段的行数 |
| `latency_ms_p50/p95` | 响应耗时 |
| `source_timestamp` | 行情源返回的最新时间 |

## 推荐落地顺序

1. 给 `TencentQuoteSource.fetch_stock_list` 增加 `getBoardRankList` 分页实现。
2. 后台手工添加/校验股票时增加 `smartbox/search/get` 搜索接口。
3. 股票基础信息同步任务优先使用腾讯股票池，不用空值覆盖已有 `industry/list_date`。
4. 实时快照继续使用 `qt.gtimg.cn`，同时评估 `sqt.gtimg.cn/utf8` 作为备选入口，并补充批量大小和失败率监控。
5. 分钟 K 线的成交额质量单独治理：短期标注 `mkline` 的 `amount` 为估算值，中期改为由 1 分钟累计成交额聚合。
6. 把 `fqkline/get` 纳入价格、复权和成交量校验来源，但不要用它单独覆盖日线成交额。
7. 数据中心和数据日历增加腾讯接口健康指标：全量股票数、分页完整度、字段有效率、接口延迟、最近源时间。

## 未确认问题

- `getBoardRankList` 的 `state` 字段对停牌、退市、临停等状态的取值需要交易日持续采样确认。
- `getBoardRankList` 的 `count` 参数 2026-07-02 已验证 `300+` 会报错，后续仍需长期观察腾讯是否调整限制。
- 腾讯接口不是官方稳定 API，前端包版本变化可能导致参数或字段调整。
- 股票行业、上市日期等静态字段仍需要其他来源补充，腾讯当前接口不能完全替代基础资料源。
- Stockbar 没有提供腾讯日线、财务、公告、行业成分等接口线索，不能据此扩展到完整基本面数据。
- `ArSrNa/tencent-stock-api` 只封装了 `qt.gtimg.cn/q=`，没有提供腾讯日线、财务、公告、行业成分等接口线索。
- 当前项目的 `mcap/float_mcap` 腾讯字段映射疑似反向，需要单独验证并修复。
- `fqkline/get` 的历史成交量单位需要和当前日线表继续对齐验证；该接口不返回历史成交额。
- `sqt.gtimg.cn/utf8` 是否完全覆盖 `qt.gtimg.cn` 的全部市场和字段，需要在全市场批量任务中继续观察。
