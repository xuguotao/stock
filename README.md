# A 股量化研究与数据平台

面向 A 股研究、回测和模拟交易的 Python 项目。当前以 **ClickHouse 数据仓**、**Mootdx 数据同步** 和 **数据运维 runner** 为主线；Web 后台用于查看数据健康、任务状态和研究结果。

## 当前架构

```text
Mootdx / 其他数据源
        ↓
数据同步与数据质量任务（src.data_ops.runner）
        ↓
ClickHouse（股票主数据、日线、XDXR、复权研究层、任务审计）
        ↓
研究 / 回测 / 模拟交易 / Web 控制台
```

- `src/data/`：数据源、ClickHouse 同步、XDXR 与复权研究数据层。
- `src/data_ops/`：独立数据任务 runner、任务配置、运行记录与心跳。
- `src/research/`、`src/strategy/`：因子研究、回测、尾盘策略与报告。
- `src/web/`、`frontend/`：FastAPI + Vue 控制台。
- `scripts/`：经过测试的 CLI 入口与人工诊断工具；可复用逻辑应放在 `src/`。

完整模块边界见 [架构说明](docs/ARCHITECTURE.md)。

## 本地开发

```bash
cp .env.example .env
pip install -e ".[dev]"
python -m pytest -q
```

启动 Web 后台：

```bash
python -m uvicorn src.web.backend.app:app --reload
```

启动前端：

```bash
cd frontend
npm install
npm run dev
```

数据任务 runner 的部署、任务组和验收方式见 [数据运维 runner 部署说明](docs/data_ops_runner_deployment.md)。生产或长期运行前，应先在 Web 的任务状态页或 ClickHouse 审计表确认最近一次运行结果；不要把研究脚本当作常驻同步服务。

## 文档入口

- [今日项目清理计划](docs/plan-2026-07-22-project-cleanup.md)
- [当前待办](docs/todo.md)
- [数据库数据字典](docs/database-data-dictionary-2026-07-22.md)
- [Codex 协作规范](docs/codex-usage-playbook.md)
- [全部文档索引](docs/README.md)

## 开发约定

- 数据仓与任务状态以 ClickHouse 为准；本地 `data/`、`reports/` 主要是缓存和运行产物。
- 日线复权研究层不直接替换线上策略读取口径，先独立验证与发布。
- 提交前至少运行相关测试和 `git diff --check`；数据同步、表结构或部署变更还需说明回滚与验证方式。
