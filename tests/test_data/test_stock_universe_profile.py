from __future__ import annotations

from datetime import date, datetime


def test_build_profile_marks_valid_liquid_stock_as_eligible() -> None:
    from src.data.stock_universe_profile import StockUniverseProfileRules, build_profile

    profile = build_profile(
        catalog_row=("000001.SZ", "平安银行", "SZ", False, date(1991, 4, 3)),
        daily_metrics=(date(2026, 7, 10), 20, 16, 12_000_000.0, 10_500_000.0, 0),
        rules=StockUniverseProfileRules(),
        rule_version=3,
        computed_at=datetime(2026, 7, 13, 16, 15),
        as_of_date=date(2026, 7, 10),
    )

    assert profile["catalog_valid"] is True
    assert profile["latest_daily_valid"] is True
    assert profile["liquidity_qualified"] is True
    assert profile["universe_eligible"] is True
    assert profile["exclusion_reasons"] == []
    assert profile["rule_version"] == 3


def test_build_profile_explains_stale_daily_and_low_liquidity() -> None:
    from src.data.stock_universe_profile import StockUniverseProfileRules, build_profile

    profile = build_profile(
        catalog_row=("600001.SH", "ST 样本", "SH", True, date(2020, 1, 1)),
        daily_metrics=(date(2026, 7, 9), 20, 3, 2_000_000.0, 1_500_000.0, 17),
        rules=StockUniverseProfileRules(),
        rule_version=3,
        computed_at=datetime(2026, 7, 13, 16, 15),
        as_of_date=date(2026, 7, 10),
    )

    assert profile["universe_eligible"] is False
    assert profile["liquidity_level"] == "low"
    assert profile["exclusion_reasons"] == ["st", "latest_daily_missing", "insufficient_trading_days", "low_average_amount"]


def test_refresh_profiles_writes_complete_snapshot_and_audit() -> None:
    from src.data.stock_universe_profile import StockUniverseProfileRules, refresh_stock_universe_profiles

    class FakeClient:
        def __init__(self) -> None:
            self.inserts: list[tuple[str, list[tuple]]] = []
            self.ddl: list[str] = []

        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            if normalized.startswith("create table if not exists"):
                self.ddl.append(query)
                return []
            if normalized.startswith("alter table mootdx_xdxr modify column") or normalized.startswith(
                "alter table mootdx_stock_catalog add column if not exists"
            ):
                self.ddl.append(query)
                return []
            if "from trade_calendar" in normalized:
                return [(date(2026, 7, 10),)]
            if "mootdx_stock_catalog final" in normalized:
                assert "from (select * from mootdx_stock_catalog final) as c" in normalized
                assert "left join (select * from stocks final) as s" in normalized
                return [("000001.SZ", "平安银行", "SZ", 0, date(1991, 4, 3))]
            if "from mootdx_stock_kline final" in normalized:
                return [("000001.SZ", date(2026, 7, 10), 20, 16, 12_000_000.0, 10_000_000.0, 0)]
            if normalized.startswith("insert into stock_universe_profiles"):
                self.inserts.append((query, params))
                return []
            raise AssertionError(query)

    client = FakeClient()
    result = refresh_stock_universe_profiles(
        client=client,
        rules=StockUniverseProfileRules(),
        rule_version=2,
    )

    assert result["as_of_date"] == "2026-07-10"
    assert result["universe_eligible"] == 1
    assert result["catalog_valid"] == 1
    assert any("stock_universe_profiles" in sql for sql in client.ddl)
