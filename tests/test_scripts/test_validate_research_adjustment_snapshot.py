"""Tests for the repeatable research-adjustment acceptance report."""
from __future__ import annotations

from scripts.validate_research_adjustment_snapshot import render_report


def test_render_report_separates_automated_checks_from_external_verification() -> None:
    report = render_report(
        run={"run_id": "run-1", "formula_version": "v1", "input_ingest_seq": 3},
        coverage={"raw_bar_count": 10, "factor_count": 10, "coverage_mismatch_count": 0},
        events={"approved": 2, "unverified": 1},
        factors={"approved": 8, "unverified": 2},
        continuity={"approved_count": 2, "max_abs_error": 0.02, "p95_abs_error": 0.025},
        nontrivial={"bar_count": 5, "symbol_count": 2, "min_forward_factor": 0.8, "max_forward_factor": 0.99},
        samples=[{"symbol": "000001.SZ", "event_date": "2026-07-17", "ratio": 0.97, "abs_error": 0.02}],
    )

    assert "# 研究复权准确性验收报告" in report
    assert "run-1" in report
    assert "通过（自动检查）" in report
    assert "外部权威公告核验：待完成" in report
    assert "连续性警戒：需要人工复核" in report
    assert "000001.SZ" in report
    assert "0.020000" in report
