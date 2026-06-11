from __future__ import annotations

import json

import pandas as pd
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_datasets_api_lists_local_research_datasets(tmp_path) -> None:
    data_root = tmp_path / "research"
    data_root.mkdir()
    dataset_path = data_root / "tail_session.parquet"
    pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000,
                "amount": 10200,
                "adjusted_close": 10.2,
            },
            {
                "date": "2025-01-03",
                "symbol": "600519.SH",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 2000,
                "amount": 202000,
                "adjusted_close": 101.0,
            },
        ]
    ).to_parquet(dataset_path, index=False)
    dataset_path.with_name("tail_session_manifest.json").write_text(
        json.dumps(
            {
                "dataset_path": str(dataset_path),
                "start": "2025-01-02",
                "end": "2025-01-03",
                "symbol_count": 2,
                "row_count": 2,
                "built_at": "2025-01-04T09:30:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app = create_app(db_path=tmp_path / "jobs.sqlite3", dataset_root=data_root)
    client = TestClient(app)

    response = client.get("/api/datasets")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": "tail_session.parquet",
            "name": "tail_session.parquet",
            "path": str(dataset_path),
            "manifest_path": str(dataset_path.with_name("tail_session_manifest.json")),
            "row_count": 2,
            "symbol_count": 2,
            "start": "2025-01-02",
            "end": "2025-01-03",
            "built_at": "2025-01-04T09:30:00",
            "size_bytes": dataset_path.stat().st_size,
        }
    ]


def test_datasets_api_returns_dataset_detail_with_symbols(tmp_path) -> None:
    data_root = tmp_path / "research"
    data_root.mkdir()
    dataset_path = data_root / "liquid.parquet"
    pd.DataFrame(
        [
            {"date": "2025-01-02", "symbol": "000001.SZ", "close": 10.2},
            {"date": "2025-01-03", "symbol": "000001.SZ", "close": 10.4},
            {"date": "2025-01-03", "symbol": "600519.SH", "close": 101.0},
        ]
    ).to_parquet(dataset_path, index=False)
    app = create_app(db_path=tmp_path / "jobs.sqlite3", dataset_root=data_root)
    client = TestClient(app)

    response = client.get("/api/datasets/liquid.parquet")

    assert response.status_code == 200
    assert response.json()["id"] == "liquid.parquet"
    assert response.json()["row_count"] == 3
    assert response.json()["symbol_count"] == 2
    assert response.json()["start"] == "2025-01-02"
    assert response.json()["end"] == "2025-01-03"
    assert response.json()["symbols"] == ["000001.SZ", "600519.SH"]


def test_datasets_api_rejects_unknown_dataset(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", dataset_root=tmp_path / "research")
    client = TestClient(app)

    response = client.get("/api/datasets/missing.parquet")

    assert response.status_code == 404
