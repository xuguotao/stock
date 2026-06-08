"""因子中性化.

通过截面回归去除行业暴露和市值暴露，得到"纯净"因子。
factor_neutral = factor - beta_industry - beta_mcap

Usage:
    neutralizer = FactorNeutralizer()
    neutral = neutralizer.neutralize(factor_values, industry, market_cap)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class FactorNeutralizer:
    """Cross-sectional factor neutralization."""

    def neutralize(
        self,
        factor_values: pd.DataFrame,
        industry_codes: pd.Series | None = None,
        market_cap: pd.Series | None = None,
    ) -> pd.DataFrame:
        """Neutralize factors against industry and market cap.

        Args:
            factor_values: MultiIndex (date, symbol), factor values
            industry_codes: MultiIndex (date, symbol), industry codes (e.g., "银行", "电子")
            market_cap: MultiIndex (date, symbol), market capitalization

        Returns:
            Neutralized factor values, same shape as input.
        """
        if factor_values.empty:
            return factor_values.copy()

        frames = []
        date_level = factor_values.index.names[0] or "date"
        symbol_level = factor_values.index.names[1] or "symbol"

        for d, group in factor_values.groupby(level=0, sort=False):
            cross_section = group.droplevel(0)
            industry = self._loc_date(industry_codes, d) if industry_codes is not None else None
            mcap = self._loc_date(market_cap, d) if market_cap is not None else None

            columns = {}
            for col in cross_section.columns:
                columns[col] = self._neutralize_single(
                    cross_section[col],
                    industry,
                    mcap,
                )

            frame = pd.DataFrame(columns, index=cross_section.index)
            frame.index = pd.MultiIndex.from_product(
                [[d], frame.index],
                names=[date_level, symbol_level],
            )
            frames.append(frame)

        if not frames:
            return factor_values.copy()

        result = pd.concat(frames).reindex(factor_values.index)
        return result[factor_values.columns]

    def _loc_date(self, values: pd.Series, d) -> pd.Series:
        """Return one date's cross-section, accepting date/Timestamp variants."""
        try:
            return values.loc[d]
        except KeyError:
            ts = pd.Timestamp(d)
            try:
                return values.loc[ts]
            except KeyError:
                return pd.Series(dtype=object)

    def _neutralize_single(
        self,
        factor: pd.Series,
        industry: pd.Series | None,
        mcap: pd.Series | None,
    ) -> pd.Series:
        """Neutralize a single cross-section."""
        y = factor.copy()

        # Build design matrix
        X_data = []
        valid_mask = y.notna()

        if industry is not None:
            valid_mask &= industry.notna()
            dummies = pd.get_dummies(industry[valid_mask], drop_first=True)
            X_data.append(dummies)

        if mcap is not None:
            valid_mask &= mcap.notna()
            log_mcap = np.log(mcap[valid_mask].replace(0, np.nan))
            X_data.append(pd.DataFrame({"log_mcap": log_mcap}, index=log_mcap.index))

        if not X_data or valid_mask.sum() < 3:
            return y

        X = pd.concat(X_data, axis=1)
        X.insert(0, "intercept", 1.0)
        X = X.fillna(0)
        y_valid = y[valid_mask]

        # Align
        common_idx = X.index.intersection(y_valid.index)
        if len(common_idx) < 3:
            return y

        X_aligned = X.loc[common_idx].astype(float).values
        y_aligned = y_valid.loc[common_idx].values.astype(float)

        # OLS: y = X @ beta + residual
        try:
            from numpy.linalg import lstsq
            beta, residuals, rank, sv = lstsq(X_aligned, y_aligned, rcond=None)
            fitted = X_aligned @ beta
            residual = pd.Series(y_aligned - fitted, index=common_idx)
            y[common_idx] = residual
        except Exception:
            pass

        return y
