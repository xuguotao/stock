from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".ts", ".vue"}
SCAN_DIRS = ["src", "scripts", "frontend/src", "tests"]
FORBIDDEN = [
    "sql" + "ite" + "3",
    "SQL" + "ite",
    "stock" + ".db",
    "jobs" + "." + "sql" + "ite3",
    "sync-stock" + "-db",
    "stock_db" + "_path",
    "SQL" + "iteStock" + "DataSource",
    "inspect_stock" + "_database",
]


def test_codebase_has_no_legacy_local_database_references() -> None:
    offenders: list[str] = []
    for dirname in SCAN_DIRS:
        for path in (ROOT / dirname).rglob("*"):
            if path == Path(__file__).resolve() or path.suffix not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN:
                if token in text:
                    offenders.append(f"{path.relative_to(ROOT)} contains {token}")

    assert offenders == []


def test_legacy_stock_database_file_is_removed() -> None:
    assert not (ROOT / "data" / ("stock" + ".db")).exists()
