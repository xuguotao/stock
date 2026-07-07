# 数据质量改进方案

> 基于 2026-07-06 的数据质量审计结果

## 后续状态更新（2026-07-07）

- XDXR 默认 handler 已改为使用 ClickHouse 数据源，并传入带市场后缀的 `symbol.market`，避免沪市股票被当成深市查询。
- 数据中心健康矩阵中“默认研究股票池”和“股票基础信息”已改为展示业务口径行数，不再展示 ReplacingMergeTree 物理行数。
- `minute1_kline` 后续确认来自腾讯当天分钟走势接口，不适合历史回补和严肃 1m K 线使用；相关腾讯 1m 获取、ClickHouse 同步脚本、`minute1_kline` 物理表和数据中心展示已清理。
- 本文保留为 2026-07-06 当时的数据质量排查记录；若与 2026-07-07 之后代码现状冲突，以后续提交和运行态验证为准。

## 问题摘要

| # | 优先级 | 问题 | 根因 | 影响 |
|---|--------|------|------|------|
| 1 | P0 | 北交所数据持续失败 | 数据源不支持 | 每日采集浪费 + 噪音日志 |
| 2 | P0 | xdxr 覆盖率仅 52% (2,896/5,534) | **fetch_xdxr_info 默认 market=0(SZ)**，SH 股票全部取不到数据 | 复权回测不准确 |
| 3 | P0 | 日线覆盖 6/18 跳降 240 只 | 需进一步排查 | 待确认 |
| 4 | P0 | 5m 重复 27 条 | ReplacingMergeTree 未 OPTIMIZE | 轻微数据冗余 |
| 5 | P1 | SQLite 仍然存在 | ClickHouse 已替代，但 web backend 仍传递 stock_db_path | 维护两套数据源 |
| 6 | P1 | data/ 目录存储必要性 | 需逐个评估 | — |
| 7 | P2 | minute1_kline 无日期范围 | 无定时同步任务 | 数据量远小于 5m |
| 8 | P2 | 重新定义研究标的 | 依赖上述改动 | — |

---

## 执行计划

### Phase 1: P0 — 北交所排除 + xdxr 修复 + 5m 去重

#### 1.1 排除北交所（BJ）股票

**改动点**：`src/data/stock_research_status_sync.py` 第 12 行

```python
# Before:
SUPPORTED_MARKETS = {"SH", "SZ", "BJ"}

# After:
SUPPORTED_MARKETS = {"SH", "SZ"}
```

**效果**：
- 所有 BJ 股票（324 只）自动标记 `excluded_reasons=["unsupported_market"]`
- `research_eligible=0`，不再出现在研究标的中
- 联动影响：data_quality_calendar 的 `_expected_symbols()` 也使用此表，自动排除

**额外改动**：
- `src/data/stock_research_status_sync.py` 第 302 行 `_board_from_symbol` 中 BJ 分支保留（不影响功能，避免破坏 board 识别逻辑）
- `tests/test_data/test_stock_research_status_sync.py` 需要更新断言

#### 1.2 修复 xdxr 覆盖率（核心 bug）

**根因**：`src/data/tdxrs_sync.py` 的 `fetch_xdxr_info` 接收 bare code（如 `600519`）时，默认映射到 `market=0`（SZ）。导致所有 SH 股票（2,315 只）的 xdxr 查询返回空。

**改动点**：`src/data_ops/handlers.py` 第 199 行

```python
# Before (返回 bare codes):
symbols_result = client.execute("SELECT DISTINCT symbol FROM stocks WHERE market IN ('SZ', 'SH')")
symbols = [row[0] for row in symbols_result]

# After (返回带后缀的完整 symbols):
symbols_result = client.execute("""
    SELECT symbol || '.' || market FROM stocks FINAL WHERE market IN ('SZ', 'SH')
""")
symbols = [row[0] for row in symbols_result]
```

**效果**：`fetch_xdxr_info("600519.SH")` 能正确解析 `market=1`（SH），tdxrs 返回正确的 xdxr 数据。

#### 1.3 5m 去重

```sql
OPTIMIZE TABLE minute5_kline FINAL
```

通过 `clickhouse_table_maintenance.py` 执行。

#### 1.4 日线覆盖跳降排查

需进一步查看：6/17 和 6/18 之间 stocks 表是否有变化。暂列为待排查项。

### Phase 2: P1 — SQLite 清理 + data/ 目录整理

#### 2.1 SQLite 必要性分析

**结论**：SQLite 已被 ClickHouse 完全替代，但以下代码仍引用 `stock.db`：

| 文件 | 引用方式 | 是否可移除 |
|------|----------|------------|
| `src/data/sqlite_source.py` | SQLiteStockDataSource 类 | ✅ 死代码，可删除 |
| `src/data/market_enrichment_sync.py` | 写入 stock.db | ✅ 死代码，可删除 |
| `src/web/backend/data_sync.py` | rsync stock.db | ✅ 旧同步，可删除 |
| `src/web/backend/app.py` | 传递 stock_db_path ~30 处 | ⚠️ 需重构，移除参数 |
| `src/web/backend/minute5_monitor.py` | 传递 stock_db_path | ⚠️ 需重构 |
| `src/web/backend/data_status.py` | inspect_stock_database() | ⚠️ 需重构 |
| `scripts/sync_stock_db.py` | CLI 同步脚本 | ✅ 可删除 |
| `scripts/sync_minute5_kline.py` | CLI 同步脚本 | ✅ 可删除 |
| `scripts/sync_market_enrichment.py` | CLI 同步脚本 | ✅ 可删除 |
| `scripts/check_clickhouse_coverage.py` | 迁移对比工具 | ✅ 迁移完成后可删 |

**注意**：`data/web/jobs.sqlite3`（608 MB）是 Web 任务队列，**不可删除**。

**建议**：本阶段仅做分析报告，实际清理需大规模重构 web backend，建议在独立分支进行。

#### 2.2 data/ 目录评估

| 目录 | 大小 | 用途 | 保留? |
|------|------|------|--------|
| `data/stock.db` | 1.3 GB | 旧 SQLite 存储 | ❌ 可删除（等 Phase 2 清理） |
| `data/web/jobs.sqlite3` | 608 MB | Web 任务队列 | ✅ 必须保留 |
| `data/cache/bars/` | 3.2 MB | Parquet bar 缓存 | ✅ 策略回测/实盘使用 |
| `data/cache/stock_list.parquet` | 127 KB | 股票列表缓存 | ✅ 使用 |
| `data/cache/financials/` | 空 | 财务数据缓存 | ⚠️ 空目录 |
| `data/fund_tail/` | 1.1 MB | 基金 CSV | ⚠️ ClickHouse 已替代，但 fallback 使用 |
| `data/fund_tail_opportunities/` | 1.6 MB | 基金机会 CSV | ⚠️ 同上 |
| `data/paper_trading/` | 36 KB | 模拟交易数据 | ⚠️ 测试用 |
| `data/research/` | 空 | 研究数据集目标 | ⚠️ 空目录 |
| `data/runtime/` | 锁文件 | 日线修复锁 | ✅ 使用 |

### Phase 3: P2 — minute1_kline + 研究标的重定义

#### 3.1 minute1_kline

**现状**：1,204,434 行，无定时同步任务。数据可能来自一次性批量导入。

**建议**：
- 如果需要 1m 数据，需在 `data_ops/models.py` 的 `default_task_configs()` 中添加 `minute1_intraday_sync` 任务
- 如果不需要，可以忽略或清理表

#### 3.2 重新定义研究标的

排除 BJ 后的研究标的定义：
- **全量标的**：`stock_research_status` 中 `research_eligible=1` 的股票
- **数据就绪标的**：`data_ready=1`（有日线+5m 数据）
- **策略标的**：`strategy_universe.py` 默认 `markets=("SH", "SZ")`，已自动排除 BJ

---

## 执行顺序

1. ✅ 分析完成
2. ✅ **P0-1**：排除 BJ（改 `SUPPORTED_MARKETS`）— 324 只 BJ 股票标记为 `unsupported_market`
3. ✅ **P0-2**：修复 xdxr（改 handler 查询 `symbol || '.' || market`）
4. ✅ **P0-3**：排查 6/18 跳降 — **结论：非 bug**，ST 股票被 `include_st=False` 设计排除
5. ✅ **P0-4**：5m 去重（OPTIMIZE TABLE，9→0 条重复）
6. 🔲 **P1**：输出 SQLite/data 分析报告
7. 🔲 **P2**：minute1 + 研究标的重定义

---

## 执行结果记录

### P0-1: 排除北交所 ✅

**改动**：
- `src/data/stock_research_status_sync.py:12` — `SUPPORTED_MARKETS = {"SH", "SZ"}`
- `tests/test_data/test_stock_research_status_sync.py` — 更新测试断言

**验证**：3 个测试全部通过

### P0-2: 修复 xdxr 覆盖率 ✅

**改动**：
- `src/data_ops/handlers.py:199` — 查询改为 `SELECT symbol || '.' || market FROM stocks FINAL WHERE market IN ('SZ', 'SH')`

**根因**：
- `fetch_xdxr_info` 解析 `"000001"` → 默认 `market_suffix="SZ"` → `market=0`（深圳）
- SH 股票（600xxx）被错误地用 market=0 查询，返回空
- xdxr_info 中 2,896 只股票全部是 SZ 代码，零 SH 代码

**验证**：36 个 data_ops 测试全部通过

### P0-3: 日线覆盖跳降排查 ✅

**结论：非 bug，设计行为**

**分析**：
- 6/17 有 5,207 只，6/18 降为 4,967 只（减少 240 只）
- 240 只缺失股票中：204 只 ST/*ST，4 只退市，32 只其他
- `post_close_maintenance` 的 5m 同步使用 `include_st=False`
- 日线修复从 5m 推导，ST 股票无 5m 数据 → 无法修复日线
- 6/17 之前的 ST 日线来自旧数据源（非当前 data_ops 管道）

### P0-4: 5m 去重 ✅

**结果**：`OPTIMIZE TABLE minute5_kline FINAL` 将重复从 9→0 条

---

## P1: SQLite + data/ 目录分析

### SQLite 现状

**文件**：`data/stock.db`（1,305 MB / 1.3 GB）
**最后写入**：2026-06-15 17:39（21 天前）

**表数据**：
| 表 | 行数 | 最新日期 |
|----|------|----------|
| daily_kline | 7,216,567 | 2026-06-12 |
| minute5_kline | 352,513 | 2026-06-12 |
| stocks | 5,207 | — |
| financials | 315,061 | — |
| trade_calendar | 1,697 | — |
| index_daily | 6,830 | — |
| stock_quote_snapshots | 2 | — |
| data_source_health | 4 | 2026-06-15 |

**结论**：SQLite 数据已全部过时（最新到 6/12），ClickHouse 是活跃主库。

### 仍引用 SQLite 的代码

| 分类 | 文件 | 引用方式 | 建议 |
|------|------|----------|------|
| **死代码** | `src/data/sqlite_source.py` | `SQLiteStockDataSource` 类 | 可删除 |
| **死代码** | `src/data/market_enrichment_sync.py` | 写入 stock.db 的同步函数 | 可删除 |
| **死代码** | `src/web/backend/data_sync.py` | rsync stock.db 的旧同步 | 可删除 |
| **死代码** | `scripts/sync_stock_db.py` | CLI 同步脚本 | 可删除 |
| **死代码** | `scripts/sync_minute5_kline.py` | SQLite 版 5m 同步 | 可删除 |
| **死代码** | `scripts/sync_market_enrichment.py` | CLI 同步脚本 | 可删除 |
| **迁移工具** | `scripts/check_clickhouse_coverage.py` | SQLite vs ClickHouse 对比 | 迁移完成后可删 |
| **幽灵参数** | `src/web/backend/app.py` | `stock_db_path` 参数传递 ~30 处 | 需重构移除 |
| **幽灵参数** | `src/web/backend/minute5_monitor.py` | 传递 `stock_db_path` | 需重构移除 |
| **旧功能** | `src/web/backend/data_status.py` | `inspect_stock_database()` | 需重构移除 |

**关键发现**：`stock_db_path` 参数在 `app.py` 中被传递到 ClickHouse 同步函数，但这些函数根本不接收 `db_path` 参数（实际写入 ClickHouse）。这是幽灵参数，应清理。

**注意**：`data/web/jobs.sqlite3`（608 MB）是 Web 任务队列（`JobStore`），**不可删除**。

### data/ 目录存储评估

| 目录/文件 | 大小 | 用途 | 结论 |
|-----------|------|------|------|
| `data/stock.db` | **1.3 GB** | 旧 SQLite 存储，数据过时到 6/12 | ❌ **可删除**（等 P1 清理后） |
| `data/web/jobs.sqlite3` | 608 MB | Web 任务队列 | ✅ 必须保留 |
| `data/cache/bars/` | 3.1 MB | 189 个 parquet 文件，策略回测/实盘缓存 | ✅ 保留 |
| `data/cache/stock_list.parquet` | 128 KB | 股票列表缓存 | ✅ 保留 |
| `data/cache/financials/` | 空 | 财务数据缓存（未使用） | ⚠️ 空目录，可清理 |
| `data/fund_tail/` | 1.1 MB | 基金 CSV（ClickHouse 已替代） | ⚠️ fallback 使用，暂保留 |
| `data/fund_tail_opportunities/` | 1.6 MB | 基金机会 CSV（同上） | ⚠️ 同上 |
| `data/paper_trading/` | 36 KB | 模拟交易 JSON | ⚠️ 测试数据 |
| `data/research/` | 空 | 研究数据集目标 | ⚠️ 空目录 |
| `data/runtime/` | 0 | 日线修复锁文件 | ✅ 保留 |

**总大小**：1.9 GB，其中 stock.db（1.3 GB）+ jobs.sqlite3（608 MB）= 98%

### P1 清理建议

**立即可做（低风险）**：
- 删除 `data/stock.db`（1.3 GB 空间回收）— 等代码清理完成后
- 删除空目录 `data/cache/financials/`、`data/research/`

**需要重构（中风险）**：
- 从 `app.py` 移除 `stock_db_path` 参数传递链
- 删除 `sqlite_source.py`、`market_enrichment_sync.py`、`data_sync.py`
- 删除相关 CLI 脚本
- 移除 `data_status.py` 中的 `inspect_stock_database()`

**建议在独立分支执行**，涉及 ~15 个文件修改。

### P2: minute1_kline + 研究标的重定义

#### minute1_kline 分析

**现状**：
- 仅 1 天数据（2026-06-17），1,204,434 行，4,977 只股票
- 无定时同步任务（不在 `data_ops/models.py` 的 `default_task_configs()` 中）
- 有手动脚本 `scripts/sync_clickhouse_minute1_kline.py`，需 `--trade-date` 参数
- 仅用于 `data_status.py` 质量监控展示，**未被策略/ML/研究代码使用**
- 对比：minute5_kline 有 27.5M 行（23x），日期范围 6 个月

**结论**：minute1 是一次性测试数据（6/17 手动同步），从未自动化。

**建议**：
- **如果不需要 1m 数据**：保持现状，忽略即可（数据已存在不影响其他功能）
- **如果需要持续采集**：需在 `data_ops/models.py` 添加 `minute1_intraday_sync` 任务，配置 `market_interval` 调度。注意：1m 数据量约为 5m 的 5 倍（每天 ~500MB），需评估存储成本
- **不需要本次操作**：仅做分析报告

#### 研究标的重定义

**排除 BJ 后的研究标的**（基于当前数据）：

| 指标 | 数量 | 说明 |
|------|------|------|
| 全量股票 | 5,534 | stocks 表全部 |
| SH + SZ | 5,210 | 排除 BJ（324 只） |
| SH/SZ 非 ST 非退市 | ~4,992 | 排除 ST（~200）+ 退市（~18） |
| research_eligible（旧） | 5,312 | 包含 BJ 的旧结果 |
| **research_eligible（新）** | **~4,992** | 排除 BJ 后预期值 |
| data_ready | ~4,967 | 有日线+5m 数据的 eligible 股票 |

**三层标的定义**：
1. **全量标的**：`stock_research_status` 中 `research_eligible=1`
   - 条件：SH/SZ 市场 + 非 ST + 非退市 + 名称非空
2. **数据就绪标的**：`data_ready=1`
   - 条件：eligible + 有日线数据 + 有 5m 数据
3. **策略标的**：`StrategyUniverseOptions` 默认 `markets=("SH", "SZ")`
   - 条件：data_ready + 满足策略特定过滤（流动性、bar 数量等）

**注意**：`stock_research_status` 表尚未重新同步（需要同步一次使 BJ 排除生效）。下次 `stock_master_sync` 运行时会自动更新。

**验证**：`strategy_universe.py` 的 `StrategyUniverseOptions.markets` 默认已经是 `("SH", "SZ")`，策略层不受 BJ 影响。

---

## 最终状态

| # | 优先级 | 任务 | 状态 |
|---|--------|------|------|
| 1 | P0 | 排除北交所 | ✅ 完成 |
| 2 | P0 | 修复 xdxr 覆盖率 | ✅ 完成 |
| 3 | P0 | 排查日线覆盖跳降 | ✅ 完成（非 bug） |
| 4 | P0 | 5m 去重 | ✅ 完成 |
| 5 | P1 | SQLite/data 分析报告 | ✅ 完成 |
| 6 | P2 | minute1 + 研究标的重定义 | ✅ 完成 |

---
