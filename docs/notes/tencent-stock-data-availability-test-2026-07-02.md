# 腾讯股票数据接口可用性测试报告

## 测试目标

基于 `docs/notes/tencent-stock-data-interfaces.md` 中整理的接口，做一轮小流量真实请求测试，判断每个接口是否适合作为项目主链路、备选链路或仅用于校验。

测试时间：2026-07-02 10:25-10:27，A 股盘中。

## 结论

| 场景 | 最佳使用方式 | 结论 |
| --- | --- | --- |
| 全 A 股票池 | `getBoardRankList`，`count=100` 或 `200` 分页 | 可作为股票池主候选 |
| 实时行情 | 优先评估 `sqt.gtimg.cn/utf8`，保留 `qt.gtimg.cn` 兜底 | UTF-8 入口小样本更快，字段一致 |
| 股票搜索 | `smartbox/search/get` | 适合手工搜索和代码校验，不适合全量同步 |
| 当日 1m 分时 | `minute/query` | 沪深 A 股和港股可用，北交所可能缺累计成交额 |
| 分钟 K 线 | `mkline`，项目主用 `m5` | `m1/m5/m15/m30/m60` 均可用，但成交额需估算 |
| 日/周/月 K 线 | `fqkline/get` | 可做价格/复权/成交量校验，不能替代日线成交额 |
| 板块排行 | `mktHs/rank` | 可做板块热度，不能做股票池 |

## 股票池接口

接口：

```text
https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList
```

参数：

```text
_appver=11.17.0
board_code=aStock
sort_type=priceRatio
direct=down
offset=0
count=100
```

测试结果：

| count | 结果 | 说明 |
| --- | --- | --- |
| `100` | 成功 | 返回 100 行，约 206ms |
| `150` | 成功 | 返回 150 行，约 215ms |
| `200` | 成功 | 返回 200 行，约 253ms |
| `300` | 失败 | `参数错误:count too large` |
| `400` | 失败 | `参数错误:count too large` |
| `500` | 失败 | `参数错误:count too large` |

分页测试：

- `offset=0/100/200/300/400/500/1000/3000` 均正常返回 100 行。
- `offset=5500` 返回 30 行。
- 2026-07-02 接口声明 `total=5530`。

最佳使用：

1. 使用 `count=100` 或 `count=200`。
2. 按 `offset += count` 分页，直到累计条数达到 `total` 或返回空。
3. 每页校验 `code=0`、`data.rank_list` 为数组。
4. 标准化后按 `symbol` 去重。

## 实时行情接口

测试接口：

```text
https://qt.gtimg.cn/q={symbols}
https://sqt.gtimg.cn/utf8/q={symbols}
```

样本：从股票池接口前 8 页取 789 只 A 股样本。

结果：

| endpoint | 请求数 | 返回数 | bad_rows | 延迟 |
| --- | --- | --- | --- | --- |
| `qt` | 10 | 10 | 0 | 223.5ms |
| `qt` | 50 | 50 | 0 | 230.7ms |
| `qt` | 100 | 100 | 0 | 317.4ms |
| `qt` | 300 | 300 | 0 | 537.5ms |
| `qt` | 789 | 789 | 0 | 937.0ms |
| `sqt_utf8` | 10 | 10 | 0 | 131.6ms |
| `sqt_utf8` | 50 | 50 | 0 | 147.8ms |
| `sqt_utf8` | 100 | 100 | 0 | 171.4ms |
| `sqt_utf8` | 300 | 300 | 0 | 197.0ms |
| `sqt_utf8` | 789 | 789 | 0 | 254.7ms |

字段长度：

- 样本返回字段长度为 87 或 88。
- 类型包含 `GP`、`GP-A`、`GP-A-CYB`、`GP-A-KCB`。

最佳使用：

1. 新实现优先评估 `sqt.gtimg.cn/utf8`，减少 GBK 解码风险。
2. 保留 `qt.gtimg.cn` 作为兜底。
3. 批量大小建议先设 `300-800`，上线后按失败率和延迟动态调整。
4. 字段解析不能强制要求固定 88 列，应按最小必要字段校验。

## 股票搜索接口

接口：

```text
https://proxy.finance.qq.com/ifzqgtimg/appstock/smartbox/search/get?q={keyword}
```

测试结果：

| 查询词 | 结果 |
| --- | --- |
| `平安银行` | 返回 `sz000001` |
| `000001` | 返回股票、指数、基金 |
| `腾讯` | 返回港股、美股 ADR、A 股相关结果 |
| `AAPL` | 返回美股 |
| `浦发银行` | 返回 `sh600000` |
| `海达尔` | 返回 `bj920699`、`bj836699` |

最佳使用：

1. 只用于手工搜索、代码校验和后台交互。
2. 不能用于全量股票池同步。
3. A 股过滤不能只看 `type=GP-A`，北交所可能是 `market=bj` 且 `type=GP`。
4. 必须排除 `ZS` 指数、`KJ` 基金等非股票类型。

## 当日 1m 分时

接口：

```text
https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}
```

测试结果：

| symbol | rows | 单行列数 | 首行 |
| --- | --- | --- | --- |
| `sz000001` | 57 | 4 | `0930 10.20 17257 17602140.00` |
| `sh600000` | 57 | 4 | `0930 8.71 6379 5556109.00` |
| `bj920699` | 57 | 3 | `0930 94.00 476` |
| `hk00700` | 57 | 4 | `0930 442.600 2983792 1319013744.200` |

JSON 和 JSONP 两种形式都可用。

最佳使用：

1. 沪深 A 股使用累计成交量、累计成交额差分生成分钟量额。
2. 港股可复用同样逻辑，但需要按港股交易时间处理。
3. 北交所样本缺累计成交额，不能直接生成真实分钟成交额。
4. 解析时按列数分支，不能强制要求 4 列。

## 多周期分钟 K 线

接口：

```text
https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sz000001,{period},,5
```

测试结果：

| period | rows | 首条时间 | 结构 |
| --- | --- | --- | --- |
| `m1` | 5 | `202607021022` | `[datetime, open, close, high, low, volume, {}, turnover_pct]` |
| `m5` | 5 | `202607021010` | 同上 |
| `m15` | 5 | `202607011500` | 同上 |
| `m30` | 5 | `202607011400` | 同上 |
| `m60` | 5 | `202607011030` | 同上 |

最佳使用：

1. 项目主链路继续使用 `m5`。
2. `m1` 可用于补历史窗口，但当日真实成交额仍优先取 `minute/query`。
3. `mkline` 没有直接返回真实成交额，当前 `amount=close*volume*100` 只能标为估算。

## 日/周/月复权 K 线

接口：

```text
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},{period},,{endDate},{count},{fq}
```

测试结果：

| symbol | period | fq | 返回 key |
| --- | --- | --- | --- |
| `sz000001` | `day/week/month` | `qfq` | `qfqday/qfqweek/qfqmonth` |
| `sz000001` | `day/week/month` | `hfq` | `hfqday/hfqweek/hfqmonth` |
| `sh000001` | `day/week/month` | `qfq/hfq` | `day/week/month` |
| `hk00700` | `day/week/month` | `qfq/hfq` | `day/week/month` |

最佳使用：

1. 沪深 A 股可用于前复权、后复权价格校验。
2. 指数和港股不返回 `qfqday/hfqday` 这类 key，而是直接返回 `day/week/month`。
3. 港股日/周 K 线可能在第 6 位携带回购等公司行动对象。
4. 该接口不返回历史成交额，不能作为日线主数据源。

## 板块排行接口

接口：

```text
https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank
```

测试结果：

- `o=0`、`o=1` 均可返回 10 条板块排行。
- 返回字段包括板块名称、板块代码、板块涨跌幅、领涨股票代码和名称。

最佳使用：

1. 可作为板块热度、市场温度或行业情绪参考。
2. 不适合股票池同步。
3. 行业分类体系需要单独确认，不能直接等同申万行业。

## 推荐落地策略

1. 股票池：`getBoardRankList count=100/200` 分页。
2. 实时行情：优先试运行 `sqt.gtimg.cn/utf8`，保留 `qt.gtimg.cn` 兜底。
3. 盘中 1m：沪深 A 股用 `minute/query`，北交所金额缺失时标记为不可用或估算。
4. 5m：继续 `mkline m5`，但金额字段标注为估算。
5. 日线：腾讯 `fqkline` 只做价格/复权/成交量校验，不替代主日线源。
6. 搜索：`smartbox` 只用于后台交互，不参与全量同步。
7. 数据质量：每个任务记录请求次数、成功率、行数、字段完整率、延迟、源时间。
