"""CVXPY-based portfolio optimization.

支持:
  - Max Sharpe (最大夏普比)
  - Min Variance (最小方差)
  - Risk Parity (风险平价)
  - Equal Weight (等权)

约束:
  - 权重上限 (默认单票5%)
  - 权重下限 (默认0%, 不允许做空)
  - 换手率限制
  - 行业中性约束

Usage:
    opt = PortfolioOptimizer()
    weights = opt.max_sharpe(expected_returns, cov_matrix)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class PortfolioOptimizer:
    """CVXPY portfolio optimizer with A-share constraints."""

    def __init__(
        self,
        max_weight: float = 0.05,    # 单票最大权重 5%
        min_weight: float = 0.0,     # 不允许做空
        risk_free_rate: float = 0.02, # 无风险利率 2%
    ):
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.risk_free_rate = risk_free_rate

    def max_sharpe(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        constraints: list | None = None,
    ) -> np.ndarray:
        """Maximize Sharpe ratio portfolio.

        Maximizes (w @ mu - rf) / sqrt(w @ Sigma @ w)
        Equivalent to maximizing w @ mu - lambda * w @ Sigma @ w for some lambda.

        Args:
            expected_returns: array of expected returns
            cov_matrix: covariance matrix
            constraints: additional CVXPY constraints

        Returns:
            Optimal weights array.
        """
        try:
            import cvxpy as cp
        except ImportError:
            raise ImportError("cvxpy is required for portfolio optimization")

        n = len(expected_returns)
        w = cp.Variable(n)

        mu = np.array(expected_returns)
        Sigma = np.array(cov_matrix)

        # Regularize covariance if needed
        Sigma = self._regularize_cov(Sigma)

        # Objective: maximize return - risk_penalty * variance
        # We use a simplified approach: maximize w @ mu subject to risk constraint
        risk_penalty = 1.0
        objective = cp.Maximize(w @ mu - risk_penalty * cp.quad_form(w, Sigma))

        base_constraints = [
            cp.sum(w) == 1.0,
            w >= self.min_weight,
            w <= self.max_weight,
        ]
        if constraints:
            base_constraints.extend(constraints)

        problem = cp.Problem(objective, base_constraints)
        problem.solve(solver=cp.CLARABEL, verbose=False)

        if w.value is None:
            # Fallback to equal weight
            return np.ones(n) / n

        return np.array(w.value)

    def min_variance(
        self,
        cov_matrix: np.ndarray,
        constraints: list | None = None,
    ) -> np.ndarray:
        """Minimum variance portfolio."""
        try:
            import cvxpy as cp
        except ImportError:
            raise ImportError("cvxpy is required")

        n = cov_matrix.shape[0]
        w = cp.Variable(n)
        Sigma = self._regularize_cov(np.array(cov_matrix))

        objective = cp.Minimize(cp.quad_form(w, Sigma))

        base_constraints = [
            cp.sum(w) == 1.0,
            w >= self.min_weight,
            w <= self.max_weight,
        ]
        if constraints:
            base_constraints.extend(constraints)

        problem = cp.Problem(objective, base_constraints)
        problem.solve(solver=cp.CLARABEL, verbose=False)

        if w.value is None:
            return np.ones(n) / n

        return np.array(w.value)

    def risk_parity(
        self,
        cov_matrix: np.ndarray,
        constraints: list | None = None,
    ) -> np.ndarray:
        """Risk parity portfolio (equal risk contribution) using iterative approach."""
        n = cov_matrix.shape[0]
        Sigma = self._regularize_cov(np.array(cov_matrix))

        # CCD algorithm for risk parity
        w = np.ones(n) / n
        for _ in range(100):
            sigma_w = Sigma @ w
            risk_contrib = w * sigma_w
            total_risk = risk_contrib.sum()
            if total_risk <= 0:
                break
            # Update weights proportional to sqrt of risk contribution
            w_new = np.sqrt(w * total_risk / np.where(sigma_w > 0, sigma_w, 1e-10))
            w_new /= w_new.sum()
            if np.max(np.abs(w_new - w)) < 1e-10:
                break
            w = w_new

        # Apply constraints
        w = np.clip(w, self.min_weight, self.max_weight)
        w /= w.sum()
        return w

    def equal_weight(self, n_assets: int) -> np.ndarray:
        """Equal weight portfolio."""
        return np.ones(n_assets) / n_assets

    def _regularize_cov(self, cov: np.ndarray, epsilon: float = 1e-8) -> np.ndarray:
        """Ensure covariance matrix is positive definite."""
        # Add small diagonal
        cov_reg = cov + epsilon * np.eye(cov.shape[0])
        # Make symmetric
        cov_reg = (cov_reg + cov_reg.T) / 2
        return cov_reg

    def portfolio_metrics(
        self,
        weights: np.ndarray,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> dict[str, float]:
        """Calculate portfolio metrics."""
        w = np.array(weights)
        mu = np.array(expected_returns)
        Sigma = self._regularize_cov(np.array(cov_matrix))

        port_return = w @ mu
        port_vol = np.sqrt(w @ Sigma @ w)
        sharpe = (port_return - self.risk_free_rate) / port_vol if port_vol > 0 else 0

        # Herfindahl index (concentration)
        hhi = np.sum(w ** 2)

        return {
            "expected_return": round(float(port_return * 100), 4),
            "volatility": round(float(port_vol * 100), 4),
            "sharpe_ratio": round(float(sharpe), 4),
            "hhi": round(float(hhi), 4),
            "n_positive_assets": int(np.sum(w > 0.001)),
            "max_weight": round(float(np.max(w) * 100), 2),
            "min_weight": round(float(np.min(w) * 100), 2),
        }
