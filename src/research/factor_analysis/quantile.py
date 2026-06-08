"""因子分层收益分析 (Quantile Analysis).

将股票按因子值分为N组（通常5或10组），计算每组的收益率，
观察因子是否有单调性（monotonicity）。

Usage:
    qa = QuantileAnalyzer(n_quantiles=5)
    result = qa.analyze(factor_values, forward_returns)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class QuantileResult:
    """分层分析结果."""
    quantile_returns: pd.DataFrame     # (date, quantile) -> mean return
    cumulative_returns: pd.DataFrame   # cumulative by quantile
    spread: float                      # Q_top - Q_bottom return
    monotonicity: float                # correlation of quantile rank vs mean return

    @property
    def summary(self) -> dict:
        return {
            "spread_return": round(self.spread * 100, 4),
            "monotonicity": round(self.monotonicity, 4),
            "top_quantile_ann_return": round(
                (1 + self.quantile_returns.iloc[:, -1].mean()) ** 252 - 1, 4
            ) * 100 if len(self.quantile_returns.columns) > 1 else 0,
        }


class QuantileAnalyzer:
    """因子分层收益分析."""

    def __init__(self, n_quantiles: int = 5):
        self.n_quantiles = n_quantiles

    def analyze(
        self,
        factor_values: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> QuantileResult:
        """Run quantile analysis.

        Args:
            factor_values: MultiIndex (date, symbol), factor values
            forward_returns: MultiIndex (date, symbol), forward returns

        Returns:
            QuantileResult with returns by quantile.
        """
        # Align
        aligned = factor_values.join(forward_returns, how="inner", rsuffix="_ret")
        dates = aligned.index.get_level_values(0).unique()

        quantile_returns = []

        for d in dates:
            try:
                fv = aligned.loc[d].iloc[:, 0]
                fr = aligned.loc[d].iloc[:, 1]
            except (IndexError, KeyError):
                continue

            valid = ~(fv.isna() | fr.isna())
            if valid.sum() < self.n_quantiles:
                continue

            fv_valid = fv[valid]
            fr_valid = fr[valid]

            # Assign quantiles
            try:
                quantiles = pd.qcut(fv_valid, self.n_quantiles, labels=False, duplicates="drop")
            except ValueError:
                # Not enough unique values
                continue

            # Mean return per quantile
            df = pd.DataFrame({"return": fr_valid, "quantile": quantiles})
            q_ret = df.groupby("quantile")["return"].mean()
            quantile_returns.append(q_ret)

        if not quantile_returns:
            return QuantileResult(
                quantile_returns=pd.DataFrame(),
                cumulative_returns=pd.DataFrame(),
                spread=0.0,
                monotonicity=0.0,
            )

        qr = pd.DataFrame(quantile_returns)
        qr.columns = [f"Q{i+1}" for i in range(len(qr.columns))]

        # Cumulative returns
        cum_ret = (1 + qr).cumprod()

        # Spread: top - bottom
        spread = (qr.iloc[:, -1] - qr.iloc[:, 0]).mean()

        # Monotonicity: correlation between quantile index and mean return
        mean_by_q = qr.mean()
        monotonicity = mean_by_q.corr(pd.Series(range(1, len(mean_by_q) + 1), index=mean_by_q.index), method="spearman")

        return QuantileResult(
            quantile_returns=qr,
            cumulative_returns=cum_ret,
            spread=float(spread),
            monotonicity=float(monotonicity),
        )

    def plot(self, result: QuantileResult, title: str = "Quantile Returns") -> None:
        """Plot quantile analysis results."""
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        # Mean return by quantile
        ax1 = axes[0]
        mean_ret = result.quantile_returns.mean() * 252 * 100
        colors = ["red" if v < 0 else "green" for v in mean_ret]
        ax1.bar(mean_ret.index, mean_ret.values, color=colors, alpha=0.7)
        ax1.set_ylabel("Annualized Mean Return (%)")
        ax1.set_xlabel("Quantile")
        ax1.set_title("Mean Return by Quantile")
        ax1.grid(True, alpha=0.3)

        # Cumulative returns
        ax2 = axes[1]
        result.cumulative_returns.plot(ax=ax2, linewidth=2)
        ax2.set_ylabel("Cumulative Return")
        ax2.set_xlabel("Trading Days")
        ax2.set_title("Cumulative Returns by Quantile")
        ax2.legend(title="Quantile")
        ax2.grid(True, alpha=0.3)

        fig.suptitle(title, fontsize=14)
        plt.tight_layout()
        plt.show()
