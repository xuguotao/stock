"""Dataset discovery and summaries for the dashboard API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


@dataclass(frozen=True)
class DatasetSummary:
    """Serializable local dataset metadata."""

    id: str
    name: str
    path: str
    manifest_path: str | None
    row_count: int
    symbol_count: int
    start: str | None
    end: str | None
    built_at: str | None
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "manifest_path": self.manifest_path,
            "row_count": self.row_count,
            "symbol_count": self.symbol_count,
            "start": self.start,
            "end": self.end,
            "built_at": self.built_at,
            "size_bytes": self.size_bytes,
        }


class DatasetService:
    """Inspect parquet datasets under a configured local root."""

    def __init__(self, dataset_root: str | Path = "data/research") -> None:
        self.dataset_root = Path(dataset_root)

    def list_datasets(self) -> list[DatasetSummary]:
        if not self.dataset_root.exists():
            return []
        return [self._summarize(path) for path in sorted(self.dataset_root.glob("*.parquet"))]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        path = self._resolve_dataset_id(dataset_id)
        if path is None or not path.exists():
            return None
        summary = self._summarize(path).to_dict()
        df = pd.read_parquet(path, columns=_available_columns(path, ["date", "symbol"]))
        symbols = sorted(df["symbol"].dropna().astype(str).unique().tolist()) if "symbol" in df.columns else []
        summary["symbols"] = symbols
        return summary

    def _resolve_dataset_id(self, dataset_id: str) -> Path | None:
        candidate = self.dataset_root / dataset_id
        try:
            candidate.relative_to(self.dataset_root)
        except ValueError:
            return None
        if candidate.suffix != ".parquet":
            return None
        return candidate

    def _summarize(self, path: Path) -> DatasetSummary:
        manifest = _read_manifest(path)
        fallback = _parquet_stats(path) if _needs_fallback(manifest) else {}
        return DatasetSummary(
            id=path.name,
            name=path.name,
            path=str(path),
            manifest_path=str(_manifest_path(path)) if _manifest_path(path).exists() else None,
            row_count=int(manifest.get("row_count", fallback.get("row_count", 0)) or 0),
            symbol_count=int(manifest.get("symbol_count", fallback.get("symbol_count", 0)) or 0),
            start=manifest.get("start") or fallback.get("start"),
            end=manifest.get("end") or fallback.get("end"),
            built_at=manifest.get("built_at"),
            size_bytes=path.stat().st_size,
        )


def _manifest_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}_manifest.json")


def _read_manifest(path: Path) -> dict[str, Any]:
    manifest_path = _manifest_path(path)
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _needs_fallback(manifest: dict[str, Any]) -> bool:
    required = {"row_count", "symbol_count", "start", "end"}
    return not required.issubset(manifest)


def _parquet_stats(path: Path) -> dict[str, Any]:
    columns = _available_columns(path, ["date", "symbol"])
    row_count = int(pq.ParquetFile(path).metadata.num_rows)
    if not columns:
        return {"row_count": row_count, "symbol_count": 0, "start": None, "end": None}
    df = pd.read_parquet(path, columns=columns)
    start = None
    end = None
    if "date" in df.columns and not df.empty:
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        if not dates.empty:
            start = dates.min().date().isoformat()
            end = dates.max().date().isoformat()
    symbol_count = int(df["symbol"].dropna().nunique()) if "symbol" in df.columns else 0
    return {
        "row_count": row_count,
        "symbol_count": symbol_count,
        "start": start,
        "end": end,
    }


def _available_columns(path: Path, requested: list[str]) -> list[str]:
    columns = set(pq.ParquetFile(path).schema.names)
    return [column for column in requested if column in columns]
