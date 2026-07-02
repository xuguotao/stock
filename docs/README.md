# 文档索引

本目录只保留当前有效的项目说明、新一轮优化产生的文档入口，以及必要的归档说明。

## 文档语言规范

所有项目文档使用中文叙述。代码标识、命令、API 路径、表名、字段名和文件路径保留原文，避免影响检索和执行。

## 当前文档

- `ARCHITECTURE.md`：当前系统架构和模块边界。
- `superpowers/reviews/2026-07-01-stock-vs-daily-count-gap-analysis.md`：股票总数(5207)与日线覆盖数(4960)差异的根因排查(ST 口径 + 06-17 起 ST 日线断流)。
- `fund_tail_prediction_todo.md`：基金尾盘预测的当前优化待办。
- `notes/`：不绑定单次实施计划的长期领域笔记。
- `notes/a-share-quant-data-system-todo.md`：A 股量化交易数据体系 TODO，按交易生存层、交易约束、因子研究、组合风控和宏观环境分层整理。
- `notes/tencent-stock-data-availability-test-2026-07-02.md`：腾讯股票数据接口可用性测试报告，记录接口延迟、字段完整性、分页限制和推荐使用方式。
- `notes/tencent-stock-data-interfaces.md`：腾讯股票数据接口调研文档，记录股票池、实时行情、分钟线等接口的用途、参数、字段和接入风险。
- `superpowers/README.md`：新一轮项目优化的工作区说明。
- `superpowers/specs/2026-07-01-data-quality-calendar-design.md`：数据质量日历 UI 设计。

## 当前实施计划

当前没有已批准的新实施计划。下一轮项目优化从现状检查重新开始，不沿用旧 plans/reviews/specs 作为默认输入。

## 归档记录

旧的 `superpowers/specs`、`superpowers/plans`、`superpowers/reviews` 已整体归档到：

- `archive/2026-06-30-superpowers-history/`

归档内容只用于追溯，不作为新一轮优化的默认依据。

## 已清理内容

- `WEB_DASHBOARD_ROADMAP.md`：已归档。该文件描述的是早期 parquet 数据中心和进程内后台任务路线，不能作为当前优化依据。
- `superpowers/plans/xu_0630.md`：已删除。该文件为空白临时笔记。
- 旧 `superpowers/plans`、`superpowers/reviews`、`superpowers/specs`：已归档到 `archive/2026-06-30-superpowers-history/`。
- 新一轮项目优化不默认继承归档结论，需要从当前代码、当前数据、当前目标重新检查。
