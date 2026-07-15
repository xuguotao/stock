from __future__ import annotations

from datetime import date, datetime

from src.web.backend.mootdx_quality import _classify_missing_block, _profile_filter_sql


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
