"""Stock price adjustment (复权) calculation."""
from __future__ import annotations

import pandas as pd


def compute_adjustment_ratios(events: pd.DataFrame) -> pd.DataFrame:
    """Compute per-event adjustment ratios from xdxr events.

    Args:
        events: DataFrame with columns:
            - ex_date: date of the ex-rights/ex-dividend
            - fenhong: cash dividend per share (元)
            - songzhuangu: bonus shares per share (股)
            - peigu: rights issue shares per share (股)
            - suogu: consolidation ratio (缩后股数)
            - pre_close: close price on the day before ex_date
            - peigujia: (optional) rights issue price (元), defaults to 0

    Returns:
        DataFrame sorted by ex_date with added column:
            - ratio: adjustment ratio (除权后理论价 / 除权前收盘价)
    """
    if events.empty:
        return events.copy()

    result = events.sort_values("ex_date").reset_index(drop=True)

    # Extract columns with defaults
    peigujia = result.get("peigujia", pd.Series(0.0, index=result.index)).fillna(0.0)
    pre_close = result["pre_close"].fillna(0.0)
    fenhong = result["fenhong"].fillna(0.0)
    songzhuangu = result["songzhuangu"].fillna(0.0)
    peigu = result["peigu"].fillna(0.0)
    suogu = result["suogu"].fillna(0.0)

    # ratio = (pre_close - fenhong + peigu * peigujia) / (pre_close + songzhuangu + peigu) * suogu_factor
    # suogu == 0 means no consolidation; treat as 1.0
    suogu_factor = suogu.where(suogu > 0, 1.0)

    numerator = pre_close - fenhong + peigu * peigujia
    denominator = pre_close + songzhuangu + peigu

    # Guard against division by zero
    ratio = numerator / denominator.replace(0, float("nan")) * suogu_factor
    ratio = ratio.fillna(1.0)

    result = result.copy()
    result["ratio"] = ratio
    return result


def apply_forward_adjustment(
    bars: pd.DataFrame,
    ratios: pd.DataFrame,
) -> pd.DataFrame:
    """Apply forward adjustment (前复权) to OHLCV bars.

    Latest price stays unchanged; historical prices are scaled down
    by cumulative ratios of all future xdxr events.

    Args:
        bars: DataFrame with columns including date, close, symbol.
              Must be sorted by date ascending.
        ratios: DataFrame from compute_adjustment_ratios with columns ex_date, ratio.

    Returns:
        Copy of bars with added/updated 'adjusted_close' column (前复权收盘价).
    """
    result = bars.copy()
    if ratios.empty:
        result["adjusted_close"] = result["close"]
        return result

    sorted_ratios = ratios.sort_values("ex_date").reset_index(drop=True)
    ex_dates = sorted_ratios["ex_date"].values
    ratio_values = sorted_ratios["ratio"].values

    # For each bar date, compute cumulative product of all ratios where ex_date > bar_date
    adjusted = []
    for bar_date in result["date"].values:
        mask = ex_dates > bar_date
        cum_ratio = ratio_values[mask].prod() if mask.any() else 1.0
        adjusted.append(cum_ratio)

    result["adjusted_close"] = result["close"] * adjusted
    return result


def apply_backward_adjustment(
    bars: pd.DataFrame,
    ratios: pd.DataFrame,
) -> pd.DataFrame:
    """Apply backward adjustment (后复权) to OHLCV bars.

    Earliest price stays unchanged; later prices are scaled up
    by cumulative ratios of all past xdxr events.

    Args:
        bars: DataFrame with columns including date, close, symbol.
              Must be sorted by date ascending.
        ratios: DataFrame from compute_adjustment_ratios with columns ex_date, ratio.

    Returns:
        Copy of bars with added/updated 'adjusted_close' column (后复权收盘价).
    """
    result = bars.copy()
    if ratios.empty:
        result["adjusted_close"] = result["close"]
        return result

    sorted_ratios = ratios.sort_values("ex_date").reset_index(drop=True)
    ex_dates = sorted_ratios["ex_date"].values
    ratio_values = sorted_ratios["ratio"].values

    # For each bar date, compute cumulative product of all ratios where ex_date <= bar_date
    adjusted = []
    for bar_date in result["date"].values:
        mask = ex_dates <= bar_date
        cum_ratio = ratio_values[mask].prod() if mask.any() else 1.0
        adjusted.append(cum_ratio)

    result["adjusted_close"] = result["close"] / adjusted
    return result
