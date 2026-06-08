"""因子IC (Information Coefficient) 分析.

IC衡量因子值与未来收益率的截面相关性。
- IC: Pearson相关系数
- RankIC: Spearman秩相关系数
- ICIR: IC均值 / IC标准差

Usage:
    analyzer = ICAnalyzer()
    ic = analyzer.compute_ic(factor_values, forward_returns)
    summary = analyzer.ic_summary(ic)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ICSummary:
    """IC统计汇总."""
    ic_mean: float
    ic_std: float
    icir: float              # IC / std(IC)
    ic_positive_ratio: float # IC > 0 的比例
    rank_ic_mean: float
    rank_ic_std: float
    rank_icir: float
    rank_ic_positive_ratio: float

    def to_dict(self) -> dict[str, float]:
        return {
            "ic_mean": round(self.ic_mean, 4),
            "ic_std": round(self.ic_std, 4),
            "icir": round(self.icir, 4),
            "ic_positive_ratio": round(self.ic_positive_ratio, 4),
            "rank_ic_mean": round(self.rank_ic_mean, 4),
            "rank_ic_std": round(self.rank_ic_std, 4),
            "rank_icir": round(self.rank_icir, 4),
            "rank_ic_positive_ratio": round(self.rank_ic_positive_ratio, 4),
        }


class ICAnalyzer:
    """因子IC分析器."""

    def __init__(self, forward_period: int = 1):
        self.forward_period = forward_period

    def compute_ic(
        self,
        factor_values: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> pd.Series:
        """计算逐日IC值.

        Args:
            factor_values: MultiIndex (date, symbol), factor values
            forward_returns: MultiIndex (date, symbol), forward returns

        Returns:
            Series of daily IC values indexed by date.
        """
        # Align factor and returns
        aligned = factor_values.join(forward_returns, how="inner", rsuffix="_ret")
        dates = aligned.index.get_level_values(0).unique()

        ic_values = []
        ic_dates = []

        for d in dates:
            try:
                fv = aligned.loc[d].iloc[:, 0]  # factor column
                fr = aligned.loc[d].iloc[:, 1]  # return column
            except (IndexError, KeyError):
                continue

            # Need at least 3 observations
            valid = ~(fv.isna() | fr.isna())
            if valid.sum() < 3:
                continue

            ic = fv[valid].corr(fr[valid], method="pearson")
            ic_values.append(ic)
            ic_dates.append(d)

        return pd.Series(ic_values, index=ic_dates, name="ic")

    def compute_rank_ic(
        self,
        factor_values: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> pd.Series:
        """计算逐日Rank IC (Spearman)."""
        aligned = factor_values.join(forward_returns, how="inner", rsuffix="_ret")
        dates = aligned.index.get_level_values(0).unique()

        ric_values = []
        ric_dates = []

        for d in dates:
            try:
                fv = aligned.loc[d].iloc[:, 0]
                fr = aligned.loc[d].iloc[:, 1]
            except (IndexError, KeyError):
                continue

            valid = ~(fv.isna() | fr.isna())
            if valid.sum() < 3:
                continue

            ric = fv[valid].corr(fr[valid], method="spearman")
            ric_values.append(ric)
            ric_dates.append(d)

        return pd.Series(ric_values, index=ric_dates, name="rank_ic")

    def compute_forward_returns(
        self,
        prices: pd.DataFrame,
        periods: int | None = None,
    ) -> pd.DataFrame:
        """计算前向收益率.

        Args:
            prices: DataFrame with DatetimeIndex (date) and columns as symbols.
            periods: Forward period (default: self.forward_period)

        Returns:
            MultiIndex (date, symbol) forward returns.
        """
        p = periods or self.forward_period
        returns = prices.pct_change(p).shift(-p)
        # Stack to MultiIndex (date, symbol)
        return returns.stack(future_stack=True).to_frame(name="return").rename_axis(["date", "symbol"])["return"].to_frame()

    def ic_summary(
        self,
        ic: pd.Series,
        rank_ic: pd.Series | None = None,
    ) -> ICSummary:
        """计算IC统计汇总."""
        ic_valid = ic.dropna()

        if rank_ic is None:
            rank_ic = ic  # fallback

        ric_valid = rank_ic.dropna()

        return ICSummary(
            ic_mean=float(ic_valid.mean()),
            ic_std=float(ic_valid.std()),
            icir=float(ic_valid.mean() / ic_valid.std()) if ic_valid.std() > 0 else 0,
            ic_positive_ratio=float((ic_valid > 0).mean()),
            rank_ic_mean=float(ric_valid.mean()),
            rank_ic_std=float(ric_valid.std()),
            rank_icir=float(ric_valid.mean() / ric_valid.std()) if ric_valid.std() > 0 else 0,
            rank_ic_positive_ratio=float((ric_valid > 0).mean()),
        )

    def plot_ic(self, ic: pd.Series, title: str = "Factor IC Over Time") -> None:
        """Plot IC time series."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.bar(ic.index, ic.values, color=ic.apply(lambda x: "green" if x > 0 else "red"), alpha=0.6)
        ax.axhline(y=0, color="black", linewidth=0.5)
        ax.axhline(y=ic.mean(), color="blue", linestyle="--", label=f"Mean IC = {ic.mean():.4f}")
        ax.set_ylabel("IC")
        ax.set_xlabel("Date")
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()
