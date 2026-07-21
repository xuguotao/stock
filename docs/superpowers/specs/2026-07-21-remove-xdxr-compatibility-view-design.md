# 移除 XDXR 兼容视图设计

## 目标

删除 `mootdx_xdxr` 兼容 View，使同步、质量读取、日线关联和研究复权都直接消费明确的三层对象。

## 边界

- 同步仅写 `mootdx_xdxr_event_versions`、`mootdx_xdxr_symbol_observations` 与既有抓取审计，不再写兼容 View。
- 当前事实/质量读取和日线事件关联直接读 `mootdx_xdxr_current`。
- 研究复权直接从事件版本日志按捕获 `ingest_seq` 选择事件，不能再经过当前 View。
- 迁移器在切换完成后不再保留或重建 `mootdx_xdxr`。

## 顺序与安全

先消除同步写入及所有运行时读取依赖，测试通过后验证远端新 XDXR 同步可完成；再删除兼容 View。删除后表名不再存在，任何遗漏依赖会立即暴露，故远端删除必须是最后一个步骤。
