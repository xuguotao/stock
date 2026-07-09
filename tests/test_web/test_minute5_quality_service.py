from __future__ import annotations

from datetime import date, datetime

from src.web.backend.minute5_quality import Minute5QualityService


class FakeMinute5Client:
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if normalized.startswith("select count(), uniqexact(symbol), min(datetime), max(datetime) from minute5_kline"):
            return [(120, 3, datetime(2026, 7, 1, 9, 35), datetime(2026, 7, 8, 11, 25))]
        if "group by symbol, datetime" in normalized and "having count() > 1" in normalized:
            return [(0, 0)]
        if "countif(open <= 0" in normalized:
            return [(0, 1, 0, 0, 0)]
        if "tominute(datetime) % 5" in normalized:
            return [(0,)]
        if "not ((tohour(datetime)" in normalized:
            return [(0,)]
        if "max(todate(datetime))" in normalized:
            return [(date(2026, 7, 8),)]
        if "covered >= greatest" in normalized:
            return [(datetime(2026, 7, 8, 11, 20), 3)]
        if "group by datetime" in normalized and "order by datetime desc" in normalized and "limit 1" in normalized:
            return [(datetime(2026, 7, 8, 11, 25), 2)]
        if "from ( select s.symbol" in normalized and "inner join daily_kline" in normalized:
            return [(3,)]
        if "expected_symbols as (" in normalized and "observed_symbols as (" in normalized:
            return [
                ("000002", "万科A", 46, datetime(2026, 7, 8, 14, 50), 2),
                ("000003", "测试股", 0, None, 48),
            ]
        if "from minute5_kline k" in normalized and "invalid_reason" in normalized:
            return [
                ("000001", "平安银行", datetime(2026, 7, 8, 9, 35), 10.0, 9.5, 9.8, 10.1, 100.0, 1000.0, "high_invalid"),
            ]
        if "with candidate_dates as" in normalized and "latest_daily as" in normalized:
            return [
                (date(2026, 7, 8), 3, 48, 46, 2, 1, 1, datetime(2026, 7, 8, 14, 50)),
                (date(2026, 7, 7), 3, 48, 48, 0, 0, 0, datetime(2026, 7, 7, 15, 0)),
            ]
        return []


class StrictBackfillPlanClient(FakeMinute5Client):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "group by trade_date, expected_symbols" in normalized:
            raise AssertionError("backfill plan query must not use ambiguous final group by")
        return super().execute(query, params)


class LatestDailyUniverseClient(FakeMinute5Client):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "with candidate_dates as" in normalized and "latest_daily as" in normalized:
            assert "latest_daily" in normalized
            assert "d.date <= cd.trade_date" in normalized
            assert "o.symbol = e.symbol" in normalized
        if "observed_symbols as" in normalized and "expected_symbols" in normalized:
            assert "latest_daily" in normalized
            assert "date <= %(trade_date)s" in normalized
        return super().execute(query, params)


class StrictInvalidRowsClient(FakeMinute5Client):
    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if "from minute5_kline k" in normalized and "invalid_reason" in normalized:
            assert "anylast" not in normalized
        return super().execute(query, params)


class DeleteRowsClient(FakeMinute5Client):
    def __init__(self) -> None:
        self.mutations: list[tuple[str, object]] = []

    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        if normalized.startswith("alter table minute5_kline delete"):
            assert "mutations_sync = 2" in normalized
            self.mutations.append((normalized, params))
            return []
        return super().execute(query, params)


def test_minute5_quality_summary_rolls_up_core_integrity_signals() -> None:
    service = Minute5QualityService(client=FakeMinute5Client())

    payload = service.summary()

    assert payload["table"] == "minute5_kline"
    assert payload["rows"] == 120
    assert payload["symbols"] == 3
    assert payload["latest"]["raw_bucket"] == "2026-07-08 11:25:00"
    assert payload["latest"]["complete_bucket"] == "2026-07-08 11:20:00"
    assert payload["issues"]["invalid_ohlc"] == 1
    assert payload["status"] == "warning"


def test_minute5_quality_lists_missing_symbols_for_backfill_targeting() -> None:
    service = Minute5QualityService(client=FakeMinute5Client())

    payload = service.missing_symbols(date(2026, 7, 8), limit=10)

    assert payload["trade_date"] == "2026-07-08"
    assert payload["expected_buckets"] == 48
    assert payload["items"] == [
        {
            "symbol": "000002",
            "name": "万科A",
            "bars": 46,
            "latest_bucket": "2026-07-08 14:50:00",
            "missing_bars": 2,
        },
        {
            "symbol": "000003",
            "name": "测试股",
            "bars": 0,
            "latest_bucket": None,
            "missing_bars": 48,
        },
    ]


def test_minute5_quality_lists_invalid_rows_with_reason() -> None:
    service = Minute5QualityService(client=FakeMinute5Client())

    payload = service.invalid_rows(date(2026, 7, 8), limit=5)

    assert payload["items"] == [
        {
            "symbol": "000001",
            "name": "平安银行",
            "datetime": "2026-07-08 09:35:00",
            "open": 10.0,
            "high": 9.5,
            "low": 9.8,
            "close": 10.1,
            "volume": 100.0,
            "amount": 1000.0,
            "reason": "high_invalid",
        }
    ]


def test_minute5_quality_builds_backfill_plan_summary() -> None:
    service = Minute5QualityService(client=FakeMinute5Client())

    payload = service.backfill_plan(start=date(2026, 7, 7), end=date(2026, 7, 8))

    assert payload["range"] == {"start": "2026-07-07", "end": "2026-07-08"}
    assert payload["items"][0] == {
        "trade_date": "2026-07-08",
        "expected_symbols": 3,
        "expected_buckets": 48,
        "actual_buckets": 46,
        "missing_buckets": 2,
        "missing_symbols": 1,
        "invalid_rows": 1,
        "latest_bucket": "2026-07-08 14:50:00",
        "status": "needs_backfill",
    }
    assert payload["summary"] == {"days": 2, "needs_backfill_days": 1, "missing_buckets": 2, "missing_symbols": 1, "invalid_rows": 1}


def test_minute5_quality_backfill_plan_avoids_ambiguous_final_group_by() -> None:
    service = Minute5QualityService(client=StrictBackfillPlanClient())

    payload = service.backfill_plan(start=date(2026, 7, 7), end=date(2026, 7, 8))

    assert payload["summary"]["days"] == 2


def test_minute5_quality_backfill_plan_uses_latest_available_daily_universe() -> None:
    service = Minute5QualityService(client=LatestDailyUniverseClient())

    payload = service.backfill_plan(start=date(2026, 7, 8), end=date(2026, 7, 8))

    assert payload["items"][0]["trade_date"] == "2026-07-08"


def test_minute5_quality_missing_symbols_uses_latest_available_daily_universe() -> None:
    service = Minute5QualityService(client=LatestDailyUniverseClient())

    payload = service.missing_symbols(date(2026, 7, 8), limit=10)

    assert payload["items"][0]["symbol"] == "000002"


def test_minute5_quality_invalid_rows_query_does_not_use_aggregate_name_lookup() -> None:
    service = Minute5QualityService(client=StrictInvalidRowsClient())

    payload = service.invalid_rows(date(2026, 7, 8), limit=5)

    assert payload["items"][0]["reason"] == "high_invalid"


def test_minute5_quality_delete_symbol_day_rows_submits_targeted_mutation() -> None:
    client = DeleteRowsClient()
    service = Minute5QualityService(client=client)

    result = service.delete_symbol_day_rows(date(2026, 7, 8), ["000001.SZ", "600000"])

    assert result == {"trade_date": "2026-07-08", "deleted_symbols": ["000001", "600000"], "mutation": "submitted"}
    assert client.mutations[0][1] == {"trade_date": date(2026, 7, 8), "symbols": ("000001", "600000")}
