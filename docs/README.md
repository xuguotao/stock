# 文档索引

文档只保留当前可执行的说明、待办和必要的历史归档。所有项目文档使用中文；代码标识、命令、API、表名和路径保留原文。

## 当前文档

- [系统架构](ARCHITECTURE.md)：模块边界与运行方式。
- [数据库数据字典](database-data-dictionary-2026-07-22.md)：当前 ClickHouse 表、视图与字段含义。
- [数据运维 runner 部署](data_ops_runner_deployment.md)：任务 runner 的部署、验证与运维方式。
- [Codex 协作规范](codex-usage-playbook.md)：本项目使用 Codex 的分支、worktree、验证与交接规则。
- [今日项目清理计划](plan-2026-07-22-project-cleanup.md)：本次清理的范围和验收标准。
- [当前待办](todo.md)：下一步优先级。

## 长期笔记

- `notes/`：数据源调研、质量分析和不绑定单次实施的领域记录。
- `fund_tail_prediction_todo.md`：基金尾盘预测专项待办。
- `tdxrs-data-source-guide.md`：TDXRS 数据源使用说明。

## 历史归档

- `archive/2026-06-30-superpowers-history/`：第一轮项目优化的历史计划、设计和复核。
- `archive/2026-07-22-delivered-work/superpowers/`：已交付的 plans、specs 和 reviews 快照；只用于追溯，不作为当前实施输入。

新任务应在 `docs/` 建立简短的计划或待办，并以当前代码、数据库与运行状态为准，不默认继承归档结论。
