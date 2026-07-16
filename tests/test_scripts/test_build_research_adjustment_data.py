"""Tests for explicit, fail-closed research adjustment builds."""
from __future__ import annotations

from datetime import date

from scripts import build_research_adjustment_data


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def ensure_tables(self) -> None:
        self.calls.append(("ensure_tables",))

    def write_candidate_events(self, run_id: str, formula_version: str, rows: list[dict]) -> int:
        self.calls.append(("events", run_id, formula_version, rows))
        return len(rows)

    def write_candidate_factors(self, run_id: str, formula_version: str, rows: list[dict]) -> int:
        self.calls.append(("factors", run_id, formula_version, rows))
        return len(rows)

    def publish_run(self, **kwargs: object) -> None:
        self.calls.append(("publish", kwargs))

    def current_run(self, _formula_version: str):
        return None


class _MootdxClient:
    def execute(self, sql: str, _params: object | None = None):
        normalized = " ".join(sql.lower().split())
        if "select distinct symbol from mootdx_stock_kline final" in normalized:
            return [("000001.SZ",)]
        if "from mootdx_stock_kline final" in normalized:
            return [
                ("000001.SZ", date(2026, 7, 15), 10.0),
                ("000001.SZ", date(2026, 7, 16), 9.0),
            ]
        if "from mootdx_xdxr final" in normalized:
            return [("000001.SZ", date(2026, 7, 16), 1, "cash", 1.0, 0.0, 0.0, 0.0, 1.0)]
        raise AssertionError(sql)


def test_parse_args_supports_explicit_research_build_scope() -> None:
    args = build_research_adjustment_data.parse_args(
        ["--symbols", "000001.SZ,600519.SH", "--formula-version", "v2", "--full"]
    )

    assert args.symbols == ["000001.SZ", "600519.SH"]
    assert args.formula_version == "v2"
    assert args.full is True


def test_build_writes_candidates_before_publishing_complete_result() -> None:
    store = _Store()

    result = build_research_adjustment_data.build_research_adjustment_data(
        symbols=["000001.SZ"], formula_version="v1", full=False, store=store,
        candidate_builder=lambda **_kwargs: {
            "events": [],
            "factors": [{"symbol": "000001.SZ", "trade_date": "2026-07-16", "forward_factor": 1, "backward_factor": 1}],
        },
        run_id_factory=lambda: "run-1",
    )

    assert result == {"run_id": "run-1", "event_count": 0, "factor_count": 1}
    assert [call[0] for call in store.calls] == ["ensure_tables", "events", "factors", "publish"]
    assert store.calls[-1][1] == {
        "run_id": "run-1", "formula_version": "v1", "completed": True,
        "expected_event_count": 0, "expected_factor_count": 1,
    }


def test_default_build_constructs_candidates_from_mootdx_raw_inputs() -> None:
    store = _Store()

    result = build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", store=store, client=_MootdxClient(), run_id_factory=lambda: "run-raw"
    )

    assert result == {"run_id": "run-raw", "event_count": 1, "factor_count": 2}
    event = store.calls[1][3][0]
    factors = store.calls[2][3]
    assert event["status"] == "approved"
    assert event["ratio"] == 0.9
    assert [(row["trade_date"], row["forward_factor"]) for row in factors] == [
        (date(2026, 7, 15), 0.9),
        (date(2026, 7, 16), 1.0),
    ]


def test_default_incremental_no_change_is_a_successful_unpublished_no_op() -> None:
    store = _Store()

    class _EmptyClient:
        def execute(self, _sql: str, _params: object | None = None):
            return []

    result = build_research_adjustment_data.build_research_adjustment_data(
        symbols=["000001.SZ"], store=store, client=_EmptyClient()
    )

    assert result == {"run_id": None, "event_count": 0, "factor_count": 0, "published": False}
    assert store.calls == []


def test_script_does_not_depend_on_online_data_aggregator() -> None:
    source = build_research_adjustment_data.__file__
    assert "DataAggregator" not in open(source, encoding="utf-8").read()
