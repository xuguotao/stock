from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_backtest_api_runs_with_inline_sample_dataset(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "capital": 100000,
            "top_n": 2,
            "sample": True,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert "metrics" in job["result"]
    assert "equity_curve" in job["result"]
    assert len(job["result"]["equity_curve"]) > 0
    assert job["result"]["universe_symbols"] == ["000001.SZ", "300750.SZ", "600519.SH"]
    assert len(job["result"]["latest_selection"]) == 2
    assert {"date", "rank", "symbol", "score", "close"}.issubset(job["result"]["latest_selection"][0])
    assert len(job["result"]["rebalance_selections"]) > 0
    assert {"date", "rank", "symbol", "score", "close"}.issubset(job["result"]["rebalance_selections"][0])
    assert len(job["result"]["trades"]) > 0
    assert {"date", "symbol", "side", "quantity", "price", "amount"}.issubset(job["result"]["trades"][0])
    assert "T" not in job["result"]["trades"][0]["date"]


def test_backtest_api_rejects_missing_dataset_when_not_sample(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "sample": False,
        },
    )

    assert response.status_code == 422


def test_backtest_api_resolves_dataset_id_from_configured_dataset_root(tmp_path) -> None:
    data_root = tmp_path / "research"
    data_root.mkdir()
    dataset_path = data_root / "daily.parquet"
    dates = pd.bdate_range("2025-01-01", periods=45)
    rows = []
    for symbol_index, symbol in enumerate(["000001.SZ", "600519.SH", "300750.SZ"]):
        for index, current_date in enumerate(dates):
            close = 10 + symbol_index * 5 + index * 0.1
            rows.append(
                {
                    "date": current_date.date().isoformat(),
                    "symbol": symbol,
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1000000 + index * 1000,
                    "amount": close * (1000000 + index * 1000),
                    "adjusted_close": close,
                }
            )
    pd.DataFrame(rows).to_parquet(dataset_path, index=False)
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        dataset_root=data_root,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "capital": 100000,
            "top_n": 2,
            "dataset_id": "daily.parquet",
            "sample": False,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["params"]["dataset_id"] == "daily.parquet"
    assert job["params"]["dataset_path"] == str(dataset_path)
    assert job["result"]["symbol_count"] == 3
    assert job["result"]["universe_symbols"] == ["000001.SZ", "300750.SZ", "600519.SH"]


def test_backtest_api_rejects_unknown_dataset_id(tmp_path) -> None:
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        dataset_root=tmp_path / "research",
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "dataset_id": "missing.parquet",
            "sample": False,
        },
    )

    assert response.status_code == 404
