import pandas as pd

from src.research.fund_tail_backtest import (
    assign_decision,
    assign_sell_decision,
    append_latest_row,
    classify_tail_signals,
    evaluate_proxy_fit,
    evaluate_prediction_profile,
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
    assert "return_3d" in signals.columns
    assert "return_10d" in signals.columns
    assert "ma20_deviation" in signals.columns
    assert "volatility_20d" in signals.columns
    assert "drawdown_20d" in signals.columns
    assert "streak" in signals.columns


def test_prediction_profile_refines_similar_samples_with_feature_regime():
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    signals = pd.DataFrame(
        {
            "date": dates,
            "daily_return": [0.011, 0.012, 0.010, 0.011, 0.012, 0.011, 0.010, 0.012, 0.011, 0.010, 0.011, 0.012],
            "return_5d": [0.03, 0.04, 0.03, 0.04, -0.03, -0.04, -0.03, -0.04, 0.03, 0.04, 0.03, 0.04],
            "ma20_deviation": [0.02, 0.03, 0.02, 0.03, -0.02, -0.03, -0.02, -0.03, 0.02, 0.03, 0.02, 0.03],
            "signal": ["add"] * 12,
            "reason": ["trend_positive_relative_strength"] * 12,
        }
    )
    nav = pd.DataFrame(
        {
            "date": dates,
            "close": [1.00, 1.02, 1.01, 1.03, 1.00, 0.99, 0.98, 0.97, 1.00, 1.02, 1.03, 1.04],
        }
    )

    profile = evaluate_prediction_profile(signals, nav, horizons=(1,), min_samples=3)

    assert "return_5d_positive" in profile["prediction_condition_label"]
    assert "ma20_positive" in profile["prediction_condition_label"]
    assert profile["prediction_h1_count"] == 7


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


def test_evaluates_proxy_fit_correlation_between_nav_and_proxy_returns():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    nav = pd.DataFrame({"date": dates, "close": [1.00, 1.01, 1.02, 1.03, 1.04, 1.05]})
    proxy = pd.DataFrame({"date": dates, "close": [100, 101, 102, 103, 104, 105]})

    result = evaluate_proxy_fit(nav, proxy, min_samples=3)

    assert result["proxy_fit_sample_count"] == 5
    assert round(result["proxy_fit_correlation"], 2) == 1.0
    assert result["proxy_fit_level"] == "high"


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


def test_assigns_take_profit_sell_when_overextended_and_forward_edge_turns_negative():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-15"]),
            "signal": ["watch"],
            "reason": ["overextended_do_not_chase"],
            "daily_return": [0.036],
            "return_5d": [0.055],
            "ma20_deviation": [0.025],
            "daily_return_rank_252d": [0.99],
        }
    )
    prediction = {
        "prediction_score": 30.0,
        "prediction_h3_count": 40,
        "prediction_h3_up_prob": 0.45,
        "prediction_h5_count": 40,
        "prediction_h5_up_prob": 0.40,
        "prediction_h5_median_return": -0.004,
        "prediction_h5_down_gt_2pct": 0.22,
    }

    decision = assign_sell_decision(signals, prediction=prediction)

    assert decision["sell_grade"] == "A"
    assert decision["sell_action"] == "take_profit_reduce"
    assert decision["sell_reason"] == "overextended_forward_edge_negative"
    assert decision["sell_score"] >= 70


def test_assigns_stop_loss_sell_when_weak_trend_has_downside_risk():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-15"]),
            "signal": ["avoid"],
            "reason": ["weak_below_trend"],
            "daily_return": [-0.018],
            "return_5d": [-0.045],
            "ma20_deviation": [-0.035],
            "daily_return_rank_252d": [0.18],
        }
    )
    prediction = {
        "prediction_score": 20.0,
        "prediction_h3_count": 32,
        "prediction_h3_up_prob": 0.35,
        "prediction_h5_count": 32,
        "prediction_h5_up_prob": 0.34,
        "prediction_h5_median_return": -0.012,
        "prediction_h5_down_gt_2pct": 0.38,
    }

    decision = assign_sell_decision(signals, prediction=prediction)

    assert decision["sell_grade"] == "A"
    assert decision["sell_action"] == "stop_loss_reduce"
    assert decision["sell_reason"] == "weak_trend_downside_risk"


def test_assigns_hold_when_pullback_still_has_rebound_probability():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-15"]),
            "signal": ["watch"],
            "reason": ["mixed_signal"],
            "daily_return": [-0.006],
            "return_5d": [0.007],
            "ma20_deviation": [-0.004],
            "daily_return_rank_252d": [0.35],
        }
    )
    prediction = {
        "prediction_score": 58.0,
        "prediction_h3_count": 35,
        "prediction_h3_up_prob": 0.62,
        "prediction_h5_count": 35,
        "prediction_h5_up_prob": 0.57,
        "prediction_h5_median_return": 0.003,
        "prediction_h5_down_gt_2pct": 0.08,
    }

    decision = assign_sell_decision(signals, prediction=prediction)

    assert decision["sell_grade"] == "D"
    assert decision["sell_action"] == "do_not_sell"
    assert decision["sell_reason"] == "pullback_rebound_probability_ok"


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


def test_assigns_wait_when_weak_below_trend_continues_for_two_days():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "signal": ["avoid", "avoid"],
            "reason": ["weak_below_trend", "weak_below_trend"],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [5],
            "count": [60],
            "avg_return": [0.007],
            "median_return": [0.006],
            "win_rate": [0.66],
            "worst_return": [-0.05],
            "drawdown_risk": [0.10],
        }
    ).set_index("horizon")
    condition = {
        "condition_count": 20,
        "condition_next_up_prob": 0.57,
        "condition_next_down_prob": 0.43,
        "condition_next_avg_return": -0.001,
        "condition_next_median_return": 0.002,
        "condition_next_down_gt_1pct": 0.2,
    }

    decision = assign_decision(signals, metrics, condition)

    assert decision["decision_grade"] == "C"
    assert decision["decision_action"] == "wait_for_stabilization"
    assert decision["decision_reason"] == "consecutive_weak_needs_confirmation"


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


def test_evaluates_prediction_profile_for_future_horizons():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    signals = pd.DataFrame(
        {
            "date": dates,
            "daily_return": [0.011, 0.012, 0.009, 0.010, 0.013, -0.02, 0.004, 0.011, 0.012],
            "signal": ["add", "add", "add", "add", "add", "avoid", "watch", "add", "add"],
            "reason": [
                "trend_positive_relative_strength",
                "trend_positive_relative_strength",
                "trend_positive_relative_strength",
                "trend_positive_relative_strength",
                "trend_positive_relative_strength",
                "weak_below_trend",
                "mixed_signal",
                "trend_positive_relative_strength",
                "trend_positive_relative_strength",
            ],
        }
    )
    nav = pd.DataFrame(
        {
            "date": dates,
            "close": [1.00, 1.02, 1.01, 1.04, 1.05, 1.08, 1.07, 1.09, 1.10],
        }
    )

    profile = evaluate_prediction_profile(signals, nav, horizons=(1, 3), min_samples=3)

    assert profile["prediction_condition_label"] == "trend_positive_relative_strength_daily_0.2%_2.2%"
    assert profile["prediction_h1_count"] == 6
    assert round(profile["prediction_h1_up_prob"], 4) == 0.8333
    assert profile["prediction_h3_count"] == 5
    assert round(profile["prediction_h3_median_return"], 4) > 0


def test_prediction_profile_downgrades_high_chase_when_edge_is_weak():
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "signal": ["add"],
            "reason": ["trend_positive_relative_strength"],
            "daily_return": [0.023],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [5],
            "count": [80],
            "avg_return": [0.008],
            "median_return": [0.006],
            "win_rate": [0.65],
            "worst_return": [-0.04],
            "drawdown_risk": [0.1],
        }
    ).set_index("horizon")
    prediction = {
        "prediction_score": 54.0,
        "prediction_h3_count": 50,
        "prediction_h3_up_prob": 0.51,
        "prediction_h5_count": 50,
        "prediction_h5_median_return": 0.001,
        "prediction_h5_down_gt_2pct": 0.08,
    }

    decision = assign_decision(signals, metrics, prediction=prediction)

    assert decision["decision_grade"] == "C"
    assert decision["decision_action"] == "wait_for_pullback"
    assert decision["decision_reason"] == "prediction_chase_risk"


def test_converts_report_to_chinese_columns_and_values():
    report = pd.DataFrame(
        [
            {
                "fund_name": "华夏中证500指数增强C",
                "fund_code": "007995",
                "proxy_name": "中证500",
                "proxy_code": "000905",
                "proxy_fit_correlation": 0.782,
                "proxy_fit_level": "high",
                "latest_date": pd.Timestamp("2026-06-10"),
                "latest_daily_return": -0.022,
                "latest_return_5d": 0.0312,
                "latest_ma20_deviation": -0.014,
                "latest_daily_return_rank_252d": 0.82,
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
    assert "代理标的" in result.columns
    assert "代理匹配度" in result.columns
    assert "今日代理涨跌率" in result.columns
    assert "最终操作建议" in result.columns
    assert result.iloc[0]["技术信号"] == "回避"
    assert result.iloc[0]["信号原因"] == "弱于趋势"
    assert result.iloc[0]["最终操作建议"] == "小额试探"
    assert result.iloc[0]["建议原因"] == "同类历史反弹概率略高"
    assert result.iloc[0]["今日代理涨跌率"] == "-2.20%"
    assert result.iloc[0]["近5日涨跌率"] == "3.12%"
    assert result.iloc[0]["偏离20日均线"] == "-1.40%"
    assert result.iloc[0]["今日涨跌分位"] == "82.00%"
    assert result.iloc[0]["代理标的"] == "中证500"
    assert result.iloc[0]["代理匹配度"] == "78.20%"
    assert result.iloc[0]["代理匹配等级"] == "高"


def test_converts_report_to_chinese_sorted_by_latest_daily_return_descending():
    report = pd.DataFrame(
        [
            {
                "fund_name": "华夏中证500指数增强C",
                "fund_code": "007995",
                "latest_daily_return": -0.022,
            },
            {
                "fund_name": "天弘中证食品饮料ETF联接C",
                "fund_code": "001632",
                "latest_daily_return": 0.015,
            },
            {
                "fund_name": "华宝纳斯达克精选股票(QDII)C",
                "fund_code": "017437",
                "latest_daily_return": -0.003,
            },
        ]
    )

    result = to_chinese_report(report)

    assert result["基金代码"].tolist() == ["001632", "017437", "007995"]
    assert result["今日代理涨跌率"].tolist() == ["1.50%", "-0.30%", "-2.20%"]
