from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from src.web.backend.app import create_app
from src.web.backend.tail_replay_backtest import (
    ClickHouseReplayOutcomeProvider,
    TailReplayBacktestRequest,
    run_tail_replay_backtest,
)


def test_tail_replay_backtest_replays_each_cutoff_and_summarizes_outcomes() -> None:
    calls = []

    def fake_selector(payload, progress=None):
        calls.append(payload)
        suffix = payload.as_of_time.strftime("%H%M")
        return {
            "trade_date": payload.trade_date.isoformat(),
            "mode": "preview" if payload.as_of_time.hour == 14 and payload.as_of_time.minute < 50 else "selection",
            "selected_count": 1,
            "selections": [
                {
                    "symbol": f"000{suffix}.SZ",
                    "rank": 1,
                    "strength": 0.8,
                    "last_price": 10.0,
                    "volume_ratio": 2.2,
                    "tail_return": 0.012,
                    "v2_score": 82,
                    "v2_layer": "strong",
                    "score_breakdown": {"strength": 80, "volume_ratio": 88, "tail_return": 40},
                }
            ],
            "ranked_signals": [],
            "diagnostics": {"empty_reason": None},
            "data_freshness": {"status": "fresh"},
        }

    def fake_outcome(*, signal_date: date, symbol: str, signal_price: float) -> dict[str, Any]:
        close_return = 0.05 if "1430" in symbol else 0.01
        return {
            "signal_date": signal_date.isoformat(),
            "outcome_date": "2026-06-13",
            "symbol": symbol,
            "signal_price": signal_price,
            "next_open": 10.2,
            "next_high": 10.8,
            "next_low": 9.9,
            "next_close": signal_price * (1 + close_return),
            "open_return": 0.02,
            "max_return": 0.08,
            "min_return": -0.01,
            "close_return": close_return,
            "policy_return": 0.01,
            "policy_exit": "take_profit",
            "source": "minute5",
        }

    result = run_tail_replay_backtest(
        TailReplayBacktestRequest(
            start="2026-06-12",
            end="2026-06-12",
            cutoff_times=["14:30", "14:50"],
            limit=20,
            top_n=1,
        ),
        selector=fake_selector,
        outcome_provider=fake_outcome,
    )

    assert [call.as_of_time.strftime("%H:%M") for call in calls] == ["14:30", "14:50"]
    assert all(call.ignore_session is True for call in calls)
    assert all(call.auto_sync_minute5 is False for call in calls)
    assert result["summary"]["total_runs"] == 2
    assert result["summary"]["total_selected"] == 2
    assert result["summary"]["avg_policy_return"] == 0.01
    assert result["summary"]["win_rate_policy"] == 1.0
    assert result["by_cutoff"][0]["cutoff_time"] == "14:30"
    assert result["by_cutoff"][0]["avg_close_return"] == 0.05
    assert result["factor_diagnostics"][0]["factor"] == "strength"
    assert result["strategy_recommendation"]["best_cutoff_time"] == "14:30"
    assert result["strategy_recommendation"]["recommended_filters"][0]["factor"] == "strength"
    assert result["details"][0]["outcome"]["close_return"] == 0.05


def test_tail_replay_backtest_optimizes_cutoff_and_top_n_from_replayed_ranks() -> None:
    def fake_selector(payload, progress=None):
        cutoff = payload.as_of_time.strftime("%H%M")
        return {
            "trade_date": payload.trade_date.isoformat(),
            "mode": "selection",
            "selections": [
                {"symbol": f"{cutoff}01.SZ", "rank": 1, "strength": 0.8, "last_price": 10.0, "volume_ratio": 1.8, "tail_return": 0.008},
                {"symbol": f"{cutoff}02.SZ", "rank": 2, "strength": 0.7, "last_price": 10.0, "volume_ratio": 1.7, "tail_return": 0.006},
            ],
            "ranked_signals": [],
            "diagnostics": {"empty_reason": None},
        }

    def fake_outcome(*, signal_date: date, symbol: str, signal_price: float) -> dict[str, Any]:
        policy_return = 0.015 if symbol == "145501.SZ" else -0.01
        return {
            "signal_date": signal_date.isoformat(),
            "outcome_date": "2026-06-13",
            "symbol": symbol,
            "signal_price": signal_price,
            "next_open": signal_price,
            "next_high": signal_price * 1.02,
            "next_low": signal_price * 0.99,
            "next_close": signal_price * (1 + policy_return),
            "open_return": 0.0,
            "max_return": 0.02,
            "min_return": -0.01,
            "close_return": policy_return,
            "policy_return": policy_return,
            "policy_exit": "fixture",
            "source": "minute5",
        }

    result = run_tail_replay_backtest(
        TailReplayBacktestRequest(
            start="2026-06-12",
            end="2026-06-12",
            cutoff_times=["14:50", "14:55"],
            limit=20,
            top_n=2,
            min_optimizer_samples=1,
        ),
        selector=fake_selector,
        outcome_provider=fake_outcome,
    )

    assert result["strategy_recommendation"]["best_plan"]["cutoff_time"] == "14:55"
    assert result["strategy_recommendation"]["best_plan"]["top_n"] == 1
    assert result["strategy_recommendation"]["best_plan"]["avg_policy_return"] == 0.015
    assert result["optimization_grid"][0]["cutoff_time"] == "14:55"
    assert result["optimization_grid"][0]["top_n"] == 1


def test_tail_replay_backtest_assigns_selection_order_rank_for_optimizer() -> None:
    def fake_selector(payload, progress=None):
        return {
            "trade_date": payload.trade_date.isoformat(),
            "mode": "selection",
            "selections": [
                {"symbol": "000001.SZ", "strength": 0.8, "last_price": 10.0, "volume_ratio": 1.8, "tail_return": 0.008},
                {"symbol": "000002.SZ", "strength": 0.7, "last_price": 10.0, "volume_ratio": 1.7, "tail_return": 0.006},
            ],
            "diagnostics": {"empty_reason": None},
        }

    def fake_outcome(*, signal_date: date, symbol: str, signal_price: float) -> dict[str, Any]:
        return {
            "signal_date": signal_date.isoformat(),
            "outcome_date": "2026-06-13",
            "symbol": symbol,
            "signal_price": signal_price,
            "next_open": signal_price,
            "next_high": signal_price * 1.01,
            "next_low": signal_price * 0.99,
            "next_close": signal_price * 1.005,
            "open_return": 0.0,
            "max_return": 0.01,
            "min_return": -0.01,
            "close_return": 0.005,
            "policy_return": 0.005,
            "policy_exit": "fixture",
            "source": "minute5",
        }

    result = run_tail_replay_backtest(
        TailReplayBacktestRequest(
            start="2026-06-12",
            end="2026-06-12",
            cutoff_times=["14:55"],
            limit=20,
            top_n=2,
            min_optimizer_samples=1,
        ),
        selector=fake_selector,
        outcome_provider=fake_outcome,
    )

    assert [row["rank"] for row in result["details"]] == [1, 2]
    assert [row["top_n"] for row in result["optimization_grid"]] == [2, 1]


def test_tail_replay_backtest_api_runs_inline_job(tmp_path) -> None:
    def fake_replay_runner(payload, progress=None):
        if progress:
            progress(50, "replaying", "回放 14:30")
        return {
            "summary": {"total_runs": 1, "total_selected": 1},
            "by_cutoff": [{"cutoff_time": "14:30", "run_count": 1}],
            "details": [],
            "factor_diagnostics": [],
            "strategy_recommendation": {"best_cutoff_time": "14:30", "recommended_filters": []},
        }

    app = create_app(
        db_path=tmp_path / "jobs.json",
        run_jobs_inline=True,
        tail_replay_runner=fake_replay_runner,
    )
    client = TestClient(app)

    response = client.post(
        "/api/tail-session/replay-backtest",
        json={
            "start": "2026-06-12",
            "end": "2026-06-12",
            "cutoff_times": ["14:30"],
            "limit": 50,
            "top_n": 2,
        },
    )

    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["kind"] == "tail_session_replay_backtest"
    assert job["status"] == "success"
    assert job["progress"] == {"percent": 100, "stage": "completed", "message": "尾盘时段回放回测完成"}
    assert job["result"]["summary"]["total_selected"] == 1


def test_clickhouse_replay_outcome_provider_simulates_next_day_take_profit_before_close() -> None:
    class FakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "select min(todate(datetime))" in normalized:
                return [(date(2026, 6, 13),)]
            if "select datetime, open, high, low, close" in normalized:
                return [
                    ("2026-06-13 09:35:00", 10.0, 10.05, 9.98, 10.02),
                    ("2026-06-13 09:40:00", 10.02, 10.16, 10.01, 10.12),
                    ("2026-06-13 15:00:00", 10.12, 10.13, 10.0, 10.02),
                ]
            raise AssertionError(query)

    provider = ClickHouseReplayOutcomeProvider(client=FakeClient())

    outcome = provider(signal_date=date(2026, 6, 12), symbol="000001.SZ", signal_price=10.0)

    assert outcome is not None
    assert outcome["close_return"] == 0.002
    assert outcome["policy_return"] == 0.01
    assert outcome["policy_exit"] == "take_profit"
