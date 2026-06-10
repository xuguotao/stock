import pandas as pd

from src.research.fund_tail_backtest import (
    assign_decision,
    append_latest_row,
    classify_tail_signals,
    evaluate_latest_condition,
    normalize_akshare_cni_index,
    normalize_akshare_index,
    normalize_akshare_nav,
    normalize_akshare_us_daily,
    to_chinese_report,
    select_proxy_series,
    evaluate_forward_returns,
    summarize_latest_signal,
)


def test_classifies_add_when_trend_positive_and_not_overextended():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    proxy = pd.DataFrame(
        {
            "date": dates,
            "close": [100, 101, 102, 103, 104, 105, 106, 106.8],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": dates,
            "close": [100, 100.5, 101, 101.5, 102, 102.4, 102.8, 103.0],
        }
    )

    signals = classify_tail_signals(proxy, benchmark=benchmark, lookback=5)

    assert signals.iloc[-1]["signal"] == "add"
    assert signals.iloc[-1]["reason"] == "trend_positive_relative_strength"


def test_evaluates_forward_returns_only_on_add_signals():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    signals = pd.DataFrame(
        {
            "date": dates,
            "signal": ["watch", "add", "avoid", "add", "watch", "watch"],
        }
    )
    nav = pd.DataFrame(
        {
            "date": dates,
            "close": [1.00, 1.00, 1.02, 1.01, 1.03, 1.04],
        }
    )

    result = evaluate_forward_returns(signals, nav, horizons=(1, 2))

    assert result.loc[1, "count"] == 2
    assert round(result.loc[1, "avg_return"], 4) == 0.0199
    assert round(result.loc[1, "median_return"], 4) == 0.0199
    assert round(result.loc[1, "win_rate"], 4) == 1.0
    assert result.loc[1, "drawdown_risk"] == 0.0
    assert round(result.loc[2, "avg_return"], 4) == 0.0199


def test_summarizes_latest_signal_with_metrics():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "signal": ["watch", "add"],
            "reason": ["mixed_signal", "trend_positive_relative_strength"],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [1],
            "count": [3],
            "avg_return": [0.0123],
            "win_rate": [0.6667],
            "worst_return": [-0.01],
        }
    ).set_index("horizon")

    row = summarize_latest_signal("华夏中证500指数增强C", "007995", signals, metrics)

    assert row["fund_name"] == "华夏中证500指数增强C"
    assert row["latest_signal"] == "add"
    assert row["latest_reason"] == "trend_positive_relative_strength"
    assert row["decision_grade"] == "A"
    assert row["decision_action"] == "tail_add"
    assert row["h1_avg_return"] == 0.0123
    assert row["h1_median_return"] == 0.0123


def test_assigns_wait_for_pullback_when_latest_signal_is_overextended():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "signal": ["watch"],
            "reason": ["overextended_do_not_chase"],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [5],
            "count": [20],
            "avg_return": [0.01],
            "median_return": [0.008],
            "win_rate": [0.7],
            "worst_return": [-0.04],
            "drawdown_risk": [0.2],
        }
    ).set_index("horizon")

    decision = assign_decision(signals, metrics)

    assert decision["decision_grade"] == "C"
    assert decision["decision_action"] == "wait_for_pullback"
    assert decision["decision_reason"] == "latest_proxy_overextended"


def test_assigns_avoid_when_history_has_weak_edge():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "signal": ["add"],
            "reason": ["trend_positive_relative_strength"],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [5],
            "count": [20],
            "avg_return": [-0.002],
            "median_return": [-0.001],
            "win_rate": [0.45],
            "worst_return": [-0.05],
            "drawdown_risk": [0.55],
        }
    ).set_index("horizon")

    decision = assign_decision(signals, metrics)

    assert decision["decision_grade"] == "D"
    assert decision["decision_action"] == "do_not_add"
    assert decision["decision_reason"] == "historical_edge_weak"


def test_assigns_small_probe_for_weak_pullback_with_positive_history():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "signal": ["avoid"],
            "reason": ["weak_below_trend"],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [5, 10],
            "count": [60, 60],
            "avg_return": [0.007, 0.016],
            "median_return": [0.006, 0.015],
            "win_rate": [0.66, 0.78],
            "worst_return": [-0.05, -0.08],
            "drawdown_risk": [0.10, 0.08],
        }
    ).set_index("horizon")

    decision = assign_decision(signals, metrics)

    assert decision["decision_grade"] == "B"
    assert decision["decision_action"] == "small_probe"
    assert decision["decision_reason"] == "pullback_with_positive_history"


def test_normalizes_akshare_nav_columns():
    raw = pd.DataFrame(
        {
            "净值日期": ["2026-01-01", "2026-01-02"],
            "单位净值": [1.0, 1.01],
            "日增长率": [0.0, 1.0],
        }
    )

    result = normalize_akshare_nav(raw)

    assert list(result.columns) == ["date", "close"]
    assert result.iloc[-1]["close"] == 1.01


def test_normalizes_akshare_index_columns():
    raw = pd.DataFrame(
        {
            "日期": ["2026-01-01", "2026-01-02"],
            "收盘": [1000.0, 1002.0],
            "成交量": [10, 20],
        }
    )

    result = normalize_akshare_index(raw)

    assert list(result.columns) == ["date", "close", "volume"]
    assert result.iloc[-1]["close"] == 1002.0


def test_normalizes_akshare_cni_index_columns():
    raw = pd.DataFrame(
        {
            "日期": ["2026-01-01", "2026-01-02"],
            "收盘价": [1000.0, 1002.0],
            "成交量": [10, 20],
        }
    )

    result = normalize_akshare_cni_index(raw)

    assert list(result.columns) == ["date", "close", "volume"]
    assert result.iloc[-1]["close"] == 1002.0


def test_normalizes_akshare_us_daily_columns():
    raw = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 2000],
        }
    )

    result = normalize_akshare_us_daily(raw)

    assert list(result.columns) == ["date", "close", "volume"]
    assert result.iloc[-1]["close"] == 102.0


def test_selects_nav_as_proxy_when_index_proxy_missing():
    nav = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "close": [1.0, 1.01],
        }
    )

    result = select_proxy_series(nav=nav, proxy=None)

    assert result.equals(nav)


def test_append_latest_row_replaces_same_date_and_preserves_order():
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09", "2026-06-10"]),
            "close": [100.0, 101.0],
            "volume": [1000, 1000],
        }
    )
    latest = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-10"]),
            "close": [102.0],
            "volume": [2000],
        }
    )

    result = append_latest_row(history, latest)

    assert result.shape[0] == 2
    assert result.iloc[-1]["date"] == pd.Timestamp("2026-06-10")
    assert result.iloc[-1]["close"] == 102.0
    assert result.iloc[-1]["volume"] == 2000


def test_evaluates_latest_condition_by_same_reason_and_return_band():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    signals = pd.DataFrame(
        {
            "date": dates,
            "daily_return": [-0.021, -0.018, -0.024, 0.01, -0.019, -0.022, 0.005, -0.02],
            "signal": ["avoid", "avoid", "avoid", "watch", "avoid", "avoid", "watch", "avoid"],
            "reason": [
                "weak_below_trend",
                "weak_below_trend",
                "weak_below_trend",
                "mixed_signal",
                "weak_below_trend",
                "weak_below_trend",
                "mixed_signal",
                "weak_below_trend",
            ],
        }
    )
    nav = pd.DataFrame(
        {
            "date": dates,
            "close": [1.00, 1.01, 1.00, 1.02, 1.01, 1.03, 1.02, 1.04],
        }
    )

    result = evaluate_latest_condition(signals, nav, min_samples=3)

    assert result["condition_label"] == "weak_below_trend_daily_-3.0%_-1.0%"
    assert result["condition_count"] == 5
    assert round(result["condition_next_up_prob"], 4) == 0.6
    assert round(result["condition_next_down_prob"], 4) == 0.4


def test_converts_report_to_chinese_columns_and_values():
    report = pd.DataFrame(
        [
            {
                "fund_name": "华夏中证500指数增强C",
                "fund_code": "007995",
                "latest_date": pd.Timestamp("2026-06-10"),
                "latest_daily_return": -0.022,
                "latest_signal": "avoid",
                "latest_reason": "weak_below_trend",
                "decision_grade": "B",
                "decision_action": "small_probe",
                "decision_reason": "similar_history_rebound_slightly_higher",
                "condition_next_up_prob": 0.5758,
                "condition_next_down_prob": 0.4242,
            }
        ]
    )

    result = to_chinese_report(report)

    assert "基金名称" in result.columns
    assert "今日代理涨跌率" in result.columns
    assert "最终操作建议" in result.columns
    assert result.iloc[0]["技术信号"] == "回避"
    assert result.iloc[0]["信号原因"] == "弱于趋势"
    assert result.iloc[0]["最终操作建议"] == "小额试探"
    assert result.iloc[0]["建议原因"] == "同类历史反弹概率略高"
    assert result.iloc[0]["今日代理涨跌率"] == -0.022
