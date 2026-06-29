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
        if "historical_calibration_for_signal" in normalized:
            return [(12, 8, 7, 10, 0.012, 0.018, 0.041, -0.014)]
        if "confidence_bucket" in normalized:
            return [
                ("高可信", 6, 5, 5, 6, 0.018, 0.026, 0.055, -0.01),
                ("中可信", 4, 1, 2, 3, -0.004, -0.006, 0.018, -0.03),
            ]
        if "volume_ratio_bucket" in normalized:
            return [
                ("放量确认", 7, 5, 6, 7, 0.012, 0.02, 0.05, -0.012),
                ("量能一般", 3, 1, 1, 2, -0.003, 0.001, 0.02, -0.025),
            ]
        if "tail_return_bucket" in normalized:
            return [
                ("尾盘强拉", 5, 4, 4, 5, 0.014, 0.023, 0.052, -0.011),
                ("温和走强", 5, 2, 3, 4, 0.001, 0.006, 0.026, -0.021),
            ]
        if "pending_selected_signal_dates" in normalized:
            return [
                (date(2026, 6, 23), 2, 0, 2),
                (date(2026, 6, 22), 2, 1, 1),
            ]
        if "select s.trade_date, o.outcome_date" in normalized:
            return [
                (
                    date(2026, 6, 16),
                    date(2026, 6, 17),
                    "000001",
                    "平安银行",
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
        if "group by s.trade_date" in normalized:
            return [
                (date(2026, 6, 16), 4, 3, 3, 4, 0.008, 0.018, 0.045, -0.012),
                (date(2026, 6, 15), 5, 2, 2, 3, -0.002, 0.006, 0.03, -0.02),
            ]
        if "s.status = 'selected'" in normalized:
            return [(10, 6, 0.01, 0.02, 0.05, -0.015)]
        if "from tail_selection_signals" in normalized and "tail_signal_outcomes" in normalized:
            return [(30, 14, 0.002, 0.007, 0.04, -0.025)]
        return []


class StrictPendingDateFilterClient(FakeClickHouseClient):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "pending_selected_signal_dates" in normalized and "s.trade_date" in normalized:
            raise AssertionError("pending selected dates query must not use s.trade_date without alias")
        return super().execute(query, params)


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
    assert result["by_confidence"][0]["group"] == "高可信"
    assert result["by_volume_ratio"][0]["group"] == "放量确认"
    assert result["by_tail_return"][0]["group"] == "尾盘强拉"
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
    assert result["details"][0]["stock_name"] == "平安银行"
    assert result["details"][0]["review_status"] == "completed"
    assert result["details"][0]["next_high"] == 10.9
    assert result["details"][0]["current_price"] == 10.66
    assert result["details"][0]["current_return"] == pytest.approx(0.04509803921568634)
    assert result["details"][0]["max_return"] == pytest.approx(0.0686)
    assert result["details"][0]["confidence_bucket"] == "中可信"
    assert result["details"][0]["execution_label"] == "开盘可盈利"
    assert result["details"][0]["risk_label"] == "低回撤"


def test_historical_calibration_for_signal_returns_bucket_performance() -> None:
    repo = ClickHouseTailSignalRepository(client=FakeClickHouseClient())

    result = repo.historical_calibration_for_signal(
        v2_score=88.0,
        volume_ratio=2.2,
        tail_return=0.018,
        min_samples=5,
    )

    assert result == {
        "status": "ready",
        "sample_count": 12,
        "confidence_bucket": "高可信",
        "volume_ratio_bucket": "放量确认",
        "tail_return_bucket": "尾盘强拉",
        "close_win_rate": pytest.approx(8 / 12),
        "open_win_rate": pytest.approx(7 / 12),
        "max_win_rate": pytest.approx(10 / 12),
        "avg_open_return": 0.012,
        "avg_close_return": 0.018,
        "avg_max_return": 0.041,
        "avg_min_return": -0.014,
        "note": "基于历史相同可信度/量比/尾盘涨幅分桶统计。",
    }


def test_pending_selected_signal_dates_returns_missing_outcome_dates() -> None:
    repo = ClickHouseTailSignalRepository(client=StrictPendingDateFilterClient())

    result = repo.pending_selected_signal_dates(start=date(2026, 6, 1), end=date(2026, 6, 30))

    assert result == [
        {"signal_date": "2026-06-23", "selected_count": 2, "outcome_count": 0, "missing_count": 2},
        {"signal_date": "2026-06-22", "selected_count": 2, "outcome_count": 1, "missing_count": 1},
    ]


def test_compute_pending_selected_outcomes_recomputes_each_pending_date(monkeypatch) -> None:
    repo = ClickHouseTailSignalRepository(client=FakeClickHouseClient())
    calls: list[date] = []

    def fake_compute_selected_outcomes(*, signal_date: date) -> dict[str, object]:
        calls.append(signal_date)
        return {"signal_date": signal_date.isoformat(), "outcome_count": 1, "missing_symbols": []}

    monkeypatch.setattr(repo, "compute_selected_outcomes", fake_compute_selected_outcomes)

    result = repo.compute_pending_selected_outcomes(start=date(2026, 6, 1), end=date(2026, 6, 30))

    assert calls == [date(2026, 6, 23), date(2026, 6, 22)]
    assert result == {
        "mode": "pending",
        "start": "2026-06-01",
        "end": "2026-06-30",
        "date_count": 2,
        "outcome_count": 2,
        "missing_symbols": [],
        "dates": [
            {"signal_date": "2026-06-23", "outcome_count": 1, "missing_symbols": []},
            {"signal_date": "2026-06-22", "outcome_count": 1, "missing_symbols": []},
        ],
    }
