from __future__ import annotations

from pathlib import Path


def test_data_ops_launchd_script_documents_install_uninstall_status() -> None:
    source = Path("scripts/install_data_ops_launchd.sh").read_text(encoding="utf-8")

    assert "python -m src.data_ops.runner" in source
    assert "install)" in source
    assert "uninstall)" in source
    assert "status)" in source
    assert "DATA_OPS_CLICKHOUSE_HOST" in source
    assert "DATA_OPS_LOG_DIR" in source
    assert "logs/data_ops_runner.log" in source
    assert "com.xuguotao.stock.data-ops-runner" in source
    assert "resolve_python_bin" in source
    assert "command -v \"$PYTHON_BIN\"" in source
    assert "append_env_if_set DATA_OPS_CLICKHOUSE_HOST" in source
    assert "TASK_GROUP" in source
    assert "--task-group" in source
    assert "com.xuguotao.stock.data-ops-runner.$TASK_GROUP" in source
