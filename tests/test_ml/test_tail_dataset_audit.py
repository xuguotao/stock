from __future__ import annotations

from datetime import date, datetime

from src.ml.tail_dataset_audit import audit_tail_ml_data


class FakeTailMlAuditClient:
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "from stocks" in normalized and "countif" in normalized:
            return [(5207, 230, 4977)]
        if "from daily_kline" in normalized and "countif(open <= 0" in normalized:
            return [(date(2020, 1, 2), date(2026, 6, 24), 5207, 7_252_052, 1203)]
        if "from minute5_kline" in normalized and "min(datetime)" in normalized:
            return [(datetime(2026, 1, 8, 9, 35), datetime(2026, 6, 24, 15, 0), 4991, 25_747_349)]
        if "minute5_usable_days" in normalized:
            return [(108,)]
        if "joinable_label_days" in normalized:
            return [(89,)]
        if "from stock_quote_snapshots" in normalized and "min(snapshot_at)" in normalized:
            return [(datetime(2026, 6, 17, 10, 41, 21), datetime(2026, 6, 24, 14, 59, 50), 4978, 31_513_648)]
        if "from tail_selection_signals" in normalized:
            return [(date(2026, 6, 15), date(2026, 6, 23), 12_091, 6, 44, 4967)]
        if normalized == "select count() from tail_signal_outcomes":
            return [(33,)]
        if "from tail_signal_outcomes" in normalized:
            return [(date(2026, 6, 15), date(2026, 6, 23), 33, 6, 33)]
        if "strategy_tradable_pool" in normalized:
            return [(4936,)]
        return [(0,)]


def test_audit_tail_ml_data_marks_current_intraday_history_limited() -> None:
    result = audit_tail_ml_data(client=FakeTailMlAuditClient(), as_of=date(2026, 6, 24))

    assert result["status"] == "limited"
    assert result["as_of"] == "2026-06-24"
    assert result["summary"] == {
        "daily_rows": 7_252_052,
        "daily_symbols": 5207,
        "minute5_rows": 25_747_349,
        "minute5_symbols": 4991,
        "minute5_usable_days": 108,
        "joinable_label_days": 89,
        "tradable_pool": 4936,
    }
    assert result["daily"]["status"] == "limited"
    assert result["daily"]["invalid_ohlc_rows"] == 1203
    assert result["minute5"]["status"] == "limited"
    assert result["minute5"]["usable_days"] == 108
    assert result["labels"]["status"] == "limited"
    assert result["labels"]["joinable_days"] == 89
    assert result["snapshots"]["status"] == "limited"
    assert result["strategy_signals"]["status"] == "limited"
    assert "minute5_history_limited_108_days" in result["issues"]
    assert "joinable_label_days_limited_89" in result["issues"]
    assert "tail_signal_outcomes_too_sparse_33_rows" in result["issues"]


def test_audit_tail_ml_data_blocks_when_daily_data_is_missing() -> None:
    class MissingDailyClient(FakeTailMlAuditClient):
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "from daily_kline" in normalized and "countif(open <= 0" in normalized:
                return [(None, None, 0, 0, 0)]
            return super().execute(query, params)

    result = audit_tail_ml_data(client=MissingDailyClient(), as_of=date(2026, 6, 24))

    assert result["status"] == "blocked"
    assert result["daily"]["status"] == "blocked"
    assert "daily_kline_missing" in result["issues"]
