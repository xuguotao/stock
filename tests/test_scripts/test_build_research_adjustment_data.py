"""Tests for explicit, fail-closed research adjustment builds."""
from __future__ import annotations

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


def test_build_fails_closed_without_an_injected_candidate_builder() -> None:
    store = _Store()

    try:
        build_research_adjustment_data.build_research_adjustment_data(store=store)
    except RuntimeError as exc:
        assert "candidate builder" in str(exc)
    else:
        raise AssertionError("the build must not publish absent a candidate builder")

    assert store.calls == []


def test_script_does_not_depend_on_online_data_aggregator() -> None:
    source = build_research_adjustment_data.__file__
    assert "DataAggregator" not in open(source, encoding="utf-8").read()
