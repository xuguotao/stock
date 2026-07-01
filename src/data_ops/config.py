"""Runtime configuration for the standalone data operations runner."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from config.settings import get_settings


@dataclass(frozen=True)
class DataOpsRuntimeConfig:
    clickhouse_host: str
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_database: str
    log_dir: str = "logs"
    runner_id: str = ""


def load_data_ops_config(
    *,
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> DataOpsRuntimeConfig:
    settings = get_settings().clickhouse
    env = dict(os.environ if environ is None else environ)
    values = {
        "clickhouse_host": _env_or_default(env, "DATA_OPS_CLICKHOUSE_HOST", settings.host),
        "clickhouse_user": _env_or_default(env, "DATA_OPS_CLICKHOUSE_USER", settings.user),
        "clickhouse_password": _env_or_default(env, "DATA_OPS_CLICKHOUSE_PASSWORD", settings.password),
        "clickhouse_database": _env_or_default(env, "DATA_OPS_CLICKHOUSE_DATABASE", settings.database),
        "log_dir": _env_or_default(env, "DATA_OPS_LOG_DIR", "logs"),
        "runner_id": _env_or_default(env, "DATA_OPS_RUNNER_ID", f"data-ops-{socket.gethostname()}"),
    }
    if config_path is not None:
        loaded = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("data ops config file must contain a JSON object")
        values.update({key: str(value) for key, value in loaded.items() if value is not None})
    return DataOpsRuntimeConfig(**values)


def _env_or_default(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key)
    return value if value else default
