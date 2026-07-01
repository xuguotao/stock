from __future__ import annotations

import json

from src.data_ops.config import load_data_ops_config


def test_default_config_has_no_developer_absolute_paths() -> None:
    config = load_data_ops_config(environ={})

    assert "/Volumes/" not in str(config.log_dir)
    assert "/Users/" not in str(config.log_dir)
    assert config.log_dir == "logs"


def test_environment_overrides_clickhouse_and_logging() -> None:
    config = load_data_ops_config(
        environ={
            "DATA_OPS_CLICKHOUSE_HOST": "clickhouse.internal",
            "DATA_OPS_CLICKHOUSE_USER": "runner",
            "DATA_OPS_CLICKHOUSE_PASSWORD": "secret",
            "DATA_OPS_CLICKHOUSE_DATABASE": "stock_prod",
            "DATA_OPS_LOG_DIR": "/var/log/stock-runner",
            "DATA_OPS_RUNNER_ID": "runner-a",
        }
    )

    assert config.clickhouse_host == "clickhouse.internal"
    assert config.clickhouse_user == "runner"
    assert config.clickhouse_password == "secret"
    assert config.clickhouse_database == "stock_prod"
    assert config.log_dir == "/var/log/stock-runner"
    assert config.runner_id == "runner-a"


def test_empty_environment_values_fall_back_to_settings() -> None:
    default_config = load_data_ops_config(environ={})

    config = load_data_ops_config(
        environ={
            "DATA_OPS_CLICKHOUSE_HOST": "",
            "DATA_OPS_CLICKHOUSE_USER": "",
            "DATA_OPS_CLICKHOUSE_PASSWORD": "",
            "DATA_OPS_CLICKHOUSE_DATABASE": "",
            "DATA_OPS_LOG_DIR": "",
            "DATA_OPS_RUNNER_ID": "",
        }
    )

    assert config.clickhouse_host == default_config.clickhouse_host
    assert config.clickhouse_user == default_config.clickhouse_user
    assert config.clickhouse_password == default_config.clickhouse_password
    assert config.clickhouse_database == default_config.clickhouse_database
    assert config.log_dir == default_config.log_dir
    assert config.runner_id == default_config.runner_id


def test_config_file_overrides_environment(tmp_path) -> None:
    config_path = tmp_path / "data_ops.json"
    config_path.write_text(
        json.dumps(
            {
                "clickhouse_host": "file-host",
                "clickhouse_user": "file-user",
                "clickhouse_password": "file-password",
                "clickhouse_database": "file-db",
                "log_dir": "file-logs",
                "runner_id": "file-runner",
            }
        ),
        encoding="utf-8",
    )

    config = load_data_ops_config(
        config_path=config_path,
        environ={
            "DATA_OPS_CLICKHOUSE_HOST": "env-host",
            "DATA_OPS_LOG_DIR": "env-logs",
        },
    )

    assert config.clickhouse_host == "file-host"
    assert config.clickhouse_user == "file-user"
    assert config.clickhouse_password == "file-password"
    assert config.clickhouse_database == "file-db"
    assert config.log_dir == "file-logs"
    assert config.runner_id == "file-runner"
