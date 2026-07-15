# Mootdx 日线缺口归因实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将日线质量页的缺失标的归因为可回补、待核验或已知无数据。

**Architecture:** `MootdxQualityService` 在已有交易日、日线和状态查询结果上为每个缺失区间计算前后边界证据，并同时汇总到交易日；Vue 页面只消费归因字段，不重复业务判断。

**Tech Stack:** Python、ClickHouse、FastAPI、Vue 3、Element Plus、pytest。

---

### Task 1: 缺口归因契约

**Files:** `tests/test_web/test_mootdx_quality.py`, `src/web/backend/mootdx_quality.py`

- [x] 写失败测试：`no_data` 缺口为 `known_no_data`；两侧均有日线的连续缺口为 `repair_candidate`；窗口边界缺口为 `needs_review`。
- [x] 在 `daily_quality()` 中以按代码的实际交易日集合构建缺失连续区间，并返回 `classification`、`recommendation`、`evidence` 及每日分类计数。
- [x] 运行 `uv run --no-sync pytest tests/test_web/test_mootdx_quality.py -q`。

### Task 2: 日线质量页面

**Files:** `frontend/src/api/client.ts`, `frontend/src/pages/DailyKlineQuality.vue`

- [x] 扩展 API 类型，加入每日分类计数和缺失明细归因字段。
- [x] 删除表格进度条，改为完整度文本及“建议回补 / 待核验 / 已知无数据”计数；缺失标的表展示归因和证据。
- [x] 运行 `npm run build`。

### Task 3: 真实数据复核

**Files:** `docs/notes/mootdx-data-source.md`

- [x] 使用 `/api/data/mootdx/daily-quality` 检查近期缺口分类，确认未把待核验误称为合理缺失。
- [x] 补充页面判定边界与停牌历史未接入的限制说明。
- [x] 运行相关后端测试和 `git diff --check`。
