# mootdx stock_catalog 去重与变更检测

**Goal:** 让 `mootdx_stock_catalog` 实现"每只 symbol 逻辑上一行,仅当 `name/code/market/is_st` 变化时才写新版本",消除每次重跑产生的重复行(现状:`000001.SZ` 已因 3 次运行堆积 3 条一模一样的记录)。

**Architecture:**
- 改 `mootdx_stock_catalog` 表:`order by (symbol)`(去掉 `captured_at`)+ `partition by tuple()`(单分区,保证跨天去重),保留 `ReplacingMergeTree(captured_at)`。
- 同步逻辑加变更检测:`_stock_catalog_rows` 先用 `argMax` 读每只票的现存最新版,比对 `market/code/name/is_st`,只插"变化或新增"的票。
- 一次性迁移:drop 旧表(旧 schema + 现有重复)-> 重跑 `stock_catalog` 用新 schema 重建并全量载入。

**Scope(外科):** 只动 `mootdx_stock_catalog` 表与对应同步函数。其余受影响表(`finance_snapshot`/`f10_catalog`/`f10_detail`/`affair_files`)本轮不修。`_resolve_symbols` 的双 `fetch_stock_list` 调用与 ST 过滤行为保持不变(已另议,不在本次范围)。

**Files:**
- Modify: `src/data/mootdx_clickhouse_sync.py`
- Modify: `tests/test_data/test_mootdx_clickhouse_sync.py`

---

## Task 1: 改 stock_catalog 表结构

- [x] **Step 1:** 在 `MOOTDX_TABLE_SQL` 里把 `mootdx_stock_catalog` 的 `partition by toDate(captured_at)` 改为 `partition by tuple()`,`order by (symbol, captured_at)` 改为 `order by (symbol)`。其余列、`ReplacingMergeTree(captured_at)`、TTL 不变。
- [x] **Step 2:** 跑 `test_ensure_mootdx_tables_creates_only_prefixed_tables`,确认仍通过(它只断言表名字符串存在,不依赖排序键)。

## Task 2: 加变更检测逻辑

- [x] **Step 1: 写失败测试 `test_stock_catalog_skips_unchanged_symbols`**
  fake client 的 `execute` 对非 insert 查询返回与 `FakeSource` 完全一致的现存行:`[("000001.SZ", 0, "000001", "平安银行", 0)]`。跑 `stock_catalog` 任务,断言 `result["inserted"].get("mootdx_stock_catalog", 0) == 0`,且无 `mootdx_stock_catalog` 插入。
- [x] **Step 2: 写失败测试 `test_stock_catalog_inserts_changed_symbols`**
  fake client SELECT 返回 name 不同的现存行:`[("000001.SZ", 0, "000001", "旧名称", 0)]`。断言插了 1 行(`result["inserted"]["mootdx_stock_catalog"] == 1`)。
- [x] **Step 3:** 跑这两个新测试,确认失败(缺 `client` 参数 / 新逻辑未实现)。
- [x] **Step 4: 实现**
  - `_run_task` 增加 `client` 关键字参数,在 `sync_mootdx_offline_data` 调用处传入 `clickhouse`。
  - `_stock_catalog_rows(source, symbols, client)`:调 `_latest_catalog_by_symbol(client)` 拿 `symbol -> (market, code, name, is_st)`;逐只构造 `current = (market_code, stock.code, stock.name, is_st_flag)`;`latest.get(symbol) == current` 则 `continue`,否则 append(变化或新增)。
  - 新增 `_latest_catalog_by_symbol(client)`:
    ```python
    def _latest_catalog_by_symbol(client: Any) -> dict[str, tuple]:
        if client is None:
            return {}
        try:
            rows = client.execute(
                "select symbol, argMax(market, captured_at), argMax(code, captured_at), "
                "argMax(name, captured_at), argMax(is_st, captured_at) "
                "from mootdx_stock_catalog group by symbol"
            )
        except Exception:
            return {}
        return {row[0]: (int(row[1]), row[2], row[3], int(row[4])) for row in rows}
        ```
- [x] **Step 5:** 跑全量 mootdx 单测,确认全绿(含旧 `test_sync_default_tasks_writes_only_mootdx_tables`:fake SELECT 返回 `[]` -> 等价"无现存->全插",行为不变)。

## Task 3: 迁移与验证(连真实 ClickHouse)

- [x] **Step 1:** `DROP TABLE mootdx_stock_catalog`(清旧 schema + 现有重复)。
- [x] **Step 2:** `uv run --no-sync python scripts/sync_mootdx_clickhouse.py --tasks stock_catalog --limit 0`(`ensure_tables` 用新 schema 重建表 + 变更检测全量载入)。
- [x] **Step 3:** 验证:
  - `select count() from mootdx_stock_catalog` ≈ 全量票数(约 4995);
  - `select symbol, count() from mootdx_stock_catalog group by symbol having count() > 1` 为空(无重复)。
- [x] **Step 4:** 再跑一次同命令,确认 `inserted.mootdx_stock_catalog == 0`(无变化不写),证明变更检测生效。
- [ ] **Step 5(可选):** 构造一只票 name 变化,确认只插 1 行新版本,且 `argMax` 读到最新。

---

## Task 4 (后续补充): 同步末尾 OPTIMIZE FINAL

用户实测发现:手动改 `is_st` 后重跑,catalog 表短暂出现两条(symbol 的旧版本 + 新版本)。根因是 `ReplacingMergeTree` 去重为**最终一致**,新版本插入后旧版本要等后台 merge 才消失。

- [x] **Step 1:** 在 `sync_mootdx_offline_data` 的插入循环里,catalog 表有写入后追加 `optimize table mootdx_stock_catalog final`,把多版本物理合并成一条(无写入则不跑)。
- [x] **Step 2:** 单测断言:有变更时 OPTIMIZE 被执行;无变更时不执行。
- [x] **Step 3:** 端到端验证:改 `is_st=1` -> 跑同步 -> 只剩 1 条 `is_st=0`;再跑无变化 -> `inserted=0`、表保持一条/symbol。

取舍:此方案**不保留变更历史**(OPTIMIZE FINAL 只留最新版本),换取"表里始终物理一条/symbol"。如需历史则改读 `FINAL`/`argMax`。

---

## Self-Review

- 范围:只动 `stock_catalog` 表与对应同步函数;不碰其余 mootdx 表、生产表、`DataAggregator` 链路。
- 兼容:旧单测不受影响(fake 的 SELECT 返回 `[]` 等价"无现存数据->全插")。
- 迁移:drop 旧 eval 表 + 重跑,数据可由 sync 复现,无生产依赖。
- 选择依据:`argMax(..., captured_at)` 不依赖后台 merge 即可读到最新版本;`partition by tuple()` 保证跨天去重(原按天分区是跨天不去重的另一根因)。
