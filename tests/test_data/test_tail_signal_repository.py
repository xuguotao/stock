from __future__ import annotations

from datetime import date, datetime

import pytest

from src.data.tail_signal_repository import ClickHouseTailSignalRepository


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, object | None]] = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if "from minute5_kline" in normalized:
            return [
                ("000001", date(2026, 6, 16), 10.3, 10.9, 10.0, 10.8),
            ]
        if "from daily_kline" in normalized and "date = %(signal_date)s" in normalized:
            return [("000001", date(2026, 6, 15), 10.2)]
        if normalized.startswith("select symbol, date, open, high, low, close"):
            return [
                ("000001", date(2026, 6, 15), 10.0, 10.5, 9.8, 10.2),
                ("000001", date(2026, 6, 16), 10.3, 10.9, 10.1, 10.8),
            ]
        if "group by s.status" in normalized:
            return [
                ("selected", 10, 6, 7, 9, 0.01, 0.02, 0.05, -0.015),
                ("filtered", 20, 8, 9, 14, -0.002, 0.001, 0.025, -0.02),
            ]
        if "group by s.v2_layer" in normalized:
            return [
                ("strong", 5, 4, 4, 5, 0.02, 0.03, 0.06, -0.012),
                ("watchlist", 7, 3, 4, 5, 0.001, 0.004, 0.025, -0.02),
            ]
        if "group by s.filter_reason" in normalized:
            return [
                ("outside_top_n", 12, 5, 6, 8, 0.0, 0.002, 0.02, -0.018),
            ]
        if "group by s.mode" in normalized:
            return [
                ("selection", 10, 6, 7, 9, 0.01, 0.02, 0.05, -0.015),
                ("preview", 4, 1, 1, 2, -0.005, -0.01, 0.02, -0.03),
            ]
        if "group by s.trade_date" in normalized:
            return [
                (date(2026, 6, 16), 4, 3, 3, 4, 0.008, 0.018, 0.045, -0.012),
                (date(2026, 6, 15), 5, 2, 2, 3, -0.002, 0.006, 0.03, -0.02),
            ]
        if "select s.trade_date, o.outcome_date" in normalized:
            return [
                (
                    date(2026, 6, 16),
                    date(2026, 6, 17),
                    "000001",
                    "selection",
                    1,
                    "selected",
                    "",
                    "strong",
                    "buy",
                    0.82,
                    78.5,
                    2.1,
                    0.012,
                    10.2,
                    10.75,
                    10.3,
                    10.9,
                    10.1,
                    10.8,
                    0.0098,
                    0.0588,
                    0.0686,
                    -0.0098,
                    10.66,
                    datetime(2026, 6, 17, 13, 55, 13),
                )
            ]
        if "s.status = 'selected'" in normalized:
            return [(10, 6, 0.01, 0.02, 0.05, -0.015)]
        if "from tail_selection_signals" in normalized and "tail_signal_outcomes" in normalized:
            return [(30, 14, 0.002, 0.007, 0.04, -0.025)]
        return []


def test_save_tail_selection_result_writes_ranked_pool_rows() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseTailSignalRepository(client=client)

    repo.save_selection_result(
        job_id="job-1",
        result={
            "trade_date": "2026-06-15",
            "mode": "selection",
            "ranked_signals": [
                {
                    "rank": 1,
                    "symbol": "000001.SZ",
                    "status": "selected",
                    "filter_reason": None,
                    "strength": 0.82,
                    "last_price": 10.2,
                    "volume_ratio": 2.1,
                    "tail_return": 0.012,
                    "v2_score": 78.5,
                    "v2_layer": "strong",
                    "v2_action": "buy",
                },
                {
                    "rank": 2,
                    "symbol": "600000.SH",
                    "status": "filtered",
                    "filter_reason": "outside_top_n",
                    "strength": 0.7,
                    "last_price": 20.1,
                    "volume_ratio": 1.8,
                    "tail_return": 0.004,
                },
            ],
        },
    )

    inserts = [call for call in client.commands if "insert into tail_selection_signals" in call[0].lower()]
    assert len(inserts) == 1
    rows = inserts[0][1]
    assert rows == [
        (
            "job-1",
            date(2026, 6, 15),
            "selection",
            1,
            "000001",
            "selected",
            "",
            0.82,
            10.2,
            2.1,
            0.012,
            78.5,
            "strong",
            "buy",
            datetime(2026, 6, 15, 0, 0),
        ),
        (
            "job-1",
            date(2026, 6, 15),
            "selection",
            2,
            "600000",
            "filtered",
            "outside_top_n",
            0.7,
            20.1,
            1.8,
            0.004,
            None,
            "",
            "",
            datetime(2026, 6, 15, 0, 0),
        ),
    ]


def test_compute_and_save_outcomes_uses_next_daily_bar() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseTailSignalRepository(client=client)

    result = repo.compute_and_save_outcomes(
        signal_date=date(2026, 6, 15),
        symbols=["000001.SZ"],
    )

    assert result == {
        "signal_date": "2026-06-15",
        "outcome_count": 1,
        "missing_symbols": [],
    }
    inserts = [call for call in client.commands if "insert into tail_signal_outcomes" in call[0].lower()]
    rows = inserts[0][1]
    assert rows[0][:8] == (
        date(2026, 6, 15),
        date(2026, 6, 16),
        "000001",
        10.2,
        10.3,
        10.8,
        10.9,
        10.0,
    )
    assert rows[0][8:] == pytest.approx((
            0.009803921568627416,
            0.05882352941176472,
            0.06862745098039225,
            -0.019607843137254832,
        ))


def test_signal_stats_returns_overall_and_grouped_metrics() -> None:
    repo = ClickHouseTailSignalRepository(client=FakeClickHouseClient())

    result = repo.signal_stats(start=date(2026, 6, 1), end=date(2026, 6, 30))

    assert result["overall"] == {
        "count": 30,
        "win_count": 14,
        "win_rate": pytest.approx(14 / 30),
        "avg_open_return": 0.002,
        "avg_close_return": 0.007,
        "avg_max_return": 0.04,
        "avg_min_return": -0.025,
        "open_win_count": 0,
        "open_win_rate": 0.0,
        "max_win_count": 0,
        "max_win_rate": 0.0,
        "payoff_ratio": 0.0,
    }
    assert result["by_status"][0]["group"] == "selected"
    assert result["by_status"][0]["win_rate"] == pytest.approx(0.6)
    assert result["by_layer"][0]["group"] == "strong"
    assert result["by_filter_reason"][0]["group"] == "outside_top_n"
    assert result["by_mode"][0]["group"] == "selection"
    assert result["by_signal_date"] == [
        {
            "date": "2026-06-16",
            "count": 4,
            "win_count": 3,
            "win_rate": pytest.approx(0.75),
            "open_win_count": 3,
            "open_win_rate": pytest.approx(0.75),
            "max_win_count": 4,
            "max_win_rate": pytest.approx(1.0),
            "avg_open_return": 0.008,
            "avg_close_return": 0.018,
            "avg_max_return": 0.045,
            "avg_min_return": -0.012,
        },
        {
            "date": "2026-06-15",
            "count": 5,
            "win_count": 2,
            "win_rate": pytest.approx(0.4),
            "open_win_count": 2,
            "open_win_rate": pytest.approx(0.4),
            "max_win_count": 3,
            "max_win_rate": pytest.approx(0.6),
            "avg_open_return": -0.002,
            "avg_close_return": 0.006,
            "avg_max_return": 0.03,
            "avg_min_return": -0.02,
        },
    ]
    assert result["recent"] == result["by_signal_date"][:2]
    assert result["selected_overall"] == {
        "count": 10,
        "win_count": 6,
        "win_rate": pytest.approx(0.6),
        "avg_open_return": 0.01,
        "avg_close_return": 0.02,
        "avg_max_return": 0.05,
        "avg_min_return": -0.015,
        "open_win_count": 0,
        "open_win_rate": 0.0,
        "max_win_count": 0,
        "max_win_rate": 0.0,
        "payoff_ratio": 0.0,
    }
    assert result["selected_recent"] == result["recent"]
    assert result["execution_summary"] == {
        "sample_count": 10,
        "open_win_rate": 0.0,
        "close_win_rate": pytest.approx(0.6),
        "max_win_rate": 0.0,
        "avg_open_return": 0.01,
        "avg_close_return": 0.02,
        "avg_max_return": 0.05,
        "avg_min_return": -0.015,
        "payoff_ratio": 0.0,
    }
    assert result["details"][0]["symbol"] == "000001.SZ"
    assert result["details"][0]["review_status"] == "completed"
    assert result["details"][0]["next_high"] == 10.9
    assert result["details"][0]["current_price"] == 10.66
    assert result["details"][0]["current_return"] == pytest.approx(0.04509803921568634)
    assert result["details"][0]["max_return"] == pytest.approx(0.0686)
