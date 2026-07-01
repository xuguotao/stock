"""Stock database synchronization helpers."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[[int, str, str], None]


DEFAULT_REMOTE_STOCK_DB = "augustine@<PRIVATE_CLICKHOUSE_HOST>:/home/augustine/Dev/stock/data/stock.db"


def sync_stock_database(
    remote: str = DEFAULT_REMOTE_STOCK_DB,
    dest: str | Path = "data/stock.db",
    backup: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Sync stock.db via rsync, verify integrity, and atomically replace destination."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    backup_path = dest_path.with_suffix(dest_path.suffix + ".bak")

    if tmp_path.exists():
        tmp_path.unlink()

    _report(progress, 10, "copying", "开始同步 stock.db")
    subprocess.run(["rsync", "-av", "--progress", remote, str(tmp_path)], check=True)

    _report(progress, 75, "integrity_check", "校验 SQLite 完整性")
    _check_sqlite(tmp_path)

    _report(progress, 90, "replacing", "替换本地 stock.db")
    if backup and dest_path.exists():
        shutil.copy2(dest_path, backup_path)
    tmp_path.replace(dest_path)

    return {
        "remote": remote,
        "dest": str(dest_path),
        "size_bytes": dest_path.stat().st_size,
        "integrity": "ok",
        "backup_path": str(backup_path) if backup and backup_path.exists() else None,
    }


def _check_sqlite(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        result = conn.execute("pragma integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {result}")


def _report(progress: ProgressCallback | None, percent: int, stage: str, message: str) -> None:
    if progress is not None:
        progress(percent, stage, message)
