from __future__ import annotations

from datetime import date, datetime

from src.web.backend.mootdx_quality import _classify_missing_block, _profile_filter_sql


def test_xdxr_quality_keeps_run_health_separate_from_fact_summary() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class FakeClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query, params=None):
            self.queries.append(query)
            if "from mootdx_sync_runs" in query:
                return [("run-1", datetime(2026, 7, 15, 12), datetime(2026, 7, 15, 12, 1), "success", {
                "duration_seconds": 14.78,
                "diagnostics": {"xdxr": {
                        "target_symbols": 300, "requested_symbols": 300, "success_symbols": 300,
                        "empty_symbols_count": 0, "failed_symbols_count": 0, "event_rows": 15233,
                        "request_seconds": 14.36, "parse_seconds": 0.42,
                        "circuit_breaker_triggered": False,
                    }}
                }, "")]
            if "from mootdx_xdxr_symbol_runs final" in query:
                return []
            if "from mootdx_xdxr final" in query:
                return [(4997, 170822, datetime(2026, 7, 15, 12, 30, 23), 170814)]
            raise AssertionError(query)

    client = FakeClient()
    payload = MootdxQualityService(client=client).xdxr_quality(limit=30)

    assert payload["latest_run"]["status"] == "success"
    assert payload["latest_run"]["success_symbols"] == 300
    assert payload["latest_run"]["duration_seconds"] == 14.78
    assert payload["runs"][0]["circuit_breaker_triggered"] is False
    assert "task_key = 'xdxr'" in client.queries[0]
    assert payload["data_summary"] == {
        "symbols": 4997, "events": 170822,
        "latest_ingested_at": "2026-07-15 12:30:23", "null_suogu": 170814,
    }


def test_xdxr_quality_returns_a_stable_empty_payload() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class EmptyClient:
        def execute(self, query, params=None):
            if "from mootdx_sync_runs" in query or "from mootdx_xdxr final" in query:
                return []
            raise AssertionError(query)

    payload = MootdxQualityService(client=EmptyClient()).xdxr_quality()

    assert payload == {
        "latest_run": None,
        "runs": [],
        "data_summary": {"symbols": 0, "events": 0, "latest_ingested_at": None, "null_suogu": 0},
    }


def test_xdxr_quality_parameterizes_history_filters() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class FakeClient:
        def __init__(self) -> None:
            self.query = ""
            self.params = None

        def execute(self, query, params=None):
            if "from mootdx_sync_runs" in query:
                self.query, self.params = query, params
                return []
            if "from mootdx_xdxr final" in query:
                return []
            raise AssertionError(query)

    client = FakeClient()
    MootdxQualityService(client=client).xdxr_quality(
        limit=999, start_date=date(2026, 7, 1), end_date=date(2026, 7, 15), status="error",
    )

    assert "started_at >= %(start_date)s" in client.query
    assert "started_at < %(end_date)s + interval 1 day" in client.query
    assert "status = %(status)s" in client.query
    assert client.params == {"limit": 100, "start_date": date(2026, 7, 1), "end_date": date(2026, 7, 15), "status": "error"}


def test_xdxr_run_detail_returns_audits_and_safe_summary() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class FakeClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query, params=None):
            self.queries.append(query)
            if "from mootdx_sync_runs" in query:
                return [("run-1", datetime(2026, 7, 15, 12), datetime(2026, 7, 15, 12, 1), "error", {
                    "diagnostics": {"xdxr": {"requested_symbols": 1, "failed_symbols_count": 1}}
                }, "source unavailable")]
            if "from mootdx_xdxr_symbol_runs final" in query:
                return [("000001.SZ", "error", 0, 12.5, 0.3, "source unavailable", ["year", "category"])]
            raise AssertionError(query)

    client = FakeClient()
    detail = MootdxQualityService(client=client).xdxr_run_detail("run-1", status="error", limit=500)

    assert detail == {
        "run_id": "run-1", "status": "error", "started_at": "2026-07-15 12:00:00",
        "finished_at": "2026-07-15 12:01:00", "error": "source unavailable",
        "summary": {"requested_symbols": 1, "success_symbols": 0, "empty_symbols": 0, "error_symbols": 1, "event_rows": 0},
        "items": [{"symbol": "000001.SZ", "status": "error", "event_rows": 0, "request_ms": 12.5,
                   "parse_ms": 0.3, "error": "source unavailable", "raw_columns": ["year", "category"]}],
    }
    assert "status = %(status)s" in "\n".join(client.queries)
    assert "task_key = 'xdxr'" in "\n".join(client.queries)


def test_xdxr_run_detail_is_none_when_run_does_not_exist() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class EmptyClient:
        def execute(self, query, params=None):
            return []

    assert MootdxQualityService(client=EmptyClient()).xdxr_run_detail("missing") is None


def test_classify_missing_block_uses_verified_baostock_no_data() -> None:
    previous, missing, following = date(2026, 6, 23), date(2026, 6, 24), date(2026, 6, 25)

    classification, recommendation, _ = _classify_missing_block(
        symbol="000524.SZ",
        block=[missing],
        actual_by_date={previous: {"000524.SZ"}, missing: set(), following: {"000524.SZ"}},
        trade_dates=[previous, missing, following],
        date_positions={previous: 0, missing: 1, following: 2},
        status="active",
        verification_by_date={missing: "no_data"},
    )

    assert classification == "known_no_data"
    assert recommendation == "无需回补"


def test_classify_missing_block_keeps_baostock_error_for_review() -> None:
    previous, missing, following = date(2026, 6, 23), date(2026, 6, 24), date(2026, 6, 25)

    classification, recommendation, _ = _classify_missing_block(
        symbol="000524.SZ",
        block=[missing],
        actual_by_date={previous: {"000524.SZ"}, missing: set(), following: {"000524.SZ"}},
        trade_dates=[previous, missing, following],
        date_positions={previous: 0, missing: 1, following: 2},
        status="active",
        verification_by_date={missing: "error"},
    )

    assert classification == "needs_review"
    assert recommendation == "待核验"


def test_catalog_quality_includes_universe_profile_funnel_and_distributions() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class FakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "from mootdx_stock_catalog final" in normalized:
                return [(2, 1, 1, 0, 0, date(2026, 7, 13))]
            if "from mootdx_catalog_change_events" in normalized:
                return []
            if "from stock_universe_profiles final" in normalized and "group by" not in normalized:
                return [(date(2026, 7, 10), date(2026, 7, 13), 3, 2, 2, 2, 1, 1)]
            if "select reason, market, count()" in normalized:
                return []
            if "array join exclusion_reasons" in normalized:
                return [("low_average_amount", 1)]
            if "group by market" in normalized:
                return [("SZ", 1), ("SH", 1)]
            if "group by liquidity_level" in normalized:
                return [("high", 1), ("low", 1)]
            return []

    payload = MootdxQualityService(client=FakeClient()).catalog_quality()

    assert payload["universe_profile"]["summary"]["catalog_valid"] == 2
    assert payload["universe_profile"]["summary"]["universe_eligible"] == 1
    assert payload["universe_profile"]["distributions"]["exclusion_reasons"] == [{"key": "low_average_amount", "count": 1}]


def test_profile_filter_uses_clickhouse_array_parameter_for_multiple_exclusion_reasons() -> None:
    where, params = _profile_filter_sql([{"field": "exclusion_reason", "values": ["st", "low_average_amount"]}])

    assert "hasAny(exclusion_reasons" in where
    assert params["filter_0"] == ["st", "low_average_amount"]


def test_profile_filter_supports_exact_exclusion_reason_market_paths() -> None:
    where, params = _profile_filter_sql([{"field": "reason_market", "values": ["latest_daily_missing::SZ"]}])

    assert "arrayMap" in where
    assert params["filter_0"] == ["latest_daily_missing::SZ"]


def test_universe_profile_details_return_the_same_filtered_statistics() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    service = MootdxQualityService(client=object())
    expected = {"status": "healthy", "summary": {"symbols": 12}, "distributions": {}}
    service.universe_profile_quality = lambda *, filters: expected  # type: ignore[method-assign]
    service._query = lambda *_args, **_kwargs: []  # type: ignore[method-assign]

    response = service.universe_profiles(filters=[{"field": "market", "values": ["SZ"]}])

    assert response["profile"] == expected


def test_universe_profile_quality_includes_exclusion_reason_market_tree() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class FakeClient:
        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if "select max(as_of_date)" in normalized:
                return [(date(2026, 7, 10), date(2026, 7, 13), 1, 3, 2, 2, 2, 1)]
            if "select reason, market, count()" in normalized:
                return [("latest_daily_missing", "SZ", 2), ("latest_daily_missing", "SH", 1)]
            if "array join exclusion_reasons" in normalized:
                return [("latest_daily_missing", 3)]
            if "group by market" in normalized:
                return [("SZ", 2), ("SH", 1)]
            if "group by liquidity_level" in normalized:
                return [("high", 3)]
            return []

    payload = MootdxQualityService(client=FakeClient()).universe_profile_quality()

    assert payload["distributions"]["exclusion_reason_markets"] == [
        {"reason": "latest_daily_missing", "market": "SZ", "count": 2},
        {"reason": "latest_daily_missing", "market": "SH", "count": 1},
    ]


def test_universe_profile_details_include_total_for_pagination() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    service = MootdxQualityService(client=object())
    service.universe_profile_quality = lambda *, filters: {"status": "healthy"}  # type: ignore[method-assign]
    service._query = lambda query, _params=None: [(42,)] if "select count()" in query else []  # type: ignore[method-assign]

    response = service.universe_profiles()

    assert response["total"] == 42


def test_catalog_change_events_can_filter_by_discovery_date_and_type() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    class FakeClient:
        def execute(self, query, params=None):
            assert "toDate(event_at) = %(event_date)s" in query
            assert "event_type = %(event_type)s" in query
            assert params["event_date"] == date(2026, 7, 13)
            assert params["event_type"] == "name_changed"
            return [(datetime(2026, 7, 13, 9, 22), "688651.SH", "name_changed", "{}", "{}", "run-1")]

    events = MootdxQualityService(client=FakeClient()).catalog_change_events(
        event_date=date(2026, 7, 13), event_type="name_changed",
    )

    assert events == [{
        "event_at": "2026-07-13 09:22:00", "symbol": "688651.SH", "event_type": "name_changed",
        "previous": {}, "current": {}, "run_id": "run-1",
    }]


def test_daily_quality_coverage_queries_do_not_force_clickhouse_final() -> None:
    from src.web.backend.mootdx_quality import MootdxQualityService

    queries = []

    class FakeClient:
        def execute(self, query, params=None):
            queries.append(query)
            if "from trade_calendar" in query:
                return [(date(2026, 7, 13),)]
            if "from mootdx_stock_catalog final" in query:
                return [("000001.SZ", date(1991, 4, 3))]
            if "groupuniqarray(symbol)" in " ".join(query.lower().split()):
                return [(date(2026, 7, 13), ["000001.SZ"])]
            if "select symbol, min(trade_date) from mootdx_stock_kline" in query:
                return [("000001.SZ", date(1991, 4, 3))]
            if "from mootdx_symbol_data_status" in query or "from mootdx_daily_gap_verifications" in query:
                return []
            raise AssertionError(query)

    response = MootdxQualityService(client=FakeClient()).daily_quality(lookback_days=30)

    assert response["summary"]["actual_symbols"] == 1
    assert all("mootdx_stock_kline final" not in " ".join(query.lower().split()) for query in queries)
