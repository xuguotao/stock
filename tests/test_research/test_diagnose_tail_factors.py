import pandas as pd

from scripts.diagnose_tail_factors import compute_overnight_forward_return


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
