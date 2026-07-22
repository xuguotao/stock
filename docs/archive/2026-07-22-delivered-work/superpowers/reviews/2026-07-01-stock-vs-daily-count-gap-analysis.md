# 股票总数与日线覆盖数差异分析

## 背景

数据中心模块的仪表盘上,`股票基础信息` 显示 5207,`股票日线` 显示 4960,差 247。直觉上像"日线丢了 247 只股票"。本文记录一次系统化排查的结论。

排查日期:2026-07-01。数据源:ClickHouse `stock` 库(`STOCK_CLICKHOUSE_HOST`)。所有数字均来自对线上库的直接查询,非推断。

## 结论先行

**不是日线丢了 247 只,而是两个数字的口径不同,叠加一个真实的管道缺口。**

| 数字 | 含义 | 计算来源 |
|---|---|---|
| **5207** | `stocks` 表全部行数(含 ST、退市、停牌、正常股,无任何过滤) | `_clickhouse_stock_summary` → `select count() from stocks` |
| **4960** | 最新交易日(2026-06-30)有日线 bar 的**非 ST** 股票数 | `_latest_symbol_count(..., non_st_only=True)`,见 `src/web/backend/data_status.py` 约第 657 行 |

`daily_kline` 表实际有 **5207 个不同 symbol**,最新日(2026-06-30)也有 **5207 个 symbol 的 bar**。日线一条没丢。4960 是仪表盘对"日线覆盖"刻意用非 ST 口径算的,本来就不该等于 5207。

## 247 的拆解

```
5207 - 4960 = 247 = 229(ST 股) + 18(非 ST 但 06-30 无 bar)
```

| 类别 | 数量 | 是否问题 |
|---|---|---|
| ST / *ST 股 | 229 | 指标设计如此(`non_st_only=True` 排除 ST)。但见下文"真实问题" |
| 退市股(名称含"退市") | 7(含在 18 内) | 正常,已退市不再交易(600193 退市创兴、605081 退市太和、600608 退市沪科等,last_bar=2026-06-29) |
| 近期停牌非 ST | 11(含在 18 内) | 正常,06-25 / 06-26 起停牌(日科化学、好利科技、陕鼓动力、拓荆科技等) |

18 个非 ST 是真的当日没交易,属合理。

## 真实问题:229 只 ST 的日线在 2026-06-17 之后全部冻结

证据链(逐步查证):

1. 全部 229 只 ST 股的最后一条日线都是 `2026-06-17`,06-17 之后 ST 日线 = 0 条。
2. 日线入库路径是 `sync_clickhouse_daily_from_minute5`(`src/data/clickhouse_daily_sync.py:19`),由 `scripts/run_daily_maintenance.py` 和 `src/web/backend/app.py` 作为 `daily_repair_runner` 调用——**日线由 5 分钟线聚合派生**。
3. 5 分钟线入库 `src/data/minute5_sync.py:27` 与 `src/data/clickhouse_minute5_sync.py:28` 的默认是 `include_st: bool = False`。
4. 实测 `minute5_kline`:06-16 / 06-17 / 06-26 / 06-30 的 ST 覆盖全是 0;非 ST 正常(4960~4969)。
5. 但 06-17 及之前 `daily_kline` 有 ST bar(229 只,直到 06-17)。说明 06-17 之前 ST 日线来自别的源(akshare `stock_zh_a_hist`,含 ST),06-17 前后切到"5m 聚合"为主路径,而 5m 默认不收 ST,ST 日线就此断流。
6. 库内存在 `daily_kline_backup_20260623_fix` 备份表,印证 06-23 前后动过日线管道。

**根因**:日线管道改为从 5 分钟线派生后,5 分钟线 `include_st=False` 的默认值让 ST 既拿不到 5m 数据,也拿不到派生日线。

> 注意:这不影响仪表盘的 4960(ST 本就被指标排除),但 `stocks` 表里这 229 只 ST 的日线数据停在 06-17。任何下游若读 ST 日线,读到的都是陈旧数据。

## 复核查询

```sql
-- 两个口径的来源
select count() from stocks;                                    -- 5207
select max(date), uniqExact(symbol) from daily_kline;          -- 最新日 + 全量 symbol(均为 5207)

-- 4960 = 最新日有 bar 的非 ST(与仪表盘口径一致)
select uniqExact(k.symbol)
from daily_kline k
inner join stocks s on k.symbol = s.symbol
where k.date = '2026-06-30'
  and not match(upper(s.name), '^(\*ST|S\*ST|SST|ST)([^A-Z]|$)');

-- ST 冻结点:06-17 之后 ST 日线为 0
select countDistinct(symbol) from daily_kline
where date > '2026-06-17'
  and symbol in (select symbol from stocks s
                 where not match(upper(s.name), '^(\*ST|S\*ST|SST|ST)([^A-Z]|$)'));
```

## 处理建议

1. **若策略确实不碰 ST**:247 里的 229 是预期内的,仪表盘 4960 是对的。建议在 UI 上为"股票基础信息(5207)"和"股票日线(4960)"标注口径(非 ST / 最新日),避免下次又误判成丢数据。

2. **若需要 ST 日线**,三选一:
   - 5m 同步开 `include_st=True`(影响面最大,5m 也会开始收 ST);
   - 单独跑 `daily_history_backfill`(akshare `stock_zh_a_hist`)给 ST 补日线,不碰 5m;
   - 在 `sync_clickhouse_daily_from_minute5` 之外,保留一条 akshare 日线通道专门覆盖 ST。

3. 18 只非 ST(退市 / 停牌)无需处理。
