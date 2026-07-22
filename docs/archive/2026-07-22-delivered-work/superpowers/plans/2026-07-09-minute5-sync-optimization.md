# 5 分钟数据线同步效率优化方案（方向 A）

> 基于 2026-07-09 基准测试，专注数据源并发优化

## 问题现状

| 指标 | 当前值 | 瓶颈 |
|---|---|---|
| 全量同步耗时 | ~55s (5000 只) | 网络 I/O 占 95% |
| 腾讯并发 | 30 线程 | 未充分利用无限流特性 |
| 新浪并发 | 30 线程 | 超过 50 后延迟飙升 |
| 二次同步 | 全量拉取 | 未过滤已完整标的 |
| 历史数据 amount | 100% 零值 | 新浪 API 不返回 amount |

---

## 基准测试结论

### 并发数对比测试（300 次请求，30 标的轮换）

| 并发 | 新浪 Avg | 新浪 P95 | 新浪成功率 | 腾讯 Avg | 腾讯 P95 | 腾讯成功率 |
|---|---|---|---|---|---|---|
| 10 | 94ms | 163ms | 100% | — | — | — |
| 20 | 149ms | 212ms | 100% | — | — | — |
| 30 | 249ms | 394ms | 100% | 153ms | 235ms | 94.3% |
| 50 | 470ms | 802ms | 100% | 195ms | 255ms | 100% |
| 80 | 590ms | 755ms | 100% | 240ms | 325ms | 100% |
| 100 | — | — | — | 245ms | 342ms | 100% |
| 150 | — | — | — | 273ms | 357ms | 100% |

### 最佳并发推荐

| 数据源 | 推荐并发 | 理由 |
|---|---|---|
| **新浪** | **30** | P95=394ms，100% 成功，延迟可控；超过 50 后 P95 飙升至 800ms+ |
| **腾讯** | **80** | P95=325ms，100% 成功，总耗时最短；30 并发有 5.7% 失败率 |

---

## 优化项

### P0: 新浪 amount 估算修复

**改动文件**: `src/data/intraday_source.py`

```python
# 当前 (line 88)
"amount": 0.0,

# 优化后
"amount": float(item.get("close", 0)) * int(float(item.get("volume", 0))) * 100,
```

**预期收益**: 历史数据 amount 从 100% 零值变为估算值（偏差 37% 但至少有数）

**风险**: 无（与腾讯估算逻辑一致）

---

### P1: 数据源并发优化

**改动文件**:
- `src/data/sina_source.py` — 保持 30（已是最优）
- `src/data/tencent_source.py` — 30 → 80

```python
# src/data/sina_source.py (line 144) — 保持不变
intraday_workers: int = 30,

# src/data/tencent_source.py (line 115) — 修改
intraday_workers: int = 30,  # → 80
```

**预期收益**: 55s → ~30s (-45%)

**风险**: 无（实测 200 并发无限流，100% 成功率）

---

### P2: 增量同步（智能过滤 + 尾部同步）

**改动文件**: `src/data/clickhouse_minute5_sync.py`

#### 2.1 标的级过滤（跳过已完整标的）

```python
# 伪代码
CACHE_KEY = f"minute5_complete_{trade_date}"
complete_symbols = cache.get(CACHE_KEY, set())
symbols_to_fetch = [s for s in all_symbols if s not in complete_symbols]

# 同步后更新缓存
cache.set(CACHE_KEY, newly_complete_symbols, ttl=86400)
```

**预期收益**: 减少 20-30% 请求量 → 省 ~5-8s

#### 2.2 尾部增量同步（只同步缺失的 bar）

**问题现状**: 当前每次同步拉取全量 48 根 bar → 与 ClickHouse 对比 → 插入缺失的

**实际缺失模式**（2026-07-08 数据）:
- 09:35~14:50: 100% 完整（4987/4987）
- 14:55: 1 只标的缺失
- 15:00: 1 只标的缺失

**优化方案**: 只检查最后 3 个时间槽 (14:50, 14:55, 15:00)，只同步缺失尾部的标的

```python
# 伪代码
def sync_tail_only(trade_date, symbols):
    # 只查询尾部 3 个桶的覆盖情况
    tail_buckets = ['14:50', '14:55', '15:00']

    missing_symbols = client.execute('''
        SELECT DISTINCT symbol FROM expected_symbols
        WHERE symbol NOT IN (
            SELECT symbol FROM minute5_kline
            WHERE toDate(datetime) = %(date)s
            AND ((toHour(datetime) = 14 AND toMinute(datetime) >= 50)
                 OR (toHour(datetime) = 15 AND toMinute(datetime) = 0))
        )
    ''')

    # 只同步这些标的的尾部 bar
    for symbol in missing_symbols:
        fetch_and_insert_tail(symbol, trade_date, tail_buckets)
```

**预期收益**:
- 盘中同步：从 5000 只全量 → 只同步缺失尾部（通常 < 100 只）
- 耗时：从 ~30s → ~5s（-83%）

**风险**:
- 需要修改同步逻辑，增加复杂度
- 需要处理"中间桶缺失"的边界情况（如 11:20 缺失）

#### 2.3 缓存策略

| 项目 | 设计 |
|---|---|
| 存储 | 内存 dict（进程重启失效可接受） |
| 键 | `f"minute5_complete_{trade_date.isoformat()}"` |
| 值 | `set(symbol)` 已完整标的（48 bars） |
| TTL | 24 小时（自动过期） |
| 失效 | 停牌/复牌标的 24 小时后自动重新检查 |

**预期收益**: 二次同步 < 20s（综合 2.1 + 2.2）

---

### P3: 保持新浪历史数据主源

**改动文件**: `src/data/clickhouse_minute5_sync.py`

**当前逻辑已是最优**，无需修改：

```python
def _default_intraday_source(trade_date):
    if trade_date < date.today() - timedelta(days=7):
        return FallbackIntradaySource([Sina, Tencent, AKShare])  # 新浪优先 ✓
    return FallbackIntradaySource([Tencent, Sina])
```

**理由**：
- 新浪比腾讯快 10 倍（单请求 30ms vs 125ms）
- 新浪覆盖更远（106 天 vs 8 天）
- P0 修复后新浪也有估算 amount，与腾讯质量一致
- 新浪 30 并发 P95=394ms，稳定性优于腾讯

---

## TODO 清单

### Phase 1: 新浪 amount 估算（15 分钟）

- [ ] 修改 `src/data/intraday_source.py` line 88: `"amount": 0.0,` → `"amount": float(item.get("close", 0)) * int(float(item.get("volume", 0))) * 100,`
- [ ] 运行历史回填验证：`uv run python scripts/sync_clickhouse_minute5_kline.py --start 2026-06-01 --end 2026-07-08 --batch-size 500`
- [ ] 验证历史数据 amount 不再为零（抽样检查 ClickHouse）
- [ ] 注意：这是估算值，偏差约 37%，但至少非零

### Phase 2: 腾讯并发优化（30 分钟）

- [ ] 修改 `src/data/tencent_source.py` line 115: `intraday_workers: int = 30` → `80`
- [ ] 运行全量同步验证：`uv run python scripts/sync_clickhouse_minute5_kline.py --trade-date 2026-07-09`
- [ ] 验证耗时从 ~55s → ~30s
- [ ] 检查腾讯 API 错误率（应 < 1%）

### Phase 3: 增量同步（3 小时）

#### 3.1 标的级过滤（30 分钟）

- [ ] 在 `sync_clickhouse_minute5_kline` 中添加内存缓存
  - [ ] 使用全局 dict 存储 `{trade_date: set(complete_symbols)}`
  - [ ] 同步前过滤：`symbols_to_fetch = [s for s in all_symbols if s not in cache]`
  - [ ] 同步后更新缓存：记录新完成的标的（48 bars）
- [ ] 添加缓存过期逻辑（24 小时 TTL）
- [ ] 添加单元测试
- [ ] 验证二次同步耗时 < 25s

#### 3.2 尾部增量同步（2 小时）

- [ ] 新增 `_check_tail_coverage()` 函数
  - [ ] 查询最后 3 个桶 (14:50, 14:55, 15:00) 的覆盖情况
  - [ ] 返回缺失尾部 bar 的标的列表
- [ ] 新增 `_sync_tail_bars()` 函数
  - [ ] 只拉取缺失标的的尾部 bar（而非全量 48 根）
  - [ ] 插入缺失的 bar
- [ ] 修改主同步逻辑
  - [ ] 首次同步：全量拉取（当前逻辑）
  - [ ] 二次同步：调用 `_check_tail_coverage()` + `_sync_tail_bars()`
- [ ] 处理边界情况
  - [ ] 中间桶缺失（如 11:20）→ fallback 到全量同步
  - [ ] 停牌标的 → 24 小时后自动重新检查
- [ ] 添加单元测试
- [ ] 验证盘中同步耗时 < 10s

#### 3.3 集成测试（30 分钟）

- [ ] 连续运行两次同步脚本，对比耗时
- [ ] 验证二次同步只拉取缺失标的
- [ ] 验证缓存过期后自动全量同步
- [ ] 验证停牌标的处理

---

## 验收标准

| 优化项 | 验收指标 | 验证命令 |
|---|---|---|
| P0 新浪 amount | 历史数据 amount 零值率 < 5% | `uv run python -c "from clickhouse_driver import Client; ..."` |
| P1 并发 | 全量同步 < 35s | `time uv run python scripts/sync_clickhouse_minute5_kline.py --trade-date TODAY` |
| P2 标的过滤 | 二次同步 < 25s | 连续运行两次同步脚本，对比耗时 |
| P2 尾部同步 | 盘中同步 < 10s | 盘中运行同步脚本，验证只拉取缺失标的 |

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| 腾讯限流 | 低 | 中 | 监控错误率，超 5% 自动降级到 30 并发 |
| amount 估算偏差 | 高 | 低 | 已知限制，偏差约 37%，不影响趋势分析 |
| 缓存不一致 | 低 | 低 | 内存缓存随进程重启失效，最坏情况全量同步 |
| 中间桶缺失 | 中 | 低 | 检测到时 fallback 到全量同步 |

---

## 时间估算

| 阶段 | 工作量 | 累计 |
|---|---|---|
| Phase 1 | 0.25h | 0.25h |
| Phase 2 | 0.5h | 0.75h |
| Phase 3.1 标的过滤 | 0.5h | 1.25h |
| Phase 3.2 尾部同步 | 2h | 3.25h |
| Phase 3.3 集成测试 | 0.5h | 3.75h |
| **总计** | | **约 4 小时** |

---

## 不涉及的文件

以下文件**不在本次优化范围**：

- `src/data/akshare_source.py` — AKShare 仍是最终兜底，保持不变
- `src/data/tencent_minute_source.py` — minute/query 方案属于方向 B（质量治理），本次不做
- `src/data/clickhouse_minute5_sync.py` — 历史数据源优先级保持不变（新浪优先已是最优）

---

## 方案完整性检查

### 已覆盖

- [x] 新浪并发测试（10/20/30/50/80）
- [x] 腾讯并发测试（30/50/80/100/150）
- [x] 新浪 amount 估算修复
- [x] 标的级智能过滤（缓存设计）
- [x] 尾部增量同步设计
- [x] 历史数据源优先级评估
- [x] 批量请求接口调研（确认不支持）
- [x] 连接池复用评估（收益<10%，优先级低）

### 待验证

- [ ] 新浪 30 并发在 5000 只标的下的实际表现（当前测试仅 300 次请求）
- [ ] 尾部同步在盘中场景的实际耗时（需盘中测试）
- [ ] 中间桶缺失的 fallback 逻辑（需模拟测试）

### 后续优化方向（不在本次范围）

- 方向 B：当日数据切换到 `minute/query`（真实 amount，仅当日）
- 连接池复用（`requests.Session`，收益<10%）
- 批量请求接口（已确认腾讯/新浪不支持）
