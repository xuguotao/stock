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
    assert job["result"]["experiment"]["mode"] == "sample"
    assert job["result"]["experiment"]["execution_assumption"] == "daily close rebalance proxy"
    assert len(job["result"]["latest_selection"]) == 2
    assert {"date", "rank", "symbol", "score", "close", "factor_values", "factor_contributions"}.issubset(
        job["result"]["latest_selection"][0]
    )
    assert "tail_session" in job["result"]["latest_selection"][0]["factor_values"]
    assert len(job["result"]["rebalance_selections"]) > 0
    assert {"date", "rank", "symbol", "score", "close"}.issubset(job["result"]["rebalance_selections"][0])
    assert len(job["result"]["trades"]) > 0
    assert {"date", "symbol", "side", "quantity", "price", "amount", "reason", "selection_score"}.issubset(
        job["result"]["trades"][0]
    )
    assert "T" not in job["result"]["trades"][0]["date"]
    assert len(job["result"]["daily_return_curve"]) > 0
    assert len(job["result"]["monthly_returns"]) > 0
    assert len(job["result"]["position_outcomes"]) > 0
    assert {"symbol", "buy_date", "status", "return_pct", "holding_days"}.issubset(
        job["result"]["position_outcomes"][0]
    )
    assert {"closed_positions", "open_positions", "realized_pnl"}.issubset(job["result"]["outcome_summary"])
    assert len(job["result"]["tail_verifications"]) == len(job["result"]["latest_selection"])
    verification = job["result"]["tail_verifications"][0]
    assert verification["status"] == "confirmed"
    assert {"symbol", "date", "tail_return_pct", "volume_ratio", "signal_time", "bars"}.issubset(verification)
    assert verification["signal_time"] == "14:50"
    assert len(verification["bars"]) > 0
    assert {"time", "close", "volume"}.issubset(verification["bars"][0])


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
    assert job["result"]["experiment"]["mode"] == "dataset"
    assert job["result"]["tail_verifications"][0]["status"] == "missing_intraday_data"


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
