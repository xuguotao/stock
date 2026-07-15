# mootdx 监控模块实施计划

**Goal:** 将 mootdx catalog 和日线任务的配置、审计与健康状态接入 Web 后台。

**Architecture:** 使用集中任务定义驱动 data_ops 默认配置与 Web 展示；监控服务只读汇总 ClickHouse 数据；前端通过独立页面管理配置和查看审计。

---

### Task 1: 集中任务定义和运行记录读取

- [ ] 为 mootdx 三个任务建立定义模块，并让 models、handlers、runner 复用。
- [ ] 为 data_ops repository 增加按 task key 查询近期运行记录的接口。
- [ ] 测试默认配置和运行记录读取。

### Task 2: 后端监控 API

- [ ] 编写失败 API 测试，覆盖任务状态、原始审计和表健康汇总。
- [ ] 实现可注入的 `MootdxMonitorService` 与 `GET /api/data/mootdx/monitor`。
- [ ] 验证读取失败不会使整个响应失败。

### Task 3: Web 管理页面

- [ ] 扩展前端 API 类型与客户端。
- [ ] 新建 `MootdxMonitor.vue`，实现健康、配置、审计 tab 与刷新、保存、手工运行操作。
- [ ] 注册路由与导航，并执行前端构建验证。

### Task 4: 手工运行文档

- [ ] 扩充 mootdx 文档：参数表、常规同步、回补、缺口核对、无数据复查和任务 runner 运维命令。
