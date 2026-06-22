from pathlib import Path


def test_signal_review_page_shows_recent_daily_outcomes() -> None:
    source = Path("frontend/src/pages/SignalReview.vue").read_text(encoding="utf-8")

    assert "近期复盘" in source
    assert "已完成复盘" in source
    assert "跟踪中信号" in source
    assert "最终入选胜率" in source
    assert "selected_overall" in source
    assert "selected_recent" in source
    assert "stats?.recent" in source
    assert 'prop="date"' in source
    assert "avg_close_return" in source
    assert "交易执行口径" in source
    assert "单票复盘明细" in source
    assert "次日最高收益" in source
    assert "次日最低回撤" in source
    assert "按模式" in source
    assert "execution_summary" in source
    assert "details" in source
    assert "avg_max_return" in source
    assert "avg_min_return" in source
    assert "复核状态" in source
    assert "当前收益" in source
    assert "reviewStatusText" in source
