from pathlib import Path


def test_signal_review_page_shows_recent_daily_outcomes() -> None:
    source = Path("frontend/src/pages/SignalReview.vue").read_text(encoding="utf-8")

    assert "近期复盘" in source
    assert "最终入选胜率" in source
    assert "selected_overall" in source
    assert "selected_recent" in source
    assert "stats?.recent" in source
    assert 'prop="date"' in source
    assert "avg_close_return" in source
