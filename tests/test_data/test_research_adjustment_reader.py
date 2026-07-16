"""Tests for the isolated, versioned research adjustment reader."""
from __future__ import annotations

from datetime import date, datetime

from src.data.research_adjustment_reader import ResearchAdjustmentReader


class _Client:
    def __init__(self, *, current_run: tuple[object, ...] | None, rows: list[tuple[object, ...]]) -> None:
        self.current_run = current_run
        self.rows = rows
        self.calls: list[tuple[str, object | None]] = []

    def execute(self, sql: str, params: object | None = None) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        normalized = " ".join(sql.lower().split())
        if "from research_adjustment_runs final" in normalized:
            return [self.current_run] if self.current_run else []
        if "from research_adjustment_raw_bars final" in normalized:
            return self.rows
        raise AssertionError(f"unexpected SQL: {sql}")


def test_reader_returns_raw_and_both_adjusted_price_conventions() -> None:
    client = _Client(
        current_run=("run-7", "v1", datetime(2026, 7, 16, 17, 25), datetime(2026, 7, 16, 17, 20), 21),
        rows=[("000001.SZ", date(2026, 7, 15), 10.0, 12.0, 9.0, 11.0, 1000, 11000.0, 0.5, 2.0, "approved")],
    )

    bars = ResearchAdjustmentReader(client=client).get_bars(
        ["000001.SZ"], date(2026, 7, 1), date(2026, 7, 31), "v1"
    )

    row = bars.iloc[0]
    assert row.raw_open == 10.0
    assert row.forward_close == 5.5
    assert row.backward_high == 24.0
    assert row.forward_volume == 2000.0
    assert row.backward_volume == 500.0
    assert row.raw_amount == row.forward_amount == row.backward_amount == 11000.0
    assert row.quality_status == "approved"
    sql, params = client.calls[-1]
    assert "research_adjustment_raw_bars final" in sql.lower()
    assert "mootdx_stock_kline" not in sql.lower()
    assert "research_daily_adjustment_factors final" in sql.lower()
    assert params["run_id"] == "run-7"
    assert params["formula_version"] == "v1"


def test_reader_fails_closed_when_formula_has_no_published_run() -> None:
    client = _Client(current_run=None, rows=[])

    bars = ResearchAdjustmentReader(client=client).get_bars(
        ["000001.SZ"], date(2026, 7, 1), date(2026, 7, 31), "v1"
    )

    assert bars.empty
    assert len(client.calls) == 1


def test_reader_returns_empty_when_current_run_has_no_matching_factors() -> None:
    client = _Client(current_run=("run-7", "v1", datetime.now(), datetime(2026, 7, 16, 17, 20), 21), rows=[])

    bars = ResearchAdjustmentReader(client=client).get_bars(
        ["000001.SZ"], date(2026, 7, 1), date(2026, 7, 31), "v1"
    )

    assert bars.empty
    assert len(client.calls) == 2
