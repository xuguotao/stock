from __future__ import annotations

from datetime import date, datetime

from src.ml.tail_dataset_audit import audit_tail_ml_data


class FakeTailMlAuditClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, query, params=None):
        self.queries.append(query)
        normalized = " ".join(query.lower().split())
        if "select symbol, name from stocks" in normalized:
            return [("000001", "平安银行"), ("000002", "*ST测试"), ("000003", "best科技")]
        if "label_history_span" in normalized:
            return [(109,)]
        if "joinable_label_days" in normalized:
            return [(89,)]
        if "from stocks" in normalized and "countif" in normalized:
            return [(5207, 230, 4977)]
        if "from daily_kline" in normalized and "countif(open <= 0" in normalized:
            return [(date(2020, 1, 2), date(2026, 6, 24), 5207, 7_252_052, 1203)]
        if "from minute5_kline" in normalized and "min(datetime)" in normalized:
            return [(datetime(2026, 1, 8, 9, 35), datetime(2026, 6, 24, 15, 0), 4991, 25_747_349)]
        if "minute5_usable_days" in normalized:
            return [(108,)]
        if "from stock_quote_snapshots" in normalized and "min(snapshot_at)" in normalized:
            return [(datetime(2026, 6, 17, 10, 41, 21), datetime(2026, 6, 24, 14, 59, 50), 4978, 31_513_648)]
        if "from tail_selection_signals" in normalized:
            return [(date(2026, 6, 15), date(2026, 6, 23), 12_091, 6, 44, 4967)]
        if normalized == "select count() from tail_signal_outcomes":
            return [(33,)]
        if "from tail_signal_outcomes" in normalized:
            return [(date(2026, 6, 15), date(2026, 6, 23), 33, 6, 33)]
        if "from daily_kline d" in normalized and "group by d.symbol" in normalized:
            return [
                (str(index).zfill(6), f"样本{index}", "SZ" if index % 2 else "SH", 121, date(2026, 6, 24), 1_000_000.0, 100_000.0)
                for index in range(1, 4937)
            ]
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


def test_audit_tail_ml_data_uses_python_st_classifier_for_stock_summary() -> None:
    client = FakeTailMlAuditClient()

    result = audit_tail_ml_data(client=client, as_of=date(2026, 6, 24))

    assert result["stocks"] == {"stock_count": 3, "st_count": 1, "non_st_count": 2}
    stock_queries = [query for query in client.queries if "from stocks" in query.lower()]
    assert any("select symbol, name" in " ".join(query.lower().split()) for query in stock_queries)
    assert all("positionutf8" not in " ".join(query.lower().split()) for query in stock_queries)


def test_audit_tail_ml_data_marks_short_history_as_pending_not_quality_limited() -> None:
    class ShortButCompleteHistoryClient(FakeTailMlAuditClient):
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "label_history_span" in normalized:
                return [(89,)]
            if "joinable_label_days" in normalized:
                return [(89,)]
            if "minute5_usable_days" in normalized:
                return [(89,)]
            return super().execute(query, params)

    result = audit_tail_ml_data(client=ShortButCompleteHistoryClient(), as_of=date(2026, 6, 24))

    assert result["labels"]["status"] == "pending_history"
    assert result["labels"]["history_span_days"] == 89
    assert "joinable_label_days_limited_89" not in result["issues"]
    assert "label_history_pending_89_days" in result["issues"]


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


def test_audit_tail_ml_data_counts_joinable_days_without_future_self_join() -> None:
    client = FakeTailMlAuditClient()

    audit_tail_ml_data(client=client, as_of=date(2026, 6, 24))

    joinable_queries = [query for query in client.queries if "joinable_label_days" in query]
    assert len(joinable_queries) == 1
    normalized = " ".join(joinable_queries[0].lower().split())
    assert "inner join daily_kline d2" not in normalized
    assert "next_date" in normalized
