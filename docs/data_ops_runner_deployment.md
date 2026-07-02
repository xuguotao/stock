# 数据获取 Runner 独立部署说明

## 目标

`src.data_ops.runner` 可以部署到没有 Web 后台、没有前端页面的服务器上。runner 只负责执行数据获取任务；后台管理页面通过同一个 ClickHouse 读取配置、状态、运行记录和心跳。

## 最小部署内容

- Python 运行环境。
- 项目中 `src/`、`config/`、`scripts/` 以及依赖声明文件。
- 能访问行情数据源的网络环境。
- 能访问与 Web 后台相同的 ClickHouse。

不需要部署：

- 前端构建产物。
- FastAPI Web 后台进程。
- SQLite `data/web/jobs.sqlite3`。

## 配置

runner 本地配置只用于连接 ClickHouse 和写日志，不保存业务任务启停状态。业务任务配置保存在 ClickHouse 的 `data_ops_task_config` 表。

可以写在项目根目录 `.env` 中，也可以由 shell、launchd 或 systemd 注入。runner 会先加载项目 `.env`，再读取环境变量。

`.env` 示例：

```dotenv
STOCK_CLICKHOUSE_HOST=127.0.0.1
STOCK_CLICKHOUSE_USER=default
STOCK_CLICKHOUSE_PASSWORD=
STOCK_CLICKHOUSE_DATABASE=stock

DATA_OPS_LOG_DIR=/var/log/stock-data-ops
DATA_OPS_RUNNER_ID=server-a
```

如果不设置 `DATA_OPS_CLICKHOUSE_*`，runner 默认复用 `STOCK_CLICKHOUSE_*`。只有当 runner 需要连接不同地址时，才单独设置 `DATA_OPS_CLICKHOUSE_HOST`、`DATA_OPS_CLICKHOUSE_USER`、`DATA_OPS_CLICKHOUSE_PASSWORD`、`DATA_OPS_CLICKHOUSE_DATABASE`。

## 冒烟测试

迁移后先执行单轮验证：

```bash
python -m src.data_ops.runner --once
```

也可以按任务组验证，避免重任务阻塞高频任务：

```bash
python -m src.data_ops.runner --once --task-group realtime
python -m src.data_ops.runner --once --task-group intraday
python -m src.data_ops.runner --once --task-group maintenance
```

预期：

- 不需要启动 Web 后台。
- 不需要存在 `data/web/jobs.sqlite3`。
- ClickHouse 中出现 `data_ops_task_config`、`data_ops_task_runs`、`data_ops_task_heartbeats`。
- Web 后台连接同一个 ClickHouse 后，可以在数据中心看到任务状态。

## macOS launchd

本机开发环境可以使用：

```bash
scripts/install_data_ops_launchd.sh install
scripts/install_data_ops_launchd.sh status
scripts/install_data_ops_launchd.sh uninstall
```

交易时段推荐拆成三个 launchd 实例：

```bash
TASK_GROUP=realtime DATA_OPS_RUNNER_ID=server-a-realtime scripts/install_data_ops_launchd.sh install
TASK_GROUP=intraday DATA_OPS_RUNNER_ID=server-a-intraday scripts/install_data_ops_launchd.sh install
TASK_GROUP=maintenance DATA_OPS_RUNNER_ID=server-a-maintenance scripts/install_data_ops_launchd.sh install
```

任务组职责：

- `realtime`：`quote_snapshot_capture`、`quote_rollup_refresh`，用于高频快照和聚合刷新。
- `intraday`：`minute5_intraday_sync`，用于全市场 5m 分钟线同步。
- `maintenance`：`stock_master_sync`、`quality_snapshot`、`post_close_maintenance`，用于股票主数据、质量快照和日终维护。

拆分后，5m 分钟线同步耗时较长时不会阻塞快照采集和聚合刷新。

安装脚本会读取当前 shell 环境。若希望 launchd 使用 `.env` 中的值，请先执行：

```bash
set -a
source .env
set +a
scripts/install_data_ops_launchd.sh install
```

## Linux systemd 示例

第一版只提供示例，不生成自动安装脚本。

```ini
[Unit]
Description=Stock Data Ops Runner (%i)
After=network-online.target

[Service]
WorkingDirectory=/opt/stock
Environment=DATA_OPS_CLICKHOUSE_HOST=127.0.0.1
Environment=DATA_OPS_CLICKHOUSE_USER=default
Environment=DATA_OPS_CLICKHOUSE_PASSWORD=
Environment=DATA_OPS_CLICKHOUSE_DATABASE=stock
Environment=DATA_OPS_LOG_DIR=/var/log/stock-data-ops
Environment=DATA_OPS_RUNNER_ID=linux-runner-%i
ExecStart=/opt/stock/.venv/bin/python -m src.data_ops.runner --task-group %i
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

保存为 `/etc/systemd/system/stock-data-ops@.service` 后启动：

```bash
systemctl enable --now stock-data-ops@realtime.service
systemctl enable --now stock-data-ops@intraday.service
systemctl enable --now stock-data-ops@maintenance.service
```

## 后台确认

启动 runner 后，打开数据中心的“更新任务状态”。如果 Web 后台和 runner 连接同一个 ClickHouse，应能看到：

- 任务启停配置。
- 最近运行结果。
- 最近错误。
- runner 心跳。
- 手动运行触发状态。
