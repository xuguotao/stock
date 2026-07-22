# 当前待办

更新时间：2026-07-22。

## 已完成

- [x] 项目入口、文档归档、旧 XDXR 手工脚本和本地再生成物清理（见 `plan-2026-07-22-project-cleanup.md`）。

## 接下来

- [ ] 在 Web 后台展示 `research_adjustment_refresh_audits`，让复权刷新状态、阻断原因和发布版本可见。
- [ ] 将正式手工数据任务统一收敛到 data-ops runner 的手动触发入口。
- [ ] 为数据库数据字典增加可生成的结构部分，降低字段变更后的文档漂移。
- [ ] 完成主分支推送、部署与 data-ops runner 重启后的运行验收。

## 后续优化

- [ ] 按功能拆分 `src/web/backend/app.py`、`src/data/mootdx_clickhouse_sync.py` 等超大模块。
- [ ] 为前端按路由拆包，降低首屏 JavaScript 体积。
- [ ] 建立日志与报告保留周期，避免本地运行产物持续增长。
