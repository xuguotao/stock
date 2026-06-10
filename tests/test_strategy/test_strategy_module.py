"""Tests for the strategy module: factors, broker, backtest, order."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.core.types import Side
from src.strategy.base import Factor, CompositeFactor
from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor, MACrossSignal
from src.strategy.factors.mean_reversion import MeanReversionFactor
from src.strategy.factors.value import ValueFactor
from src.strategy.execution.order import Order, OrderResult
from src.strategy.execution.broker import SimulatedBroker
from src.core.broker_base import BrokerPosition as Position, BrokerTrade as Trade
from src.strategy.engine.backtest import BacktestEngine, BacktestResult


# ── Helpers ───────────────────────────────────────────────────

def _sample_bars() -> pd.DataFrame:
    """Create sample bars with 5 symbols, 30 trading days."""
    symbols = ["000001.SZ", "600519.SH", "300750.SZ", "000858.SZ", "601318.SH"]
    dates = pd.bdate_range("2025-01-01", periods=30)
    rows = []

    for si, symbol in enumerate(symbols):
        price = 10 + si * 5
        for di, d in enumerate(dates):
            price *= 1 + 0.001 * (si + 1) + 0.0002 * di
            rows.append({
                "date": d, "symbol": symbol,
                "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price,
                "volume": 1_000_000,
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })

    return pd.DataFrame(rows).set_index(["date", "symbol"])


# ── Factors ───────────────────────────────────────────────────

class TestMomentumFactor:
    def test_compute_momentum(self) -> None:
        bars = _sample_bars()
        factor = MomentumFactor(window=5)
        result = factor.compute(bars)

        assert result.columns.tolist() == ["momentum"]
        assert result.index.names == ["date", "symbol"]
        # Should have NaN for first window days
        assert result["momentum"].isna().any()

    def test_momentum_positive_for_rising_prices(self) -> None:
        # Create a single symbol with steadily rising prices
        dates = pd.bdate_range("2025-01-01", periods=30)
        rows = []
        for di, d in enumerate(dates):
            price = 100 * (1 + 0.001 * di)
            rows.append({
                "date": d, "symbol": "000001.SZ",
                "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price,
                "volume": 1_000_000,
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })
        bars = pd.DataFrame(rows).set_index(["date", "symbol"])

        factor = MomentumFactor(window=5)
        result = factor.compute(bars)

        # After window, momentum should be positive
        valid = result["momentum"].dropna()
        assert (valid > 0).all()

    def test_momentum_negative_for_falling_prices(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=30)
        rows = []
        for di, d in enumerate(dates):
            price = 100 * (1 - 0.001 * di)
            rows.append({
                "date": d, "symbol": "000001.SZ",
                "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price,
                "volume": 1_000_000,
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })
        bars = pd.DataFrame(rows).set_index(["date", "symbol"])

        factor = MomentumFactor(window=5)
        result = factor.compute(bars)

        valid = result["momentum"].dropna()
        assert (valid < 0).all()


class TestTrendFactor:
    def test_compute_trend(self) -> None:
        bars = _sample_bars()
        factor = TrendFactor(short_window=5, long_window=10)
        result = factor.compute(bars)

        assert result.columns.tolist() == ["trend"]
        assert result.index.names == ["date", "symbol"]
        # For steadily rising prices, later values should be positive
        valid = result["trend"].dropna()
        # Most values should be >= 0 for rising prices
        assert (valid >= 0).mean() > 0.5  # majority positive

    def test_trend_near_zero_for_flat_prices(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=30)
        rows = []
        for di, d in enumerate(dates):
            price = 100.0
            rows.append({
                "date": d, "symbol": "000001.SZ",
                "open": price, "high": price,
                "low": price, "close": price,
                "volume": 1_000_000,
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })
        bars = pd.DataFrame(rows).set_index(["date", "symbol"])

        factor = TrendFactor(short_window=5, long_window=10)
        result = factor.compute(bars)

        # Flat prices: factor should be near zero
        valid = result["trend"].dropna()
        assert abs(valid.mean()) < 1e-10


class TestMACrossSignal:
    def test_binary_signal(self) -> None:
        bars = _sample_bars()
        factor = MACrossSignal(short_window=5, long_window=10)
        result = factor.compute(bars)

        # Values should be either +1 or -1
        valid = result["ma_cross"].dropna()
        assert valid.isin([1.0, -1.0]).all()


class TestMeanReversionFactor:
    def test_compute_mean_reversion(self) -> None:
        bars = _sample_bars()
        factor = MeanReversionFactor(window=20)
        result = factor.compute(bars)

        assert result.columns.tolist() == ["mean_reversion"]
        assert result.index.names == ["date", "symbol"]

    def test_positive_when_below_mean(self) -> None:
        # Price with variance: starts at 100, oscillates, then drops
        dates = pd.bdate_range("2025-01-01", periods=30)
        rows = []
        for di, d in enumerate(dates):
            # Oscillating then drop
            if di < 25:
                price = 100 + 5 * np.sin(di * 0.5)  # varies around 100
            else:
                price = 80  # drops below mean
            rows.append({
                "date": d, "symbol": "000001.SZ",
                "open": price, "high": price + 1,
                "low": price - 1, "close": price,
                "volume": 1_000_000,
                "amount": price * 1_000_000,
                "adjusted_close": price,
            })
        bars = pd.DataFrame(rows).set_index(["date", "symbol"])

        factor = MeanReversionFactor(window=20)
        result = factor.compute(bars)

        # After the drop, factor should be positive (expecting reversion up)
        last_date = result.loc[dates[-1]]
        assert last_date["mean_reversion"].iloc[0] > 0


class TestValueFactor:
    def test_fallback_with_price(self) -> None:
        bars = _sample_bars()
        factor = ValueFactor()
        result = factor.compute(bars)

        assert result.columns.tolist() == ["value"]
        # 1/price, all positive
        assert (result["value"] >= 0).all()

    def test_with_fundamentals(self) -> None:
        bars = _sample_bars()
        dates = pd.bdate_range("2025-01-01", periods=30)
        symbols = ["000001.SZ", "600519.SH"]
        idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])

        fundamentals = pd.DataFrame({
            "pe_ratio": [10.0, 20.0] * len(dates),
        }, index=idx)

        factor = ValueFactor()
        result = factor.compute(bars, fundamentals=fundamentals)

        # Lower PE = higher value factor
        assert result.columns.tolist() == ["value"]


class TestCompositeFactor:
    def test_weighted_combination(self) -> None:
        bars = _sample_bars()
        momentum = MomentumFactor(window=5)
        trend = TrendFactor(short_window=3, long_window=10)

        composite = CompositeFactor([
            (momentum, 0.6),
            (trend, 0.4),
        ])
        result = composite.compute(bars)

        assert not result.empty
        # Composite should be rank-normalized, so values in [0, 1] range
        valid = result.dropna()
        if not valid.empty:
            assert (valid >= 0).all().all()

    def test_normalizes_weights(self) -> None:
        momentum = MomentumFactor(window=5)
        trend = TrendFactor(short_window=3, long_window=10)

        # Weights sum to > 1, should be normalized
        composite = CompositeFactor([
            (momentum, 3.0),
            (trend, 2.0),
        ])
        assert abs(composite.factors[0][1] - 0.6) < 1e-10
        assert abs(composite.factors[1][1] - 0.4) < 1e-10

    def test_empty_factors_returns_empty(self) -> None:
        composite = CompositeFactor([])
        result = composite.compute(pd.DataFrame())
        assert result.empty


# ── Order & OrderResult ───────────────────────────────────────

class TestOrder:
    def test_is_buy(self) -> None:
        order = Order(symbol="000001.SZ", side=Side.BUY, quantity=100)
        assert order.is_buy
        assert not order.is_sell

    def test_is_sell(self) -> None:
        order = Order(symbol="000001.SZ", side=Side.SELL, quantity=100)
        assert order.is_sell
        assert not order.is_buy

    def test_limit_order(self) -> None:
        order = Order(
            symbol="000001.SZ", side=Side.BUY, quantity=100,
            order_type="limit", limit_price=10.0,
        )
        assert order.limit_price == 10.0


class TestOrderResult:
    def test_filled(self) -> None:
        order = Order(symbol="000001.SZ", side=Side.BUY, quantity=100)
        result = OrderResult(
            order=order, status="filled",
            filled_quantity=100, filled_price=10.0,
        )
        assert result.is_filled
        assert not result.is_rejected
        assert result.filled_amount == 1000.0

    def test_rejected(self) -> None:
        order = Order(symbol="000001.SZ", side=Side.BUY, quantity=100)
        result = OrderResult(
            order=order, status="rejected",
            reject_reason="Insufficient cash",
        )
        assert result.is_rejected
        assert not result.is_filled


# ── Broker ────────────────────────────────────────────────────

class TestBroker:
    def test_buy_reduces_cash(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        result = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )

        assert result.is_filled
        assert broker.cash < 100_000

    def test_buy_lot_size_enforced(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        result = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=150),
            date(2025, 6, 3), current_price=10.0,
        )

        assert result.is_filled
        assert result.filled_quantity == 100  # rounded down to 100

    def test_t_plus_one_sell_rejected(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        buy_day = date(2025, 6, 3)

        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            buy_day, current_price=10.0,
        )

        same_day_sell = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.SELL, quantity=100),
            buy_day, current_price=10.1,
        )
        assert same_day_sell.is_rejected
        assert "T+1" in same_day_sell.reject_reason

    def test_next_day_sell_succeeds(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        buy_day = date(2025, 6, 3)
        sell_day = date(2025, 6, 4)

        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            buy_day, current_price=10.0,
        )

        broker.update_available_positions(sell_day)
        next_day_sell = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.SELL, quantity=100),
            sell_day, current_price=10.1,
        )
        assert next_day_sell.is_filled

    def test_insufficient_cash_rejected(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=1_000)
        result = broker.submit_order(
            Order(symbol="600519.SH", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=1500.0,  # 150k yuan
        )

        assert result.is_rejected
        assert "cash" in result.reject_reason.lower()

    def test_invalid_price_rejected(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        result = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=-10.0,
        )

        assert result.is_rejected

    def test_sell_without_position_rejected(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        result = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.SELL, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )

        assert result.is_rejected

    def test_price_limit_check(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        # 600519 is on main board: 10% limit
        # prev_close=10, limit=10%, upper=11, lower=9
        result = broker.submit_order(
            Order(symbol="600519.SH", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=12.0, prev_close=10.0,
        )

        assert result.is_rejected
        assert "price limit" in result.reject_reason.lower()

    def test_commission_calculation(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        buy_result = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )

        # Commission + transfer + management fees
        assert buy_result.commission > 0

        # Sell should have additional stamp duty
        broker.update_available_positions(date(2025, 6, 4))
        sell_result = broker.submit_order(
            Order(symbol="000001.SZ", side=Side.SELL, quantity=100),
            date(2025, 6, 4), current_price=10.0,
        )

        assert sell_result.commission > buy_result.commission

    def test_portfolio_value(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )

        # If price goes to 11, value = cash + 100*11
        value = broker.portfolio_value({"000001.SZ": 11.0})
        assert value > 100_000

    def test_summary(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )

        summary = broker.summary()
        assert summary["initial_capital"] == 100_000
        assert summary["total_trades"] == 1
        assert summary["buys"] == 1
        assert summary["sells"] == 0

    def test_position_update(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )

        pos = broker.positions["000001.SZ"]
        assert pos.quantity == 100
        assert pos.avg_cost == 10.0
        assert pos.available == 0  # T+1: not available yet

    def test_multiple_buys_average_cost(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        broker = SimulatedBroker(initial_capital=100_000)
        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=10.0,
        )
        broker.submit_order(
            Order(symbol="000001.SZ", side=Side.BUY, quantity=100),
            date(2025, 6, 3), current_price=12.0,
        )

        pos = broker.positions["000001.SZ"]
        assert pos.quantity == 200
        assert abs(pos.avg_cost - 11.0) < 0.01  # (10*100 + 12*100) / 200


# ── Backtest Engine ───────────────────────────────────────────

class TestBacktestEngine:
    def test_run_basic_backtest(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        bars = _sample_bars()
        engine = BacktestEngine(
            bars=bars,
            factors=[MomentumFactor(window=5)],
            top_n=2,
            rebalance_days=1,
            initial_capital=100_000,
        )

        result = engine.run()

        assert result.initial_capital == 100_000
        assert result.final_value > 0
        assert len(result.daily_returns) > 0
        assert len(result.trades) >= 0

    def test_min_score_blocks_weak_signals(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        class ConstantFactor(Factor):
            name = "constant"

            def compute(self, bars: pd.DataFrame, **kwargs):
                return pd.DataFrame({"constant": 0.0}, index=bars.index)

        bars = _sample_bars()
        engine = BacktestEngine(
            bars=bars,
            factors=[ConstantFactor()],
            top_n=2,
            rebalance_days=1,
            initial_capital=100_000,
            min_score=0.1,
        )

        result = engine.run()

        assert len(result.trades) == 0

    def test_backtest_metrics(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        bars = _sample_bars()
        engine = BacktestEngine(
            bars=bars,
            factors=[MomentumFactor(window=5)],
            top_n=2,
            rebalance_days=1,
            initial_capital=100_000,
        )

        result = engine.run()
        metrics = result.metrics

        assert "total_return" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics
        assert "win_rate" in metrics
        assert metrics["trading_days"] > 0
        assert metrics["final_value"] > 0

    def test_backtest_with_multiple_factors(self) -> None:
        from config.settings import reset_settings
        reset_settings()

        bars = _sample_bars()
        engine = BacktestEngine(
            bars=bars,
            factors=[
                MomentumFactor(window=5),
                TrendFactor(short_window=3, long_window=10),
            ],
            factor_weights=[0.5, 0.5],
            top_n=3,
            rebalance_days=2,
            initial_capital=100_000,
        )

        result = engine.run()
        assert result.final_value > 0
        assert len(result.daily_returns) > 0

    def test_no_factors_raises_error(self) -> None:
        """BacktestEngine currently raises ZeroDivisionError with empty factors."""
        from config.settings import reset_settings
        reset_settings()

        bars = _sample_bars()
        with pytest.raises(ZeroDivisionError):
            BacktestEngine(
                bars=bars,
                factors=[],
                top_n=2,
                rebalance_days=1,
                initial_capital=100_000,
            )


# ── Research Module Tests ─────────────────────────────────────

class TestFactorNeutralizer:
    def test_neutralize_preserves_shape(self) -> None:
        from src.research.factor_analysis.neutralization import FactorNeutralizer

        dates = pd.bdate_range("2025-01-01", periods=4)
        symbols = ["000001.SZ", "600036.SH", "600519.SH", "000858.SZ"]
        idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
        factor = pd.DataFrame({"momentum": np.arange(len(idx), dtype=float)}, index=idx)
        industry = pd.Series(
            ["bank", "bank", "consumer", "consumer"] * len(dates),
            index=idx,
        )
        market_cap = pd.Series(np.linspace(100, 200, len(idx)), index=idx)

        neutral = FactorNeutralizer().neutralize(
            factor, industry_codes=industry, market_cap=market_cap,
        )

        assert neutral.index.equals(factor.index)
        assert neutral.columns.tolist() == ["momentum"]
        assert neutral["momentum"].notna().all()
        # Mean should be ~0 for each cross-section
        assert abs(float(neutral.groupby(level=0)["momentum"].mean().max())) < 1e-8

    def test_neutralize_empty_returns_empty(self) -> None:
        from src.research.factor_analysis.neutralization import FactorNeutralizer

        result = FactorNeutralizer().neutralize(pd.DataFrame())
        assert result.empty


class TestICAnalyzer:
    def test_ic_summary(self) -> None:
        from src.research.factor_analysis.ic_analysis import ICAnalyzer

        ic = pd.Series([0.05, 0.03, -0.01, 0.04, 0.02], name="ic")
        rank_ic = pd.Series([0.06, 0.04, 0.0, 0.05, 0.03], name="rank_ic")

        summary = ICAnalyzer().ic_summary(ic, rank_ic)
        assert summary.ic_mean > 0
        assert summary.icir > 0
        assert summary.ic_positive_ratio == 0.8  # 4 out of 5 positive
        assert summary.rank_ic_mean > 0

    def test_compute_forward_returns(self) -> None:
        from src.research.factor_analysis.ic_analysis import ICAnalyzer

        prices = pd.DataFrame({
            "A": [100, 101, 102, 103, 104],
            "B": [50, 51, 52, 50, 51],
        }, index=pd.bdate_range("2025-01-01", periods=5))

        analyzer = ICAnalyzer(forward_period=1)
        fwd = analyzer.compute_forward_returns(prices)

        assert isinstance(fwd, pd.DataFrame)
        assert len(fwd) > 0

    def test_ic_with_synthetic_data(self) -> None:
        from src.research.factor_analysis.ic_analysis import ICAnalyzer

        dates = pd.bdate_range("2025-01-01", periods=20)
        symbols = ["A", "B", "C", "D", "E"]
        idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])

        # Factor: random
        np.random.seed(42)
        factor = pd.DataFrame({"f": np.random.randn(len(idx))}, index=idx)
        # Returns: positively correlated with factor
        returns = pd.DataFrame({"return": factor["f"] * 0.01 + np.random.randn(len(idx)) * 0.001}, index=idx)

        analyzer = ICAnalyzer(forward_period=1)
        ic = analyzer.compute_ic(factor, returns)

        # With positive correlation, IC should be mostly positive
        assert ic.mean() > 0


class TestQuantileAnalyzer:
    def test_quantile_analysis(self) -> None:
        from src.research.factor_analysis.quantile import QuantileAnalyzer, QuantileResult

        dates = pd.bdate_range("2025-01-01", periods=20)
        symbols = [f"S{i}" for i in range(10)]
        idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])

        np.random.seed(42)
        factor = pd.DataFrame({"f": np.random.randn(len(idx))}, index=idx)
        returns = pd.DataFrame({
            "return": factor["f"] * 0.01 + np.random.randn(len(idx)) * 0.001
        }, index=idx)

        analyzer = QuantileAnalyzer(n_quantiles=5)
        result = analyzer.analyze(factor, returns)

        assert isinstance(result, QuantileResult)
        assert result.spread is not None
        assert result.monotonicity is not None

    def test_empty_input(self) -> None:
        from src.research.factor_analysis.quantile import QuantileAnalyzer

        analyzer = QuantileAnalyzer(n_quantiles=5)
        result = analyzer.analyze(pd.DataFrame(), pd.DataFrame())

        assert result.quantile_returns.empty
        assert result.spread == 0.0
        assert result.monotonicity == 0.0
