# mootdx 数据源说明

最后验证日期：2026-07-09

本项目将 `mootdx` 作为可选行情数据源使用。它适合评估通达信行情服务器和补充数据可用性，但目前还没有加入 `DataAggregator()` 的默认 fallback 链路。

## 安装

`mootdx` 放在 `market` 可选依赖组中：

```bash
uv sync --extra market
```

当前固定版本为 `mootdx==0.11.7`。该包声明支持 Python `>=3.8,<4.0`；本项目已在 Python 3.13.5 环境中安装并验证。

## 可获取的数据类型

根据官方文档和当前小样本实测，`mootdx` 可获取的数据分为线上行情、线上扩展信息、财务数据和本地通达信文件读取四类。

### 线上标准行情

通过 `Quotes.factory(market="std")` 获取，当前项目优先评估这一类：

| 数据类型 | mootdx 接口 | 当前项目状态 | 说明 |
| --- | --- | --- | --- |
| 股票实时行情 | `quotes(symbol=[...])` | 已适配 | 支持多股票批量请求，输出价格、开盘、昨收、最高、最低、成交量、成交额等字段 |
| 股票列表/数量 | `stocks(market=...)`, `stock_count(market=...)` | 已适配 | 支持深市、沪市、北交所市场代码；项目返回前会过滤普通 A 股代码前缀 |
| 股票 K 线 | `bars(symbol, frequency, start, offset)` | 已适配 | 支持 1m、5m、15m、30m、60m、日线、周线、月线等；项目当前统一适配日线和分钟 OHLCV |
| 指数 K 线 | `index(symbol, frequency, start, offset)` | 已适配离线落库 | 可取上证指数等指数 K 线；当前不接入项目统一行情接口 |
| 历史分时 | `minutes(symbol, date=...)` | 已适配扩展探测 | 官方建议优先使用该接口替代 `minute()` |
| 实时分时 | `minute(symbol)` | 已适配扩展探测 | 官方文档提到该接口曾有数据异常反馈，不作为项目主路径 |
| 分笔成交 | `transaction(symbol, start, offset)` | 已适配扩展探测 | 当前分笔，接口最多返回一定数量记录 |
| 历史分笔成交 | `transactions(symbol, date, start, offset)` | 已适配扩展探测 | 指定日期分笔数据 |
| 除权除息 | `xdxr(symbol)` | 已适配离线落库 | 返回分红、配股、送转、股本变化等信息 |
| 公司资料目录 | `F10C(symbol)` | 已适配扩展探测 | 可获取 F10 资料标题目录 |
| 公司资料详情 | `F10(symbol, name)` | 已适配扩展探测 | 根据 `F10C` 的标题读取详情正文 |
| 区间 OHLC | `k(symbol, begin, end, adjust)`, `ohlc(...)` | 未适配 | 支持不复权、前复权 `qfq`、后复权 `hfq` |

### 财务数据

`mootdx` 有两类财务相关能力：

| 数据类型 | mootdx 接口 | 当前项目状态 | 说明 |
| --- | --- | --- | --- |
| 个股财务摘要 | `Quotes.finance(symbol)` | 已适配离线落库 | 返回股本、资产、收入、利润、每股净资产等字段 |
| 历史专业财务文件列表 | `Affair.files()` | 已适配扩展探测 | 返回 `gpcw*.zip` 文件名、哈希、大小 |
| 历史专业财务文件下载 | `Affair.fetch(downdir, filename)` | 未适配 | 下载通达信专业财务数据文件 |
| 本地专业财务文件解析 | `Affair.parse(downdir, filename)` | 未适配 | 解析 `.zip` 或 `.dat` 财务文件为 DataFrame |

### 本地通达信数据读取

通过 `Reader.factory(market="std", tdxdir="...")` 读取本机通达信目录，适合已有本地 `vipdoc` 数据的场景：

| 数据类型 | mootdx 接口 | 当前项目状态 | 说明 |
| --- | --- | --- | --- |
| 本地日线 | `Reader.daily(symbol)` | 未适配 | 读取 `vipdoc/{sz,sh}/lday/*.day` |
| 本地 1 分钟/5 分钟线 | `Reader.minute(symbol, suffix="1" 或 "5")` | 未适配 | 读取通达信本地分钟文件，支持 `.1/.5` 和 `.lc1/.lc5` 格式 |
| 本地 5 分钟时间线 | `Reader.fzline(symbol)` | 未适配 | 读取本地 5 分钟数据 |
| 板块信息 | `Reader.block(symbol, group=...)` | 未适配 | 读取通达信板块文件 |
| 自定义板块 | `Reader.block_new(...)` | 未适配 | 读取或写入自定义板块 |

### 暂不建议使用的能力

- 扩展市场 `Quotes.factory(market="ext")`：官方文档标注“扩展市场目前已经失效无法使用”，第一版不接入。
- `minute(symbol)`：官方文档提到该接口曾有异常反馈；项目只在 probe 中与 `minutes()` 对比，不作为主路径。
- `stocks()` 原始返回：通达信股票目录包含指数、分类和其他非普通股票条目；项目使用前必须过滤。

## 项目适配器

直接使用 `MootdxSource`：

```python
from datetime import date

from src.data.mootdx_source import MootdxSource

source = MootdxSource(bestip=False, timeout=15)
quotes = source.fetch_realtime_quotes(["000001.SZ", "600519.SH"])
bars = source.fetch_intraday_bars("000001.SZ", date(2026, 7, 9), "5m")
daily = source.fetch_bars("000001.SZ", date(2026, 7, 1), date(2026, 7, 9))
```

适配器会统一输出项目现有字段：

- 实时行情：`symbol, price, open, prev_close, high, low, volume, amount, change_pct, timestamp`
- 日线：`date, open, high, low, close, volume, amount, adjusted_close, symbol`
- 分钟线：`datetime, time, symbol, open, high, low, close, volume, amount`

为了便于评估数据源，还额外暴露以下 probe 专用方法：

- `fetch_minutes(symbol, trade_date)`：调用 `client.minutes(...)`
- `fetch_realtime_minute(symbol)`：调用 `client.minute(...)`
- `fetch_transactions(symbol, trade_date=None)`
- `fetch_xdxr(symbol)`
- `fetch_finance_frame(symbol)`
- `fetch_index_bars(symbol="000001", frequency="daily")`
- `fetch_f10_catalog(symbol)`
- `fetch_f10_detail(symbol, title)`
- `fetch_affair_files()`

## ClickHouse 离线同步

当前项目已经增加独立离线同步入口，只写 `mootdx_*` 表，不写入现有生产表，也不修改 `DataAggregator()` 默认数据源顺序。

脚本入口：

```bash
python scripts/sync_mootdx_clickhouse.py \
  --symbols 000001.SZ,600519.SH \
  --trade-date 2026-07-09 \
  --tasks stock_catalog,quote_snapshot,stock_kline_daily,stock_kline_intraday,index_kline,xdxr,finance_snapshot \
  --frequencies 5m,daily \
  --limit 2
```

默认采集任务：

| 任务 key | 数据内容 | 目标表 |
| --- | --- | --- |
| `stock_catalog` | 股票目录，按解析后的股票池过滤 | `mootdx_stock_catalog` |
| `quote_snapshot` | 实时行情快照 | `mootdx_quote_snapshots` |
| `stock_kline_daily` | 股票日 K | `mootdx_stock_kline` |
| `stock_kline_intraday` | 股票分钟 K，默认 `5m` | `mootdx_stock_kline` |
| `index_kline` | 指数 K 线，默认上证指数、深证成指、创业板指 | `mootdx_index_kline` |
| `xdxr` | 除权除息事件 | `mootdx_xdxr` |
| `finance_snapshot` | 个股财务摘要 | `mootdx_finance_snapshot` |
| 每次运行 | 同步参数、结果、失败信息 | `mootdx_sync_runs` |

扩展探测任务：

| 任务 key | 数据内容 | 目标表 |
| --- | --- | --- |
| `minutes_probe` | 指定交易日历史分时 | `mootdx_minutes` |
| `realtime_minute_probe` | 实时分时 | `mootdx_minutes` |
| `transaction_probe` | 当前分笔成交 | `mootdx_transactions` |
| `historical_transaction_probe` | 指定交易日历史分笔成交 | `mootdx_transactions` |
| `f10_catalog_probe` | F10 资料目录 | `mootdx_f10_catalog` |
| `f10_detail_probe` | F10 资料详情，默认每只股票取前 3 个目录标题 | `mootdx_f10_detail` |
| `affair_file_list_probe` | 通达信专业财务文件列表，只记文件名、哈希和大小 | `mootdx_affair_files` |

隔离边界：

- 不写 `stocks`、`daily_kline`、`minute5_kline`、`stock_quote_snapshots`、`stock_quote_snapshots_1m`、`stock_quote_snapshots_5m`。
- 不进入今日尾盘选股、数据中心质量矩阵或生产维护任务。
- 不默认下载 `Affair.fetch()` 财务压缩包。
- 不使用官方标注失效的 `market="ext"`。

### ClickHouse 小样本实跑结果

实跑命令：

```bash
python scripts/sync_mootdx_clickhouse.py \
  --symbols 000001.SZ \
  --trade-date 2026-07-09 \
  --tasks stock_catalog,quote_snapshot,stock_kline_daily,stock_kline_intraday,index_kline,xdxr,finance_snapshot \
  --frequencies 5m,daily \
  --limit 1
```

实跑结果：`failed={}`，耗时约 65 秒，写入统计如下：

| 表 | 本次写入行数 |
| --- | ---: |
| `mootdx_stock_catalog` | 1 |
| `mootdx_quote_snapshots` | 1 |
| `mootdx_stock_kline` | 49 |
| `mootdx_index_kline` | 4800 |
| `mootdx_xdxr` | 79 |
| `mootdx_finance_snapshot` | 1 |

注意：`mootdx_index_kline` 会返回较长跨度指数历史数据。ClickHouse 对单次 INSERT 跨分区数量有限制，因此同步模块对股票和指数 K 线按 `(trade_date, frequency)` 分批写入。

## 频率映射

官方文档和 `mootdx==0.11.7` 都支持数字和字符串两种 K 线频率。项目适配器使用字符串别名：

| 项目频率 | mootdx 参数 | 含义 |
| --- | --- | --- |
| `1m` | `1m` | 1 分钟 K 线 |
| `5m` | `5m` | 5 分钟 K 线 |
| `15m` | `15m` | 15 分钟 K 线 |
| `30m` | `30m` | 30 分钟 K 线 |
| `60m` | `1h` | 60 分钟 K 线 |
| `daily` | `day` | 日 K 线 |

官方文档提到 `minute()` 曾有数据异常反馈，并建议使用 `minutes()` 替代。因此项目适配器用 `bars(..., frequency=...)` 获取 OHLC 分钟 K 线；`minutes()` 和 `minute()` 仅保留给离线探测脚本做对比。

## 离线探测脚本

运行小样本可用性和延迟探测：

```bash
python scripts/probe_mootdx_source.py \
  --symbols 000001.SZ,600519.SH,300750.SZ \
  --frequencies 1m,5m,15m,30m,60m,daily \
  --rounds 2 \
  --sleep-grid 0,0.2,0.5 \
  --trade-date 2026-07-09 \
  --output-dir reports/mootdx_probe
```

输出文件：

- `reports/mootdx_probe/latest.json`
- `reports/mootdx_probe/latest.csv`

每条结果会记录数据类型、股票代码、频率、请求前 sleep 间隔、是否成功、行数、字段列表、首尾时间、延迟和错误信息。

可用 `--bestip` 让 `mootdx` 重新测试最快行情服务器。测试后也可以用 `--server host:port` 固定指定服务器。

## 当前小样本实测结果

命令：

```bash
python scripts/probe_mootdx_source.py \
  --symbols 000001.SZ \
  --frequencies 1m,5m,15m,30m,60m,daily \
  --rounds 1 \
  --sleep-grid 0 \
  --trade-date 2026-07-09 \
  --output-dir reports/mootdx_probe \
  --timeout 10
```

实测时间：2026-07-09 14:43-14:45 左右，中国时区。

| 数据类型 | 结果 |
| --- | --- |
| `realtime_quotes` | 1 行，最新时间约 `14:43`，延迟约 47 ms |
| `minutes` | 224 行，延迟约 199 ms |
| `realtime_minute` | 224 行，延迟约 202 ms |
| `transaction` | 80 行，延迟约 203 ms |
| `xdxr` | 79 行，延迟约 204 ms |
| `daily_bars` | 当前交易日 1 行，延迟约 219 ms |
| `1m` K 线 | 224 行，最新约 `14:44`，延迟约 215 ms |
| `5m` K 线 | 45 行，最新约 `14:45`，延迟约 199 ms |
| `15m` K 线 | 15 行，最新 `14:45`，延迟约 208 ms |
| `30m` K 线 | 8 行，最新 `15:00`，延迟约 202 ms |
| `60m` K 线 | 4 行，最新 `15:00`，延迟约 202 ms |
| `index_bars` | 测试频率均返回 800 行 |
| `stock_list` | 过滤后 SZ/SH A 股 5,204 行，延迟约 4.3 s |

结论：

- 单只股票的在线 K 线请求速度足够用于定向 fallback 评估。
- 通达信原始股票目录包含大量非普通股票条目；`MootdxSource` 返回 `StockInfo` 前会先按已知 A 股代码前缀过滤。
- 目前证据支持将 `mootdx` 作为显式研究源和备选 fallback 候选，不建议直接作为默认生产数据源。

## 使用过的官方文档

- Gitee 文档目录：`https://gitee.com/ibopo/mootdx/tree/master/docs`
- 标准行情接口：`docs/api/quote1.md`
- 离线 Reader 接口：`docs/api/reader.md`
- 快速上手：`docs/quick.md`
- 最优服务器 CLI：`docs/cli/bestip.md`
- 财务数据接口：`docs/api/affair.md`
