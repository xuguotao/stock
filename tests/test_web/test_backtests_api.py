from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi.testclient import TestClient

import src.web.backend.backtests as backtests
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
    assert job["progress"] == {"percent": 100, "stage": "completed", "message": "回测完成"}
    assert "metrics" in job["result"]
    assert "equity_curve" in job["result"]
    assert len(job["result"]["equity_curve"]) > 0
    assert job["result"]["universe_symbols"] == ["000001.SZ", "300750.SZ", "600519.SH"]
    assert job["result"]["experiment"]["mode"] == "sample"
    assert job["result"]["experiment"]["universe_source"] == "sample_fixed"
    assert job["result"]["experiment"]["execution_assumption"] == "tail signal today, next-session open execution"
    assert len(job["result"]["latest_selection"]) == 2
    assert {"date", "rank", "symbol", "score", "close", "factor_values", "factor_contributions"}.issubset(
        job["result"]["latest_selection"][0]
    )
    assert "tail_session" in job["result"]["latest_selection"][0]["factor_values"]
    assert len(job["result"]["rebalance_selections"]) > 0
    assert {"date", "rank", "symbol", "score", "close"}.issubset(job["result"]["rebalance_selections"][0])
    assert len(job["result"]["trades"]) > 0
    assert {"date", "signal_date", "symbol", "side", "quantity", "price", "amount", "reason", "selection_score"}.issubset(
        job["result"]["trades"][0]
    )
    assert "T" not in job["result"]["trades"][0]["date"]
    first_buy = next(trade for trade in job["result"]["trades"] if trade["side"] == "buy")
    assert first_buy["signal_date"] == "2025-01-01"
    assert first_buy["date"] == "2025-01-02"
    assert first_buy["price_source"] == "next_open"
    assert first_buy["price"] != first_buy["signal_close"]
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


def test_backtest_api_defaults_to_clickhouse_source(monkeypatch, tmp_path) -> None:
    universe_params: list[dict] = []

    class FakeClickHouseSource:
        def _client_instance(self):
            return FakeClickHouseClient()

    class FakeClickHouseClient:
        def execute(self, query, params=None):
            params = params or {}
            if "from stocks" in query:
                return [
                    ("000001", "平安银行"),
                    ("600519", "贵州茅台"),
                    ("300750", "宁德时代"),
                ]
            if "from daily_kline" in query and "group by d.symbol" in query:
                universe_params.append(params)
                return [
                    ("000001", "平安银行", "SZ", 130, date(2025, 2, 28), 10000000, 1000000),
                    ("600519", "贵州茅台", "SH", 130, date(2025, 2, 28), 10000000, 1000000),
                    ("300750", "宁德时代", "SZ", 130, date(2025, 2, 28), 10000000, 1000000),
                ]
            if "from daily_kline" in query:
                dates = pd.bdate_range(params["start"], params["end"])
                rows = []
                for symbol_index, symbol in enumerate(params["symbols"]):
                    for index, current_date in enumerate(dates):
                        close = 10 + symbol_index * 5 + index * 0.1
                        rows.append(
                            (
                                symbol,
                                current_date.date(),
                                close * 0.99,
                                close * 1.01,
                                close * 0.98,
                                close,
                                1000000 + index * 1000,
                                close * (1000000 + index * 1000),
                            )
                        )
                return rows
            return []

    monkeypatch.setattr(backtests, "ClickHouseStockDataSource", FakeClickHouseSource)
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "capital": 100000,
            "top_n": 2,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["params"]["source"] == "clickhouse"
    assert job["result"]["experiment"]["mode"] == "clickhouse"
    assert job["result"]["experiment"]["universe_source"] == "clickhouse_strategy_tradable"
    assert job["result"]["symbol_count"] == 3
    assert universe_params[0]["min_daily_bars"] == 120


def test_clickhouse_backtest_loader_filters_invalid_ohlcv_rows(monkeypatch) -> None:
    class FakeClickHouseSource:
        def _client_instance(self):
            return FakeClickHouseClient()

    class FakeClickHouseClient:
        def execute(self, query, params=None):
            if "from daily_kline" in query and "group by d.symbol" in query:
                return [("000001", "平安银行", "SZ", 30, date(2025, 2, 28), 10000000, 1000000)]
            if "from daily_kline" in query:
                return [
                    ("000001", date(2025, 1, 2), 10.0, 10.5, 9.9, 10.2, 1000.0, 10200.0),
                    ("000001", date(2025, 1, 3), 0.0, 10.5, 9.9, 10.2, 1000.0, 10200.0),
                    ("000001", date(2025, 1, 4), 10.0, 10.5, 9.9, 0.0, 1000.0, 10200.0),
                    ("000001", date(2025, 1, 5), 10.0, 10.5, 9.9, 10.2, 0.0, 10200.0),
                ]
            return []

    monkeypatch.setattr(backtests, "ClickHouseStockDataSource", FakeClickHouseSource)
    request = backtests.TailBacktestRequest(start=date(2025, 1, 1), end=date(2025, 1, 31), symbols=["000001.SZ"])

    bars = backtests._load_clickhouse_bars(request)

    assert list(bars.index.get_level_values("date")) == [date(2025, 1, 2)]


def test_backtest_api_rejects_missing_dataset_when_source_is_dataset(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start": "2025-01-01",
            "end": "2025-02-28",
            "sample": False,
            "source": "dataset",
        },
    )

    assert response.status_code == 422


def test_backtest_api_accepts_legacy_request_field_names(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.sqlite3", run_jobs_inline=True)
    client = TestClient(app)

    response = client.post(
        "/api/backtests/tail-session",
        json={
            "start_date": "2025-01-01",
            "end_date": "2025-02-28",
            "initial_cash": 100000,
            "top_n": 2,
            "use_sample": True,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["params"]["start"] == "2025-01-01"
    assert job["params"]["end"] == "2025-02-28"
    assert job["params"]["capital"] == 100000
    assert job["params"]["sample"] is True


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
    assert job["result"]["experiment"]["universe_source"] == "dataset_all"
    assert job["result"]["tail_verifications"][0]["status"] == "missing_intraday_data"


def test_backtest_api_filters_dataset_to_custom_symbols(tmp_path) -> None:
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
            "symbols": ["000001.SZ", "600519.SH"],
            "sample": False,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["result"]["symbol_count"] == 2
    assert job["result"]["universe_symbols"] == ["000001.SZ", "600519.SH"]
    assert job["result"]["experiment"]["universe_source"] == "custom_symbols"
    assert job["result"]["experiment"]["requested_symbols"] == ["000001.SZ", "600519.SH"]


def test_backtest_api_reports_empty_dataset_filter_context(tmp_path) -> None:
    data_root = tmp_path / "research"
    data_root.mkdir()
    dataset_path = data_root / "daily.parquet"
    dates = pd.bdate_range("2025-01-01", periods=10)
    rows = []
    for current_date in dates:
        rows.append(
            {
                "date": current_date.date().isoformat(),
                "symbol": "000001.SZ",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 1000000,
                "amount": 10000000,
                "adjusted_close": 10,
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
            "start": "2026-01-01",
            "end": "2026-02-01",
            "dataset_id": "daily.parquet",
            "sample": False,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "failed"
    assert "No bars available after applying filters" in job["error"]
    assert "requested=2026-01-01..2026-02-01" in job["error"]
    assert "available=2025-01-01..2025-01-14" in job["error"]
    assert "universe=dataset_all" in job["error"]


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
