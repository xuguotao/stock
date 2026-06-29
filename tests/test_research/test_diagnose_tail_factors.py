import numpy as np
import pandas as pd

from scripts.diagnose_tail_factors import compute_overnight_forward_return, run_diagnosis


def _fake_bars():
    idx = pd.MultiIndex.from_tuples(
        [("2025-01-01", "000001.SZ"), ("2025-01-02", "000001.SZ"),
         ("2025-01-01", "600519.SH"), ("2025-01-02", "600519.SH")],
        names=["date", "symbol"],
    )
    return pd.DataFrame(
        {"open": [9.0, 9.9, 100.0, 102.0], "close": [10.0, 10.0, 100.0, 101.0],
         "high": [10.5, 10.5, 101.0, 103.0], "low": [8.5, 9.5, 99.0, 100.5],
         "volume": [1000, 1100, 500, 520]}, index=idx)


def test_overnight_forward_return_uses_next_open_over_close():
    bars = _fake_bars()
    fr = compute_overnight_forward_return(bars)
    # 000001: open(01-02)/close(01-01) - 1 = 9.9/10.0 - 1 = -0.01
    val = fr.loc[("2025-01-01", "000001.SZ"), "return"]
    assert round(float(val), 4) == -0.01
    # 最后一日无次日 open -> NaN
    assert pd.isna(fr.loc[("2025-01-02", "000001.SZ"), "return"])


def _fake_bars_more():
    """6 symbols × 26 business days.

    Three symbols trend up strongly so TailSessionFactor breakouts trigger
    after the 20-bar warmup (cross-sectional factor variation on days 21+);
    three symbols decline so they never break out. Overnight gaps differ per
    symbol so forward returns (overnight open/close-1) and OvernightMomentum
    are non-degenerate, giving ICAnalyzer (≥3 obs/day) and QuantileAnalyzer
    (n_quantiles=3) valid observations each day.
    """
    dates = pd.bdate_range("2025-01-02", periods=26)
    symbols = ["600519.SH", "000001.SZ", "300750.SZ",
               "000858.SZ", "601318.SH", "600036.SH"]
    slopes = {
        "600519.SH": 0.02, "000001.SZ": 0.02, "300750.SZ": 0.02,
        "000858.SZ": -0.005, "601318.SH": -0.005, "600036.SH": -0.005,
    }
    gap_means = {
        "600519.SH": 0.006, "000001.SZ": 0.005, "300750.SZ": 0.004,
        "000858.SZ": 0.003, "601318.SH": 0.002, "600036.SH": 0.001,
    }
    close = {s: 100.0 for s in symbols}
    rows = []
    for t, d in enumerate(dates):
        for i, s in enumerate(symbols):
            prev_close = close[s]
            gap = gap_means[s] + 0.0008 * np.sin(t + i)
            open_ = prev_close * (1.0 + gap)
            new_close = prev_close * (1.0 + slopes[s]) * (1.0 + 0.5 * gap)
            high = max(open_, new_close) * 1.003
            low = min(open_, new_close) * 0.997
            # 600519.SH ramps volume so it clears the 1.2x avg-ratio threshold
            # (factor=1.0); the other trending symbols stay flat (factor=0.7),
            # giving the tail_session factor 3 distinct levels post-warmup.
            volume = (1_000_000 + 200_000 * t) if s == "600519.SH" else 1_000_000
            rows.append((d, s, round(open_, 4), round(high, 4),
                         round(low, 4), round(new_close, 4), volume))
            close[s] = new_close
    df = pd.DataFrame(
        rows, columns=["date", "symbol", "open", "high", "low", "close", "volume"]
    )
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index(["date", "symbol"]).sort_index()


def test_run_diagnosis_returns_ic_and_quantile_per_factor():
    bars = _fake_bars_more()  # ≥5 symbols × ≥5 days，保证 qcut 与 IC 有有效观测
    result = run_diagnosis(bars, n_quantiles=3)
    assert result["forward_return"] == "overnight_open/close-1"
    names = {f["factor"] for f in result["factors"]}
    assert names == {"tail_session", "overnight_momentum"}
    for f in result["factors"]:
        assert "ic_mean" in f["ic"] and "rank_icir" in f["ic"]
        assert "spread_return" in f["quantile"] and "monotonicity" in f["quantile"]


def test_main_writes_json_with_factor_results(tmp_path, monkeypatch):
    """main() loads bars via _load_bars and writes IC/quantile JSON to --out."""
    import json
    import scripts.diagnose_tail_factors as mod

    monkeypatch.setattr(mod, "_load_bars", lambda args: _fake_bars_more())
    out = tmp_path / "factor_diagnosis.json"
    monkeypatch.setattr(
        "sys.argv",
        ["diagnose_tail_factors.py", "--n-quantiles", "3", "--out", str(out)],
    )
    mod.main()

    payload = json.loads(out.read_text())
    assert payload["forward_return"] == "overnight_open/close-1"
    names = {f["factor"] for f in payload["factors"]}
    assert names == {"tail_session", "overnight_momentum"}
    for f in payload["factors"]:
        assert "ic_mean" in f["ic"] and "rank_icir" in f["ic"]
        assert "spread_return" in f["quantile"] and "monotonicity" in f["quantile"]
