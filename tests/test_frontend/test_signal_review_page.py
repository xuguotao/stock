from pathlib import Path


def test_signal_review_page_shows_recent_daily_outcomes() -> None:
    source = Path("frontend/src/pages/SignalReview.vue").read_text(encoding="utf-8")

    assert "尾盘策略复盘" in source
    assert "近期复盘" in source
    assert "正式选股已复盘" in source
    assert "待复盘信号" in source
    assert "补算全部待复盘" in source
    assert "复盘补算计划" in source
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
    assert "按可信度" in source
    assert "按量比确认" in source
    assert "按尾盘形态" in source
    assert "execution_summary" in source
    assert "details" in source
    assert "avg_max_return" in source
    assert "avg_min_return" in source
    assert "复核状态" in source
    assert "当前收益" in source
    assert "表现标签" in source
    assert "回撤风险" in source
    assert "reviewStatusText" in source
    assert "review_plan" in source
    assert "pending_signal_count" in source
    assert "pending_dates" in source
    assert "mode: 'pending'" in source
    assert "by_confidence" in source
    assert "by_volume_ratio" in source
    assert "by_tail_return" in source
    assert "execution_label" in source
    assert "risk_label" in source
