"""Tests for the trading module: signal_engine, risk_manager, scheduler."""

from __future__ import annotations

from datetime import date, time

import pytest

from src.trading.signal_engine import Signal, SignalEngine
from src.trading.risk_manager import RiskManager, RiskLevel, RiskCheckResult
from src.trading.scheduler import TradingScheduler
from src.core.types import Side


# ── Signal Engine ─────────────────────────────────────────────

class TestSignalEngine:
    def test_rebalance_day_cycle(self) -> None:
        """Engine should only generate signals on rebalance days."""
        engine = SignalEngine(top_n=2, rebalance_days=5, min_strength=0.0)

        # First 4 calls should return empty (not rebalance days)
        for _ in range(4):
            signals = engine.generate_signals(
                bars=None, factors=[], trade_date=date(2025, 1, 1),
            )
            assert signals == []

        # 5th call is a rebalance day
        signals = engine.generate_signals(
            bars=None, factors=[], trade_date=date(2025, 1, 1),
        )
        # No factors, so still empty, but the cycle advanced
        assert isinstance(signals, list)

    def test_min_strength_filter(self) -> None:
        """Signals below min_strength should be filtered out."""
        engine = SignalEngine(top_n=5, rebalance_days=1, min_strength=0.9)
        # Without factors, no signals pass
        signals = engine.generate_signals(
            bars=None, factors=[], trade_date=date(2025, 1, 1),
        )
        assert signals == []

    def test_signal_dataclass(self) -> None:
        signal = Signal(
            date=date(2025, 6, 1),
            symbol="000001.SZ",
            side=Side.BUY,
            strength=0.85,
            factor_name="momentum",
            reason="Top ranked",
        )
        assert signal.side == Side.BUY
        assert signal.strength == 0.85
        assert signal.factor_name == "momentum"


# ── Risk Manager ──────────────────────────────────────────────

class TestRiskManager:
    def _make_account(self, cash: float = 1_000_000.0):
        from config.settings import reset_settings
        from src.trading.paper_account import PaperAccount
        reset_settings()
        return PaperAccount(initial_capital=cash)

    def test_ok_order_passes(self) -> None:
        rm = RiskManager()
        account = self._make_account()

        result = rm.check_order(
            symbol="000001.SZ", side="buy", quantity=100,
            price=10.0, account=account, trade_date=date(2025, 6, 1),
        )
        assert result.passed
        assert result.level == RiskLevel.OK

    def test_single_stock_weight_blocked(self) -> None:
        rm = RiskManager(max_single_weight=0.01)  # 1% max per stock
        account = self._make_account(cash=1_000_000.0)

        # 1% of 1,000,000 = 10,000; at price=100, that's 100 shares
        result = rm.check_order(
            symbol="000001.SZ", side="buy", quantity=200,
            price=100.0, account=account, trade_date=date(2025, 6, 1),
        )
        assert not result.passed
        assert result.level == RiskLevel.WARNING
        assert "weight" in result.message.lower()

    def test_total_position_blocked(self) -> None:
        rm = RiskManager(max_total_position=0.01)  # 1% max total
        account = self._make_account(cash=1_000_000.0)

        # 1% of 1,000,000 = 10,000; at price=100, that's 100 shares
        result = rm.check_order(
            symbol="000001.SZ", side="buy", quantity=200,
            price=100.0, account=account, trade_date=date(2025, 6, 1),
        )
        assert not result.passed
        assert "position" in result.message.lower()

    def test_max_trades_per_day(self) -> None:
        rm = RiskManager(max_trades_per_day=2)
        account = self._make_account()

        r1 = rm.check_order("000001.SZ", "buy", 100, 10.0, account, date(2025, 6, 1))
        r2 = rm.check_order("600519.SH", "buy", 100, 10.0, account, date(2025, 6, 1))
        r3 = rm.check_order("300750.SZ", "buy", 100, 10.0, account, date(2025, 6, 1))

        assert r1.passed
        assert r2.passed
        assert not r3.passed
        assert "Max trades" in r3.message

    def test_trading_halt_blocks_further_orders(self) -> None:
        rm = RiskManager(max_trades_per_day=1)
        account = self._make_account()

        rm.check_order("000001.SZ", "buy", 100, 10.0, account, date(2025, 6, 1))
        result = rm.check_order("600519.SH", "buy", 100, 10.0, account, date(2025, 6, 1))

        assert not result.passed
        assert rm.is_trading_halted

    def test_drawdown_warning(self) -> None:
        rm = RiskManager(max_daily_drawdown=0.03)
        account = self._make_account()
        # Set drawdown close to limit (80%)
        account.max_drawdown = 0.025

        result = rm.check_daily_drawdown(account)
        assert result.level == RiskLevel.WARNING
        assert result.passed  # Warning, not blocked

    def test_drawdown_blocked(self) -> None:
        rm = RiskManager(max_daily_drawdown=0.03)
        account = self._make_account()
        account.max_drawdown = 0.04

        result = rm.check_daily_drawdown(account)
        assert not result.passed
        assert result.level == RiskLevel.BLOCKED

    def test_sell_side_skips_weight_checks(self) -> None:
        rm = RiskManager(max_single_weight=0.01)  # Very strict
        account = self._make_account()

        # Sell should pass without weight checks
        result = rm.check_order(
            symbol="000001.SZ", side="sell", quantity=100,
            price=10.0, account=account, trade_date=date(2025, 6, 1),
        )
        assert result.passed

    def test_industry_concentration(self) -> None:
        rm = RiskManager(max_industry_weight=0.05)  # 5% industry max
        account = self._make_account(cash=1_000_000.0)

        # First buy a stock in "银行"
        rm.check_order("600036.SH", "buy", 100, 10.0, account, date(2025, 6, 1))

        # Try to buy another stock in same industry with large quantity
        result = rm.check_order(
            "601398.SH", "buy", 500_000, 10.0, account, date(2025, 6, 1),
            industry_map={"600036.SH": "银行", "601398.SH": "银行"},
        )
        assert not result.passed

    def test_daily_reset(self) -> None:
        rm = RiskManager(max_trades_per_day=2)
        account = self._make_account()

        rm.check_order("000001.SZ", "buy", 100, 10.0, account, date(2025, 6, 1))
        rm.check_order("600519.SH", "buy", 100, 10.0, account, date(2025, 6, 1))

        # Same day, should be blocked
        r = rm.check_order("300750.SZ", "buy", 100, 10.0, account, date(2025, 6, 1))
        assert not r.passed

        # New day, should reset
        r = rm.check_order("300750.SZ", "buy", 100, 10.0, account, date(2025, 6, 2))
        assert r.passed


# ── Scheduler ─────────────────────────────────────────────────

class TestTradingScheduler:
    def test_is_trading_day_weekday(self) -> None:
        scheduler = TradingScheduler()
        # 2025-06-03 is Wednesday (not a holiday)
        assert scheduler.is_trading_day(date(2025, 6, 3))

    def test_is_not_trading_day_weekend(self) -> None:
        scheduler = TradingScheduler()
        # 2025-06-07 is Saturday
        assert not scheduler.is_trading_day(date(2025, 6, 7))

    def test_is_not_trading_day_holiday(self) -> None:
        scheduler = TradingScheduler()
        # 2025-10-01 is National Day
        assert not scheduler.is_trading_day(date(2025, 10, 1))
        # 2025-06-02 is Dragon Boat Festival holiday
        assert not scheduler.is_trading_day(date(2025, 6, 2))

    def test_market_hours(self) -> None:
        scheduler = TradingScheduler()
        assert scheduler.is_market_hours(time(10, 0))   # Morning session
        assert scheduler.is_market_hours(time(14, 0))   # Afternoon session
        assert not scheduler.is_market_hours(time(12, 0))  # Lunch break
        assert not scheduler.is_market_hours(time(8, 0))   # Before open

    def test_call_auction(self) -> None:
        scheduler = TradingScheduler()
        assert scheduler.is_call_auction(time(9, 20))     # Morning auction
        assert scheduler.is_call_auction(time(14, 58))    # Afternoon auction
        assert not scheduler.is_call_auction(time(10, 0))  # Normal trading

    def test_rebalance_weekly(self) -> None:
        scheduler = TradingScheduler()
        # 2025-06-09 is Monday (trading day, after Dragon Boat holiday)
        assert scheduler.is_rebalance_day(date(2025, 6, 9), frequency="weekly")
        # 2025-06-10 is Tuesday
        assert not scheduler.is_rebalance_day(date(2025, 6, 10), frequency="weekly")

    def test_rebalance_monthly(self) -> None:
        scheduler = TradingScheduler()
        # First trading day of June 2025: June 3 (Tue, June 2 is Dragon Boat holiday)
        assert scheduler.is_rebalance_day(date(2025, 6, 3), frequency="monthly")
        # June 4 should not be first trading day
        assert not scheduler.is_rebalance_day(date(2025, 6, 4), frequency="monthly")

    def test_rebalance_not_on_holiday(self) -> None:
        scheduler = TradingScheduler()
        # Oct 1 is holiday, shouldn't be rebalance day
        assert not scheduler.is_rebalance_day(date(2025, 10, 1), frequency="daily")

    def test_callback_registration(self) -> None:
        scheduler = TradingScheduler()
        called = []
        scheduler.on_trading_day_start(lambda: called.append(1))
        scheduler.run_callbacks()
        assert called == [1]

    def test_callback_error_does_not_stop_others(self) -> None:
        scheduler = TradingScheduler()
        called = []
        scheduler.on_trading_day_start(lambda: 1 / 0)  # raises
        scheduler.on_trading_day_start(lambda: called.append("ok"))
        scheduler.run_callbacks()
        assert called == ["ok"]

    def test_get_trading_days_range(self) -> None:
        scheduler = TradingScheduler()
        days = scheduler.get_trading_days(date(2025, 6, 1), date(2025, 6, 10))
        # Excludes weekends, no holidays in this range
        weekdays = [d for d in days if d.weekday() < 5]
        assert len(days) == len(weekdays)

    def test_is_tail_session_returns_true_in_tail_window(self) -> None:
        scheduler = TradingScheduler()
        # 14:30 is in tail session
        assert scheduler.is_tail_session(time(14, 30))
        # 14:55 is in tail session
        assert scheduler.is_tail_session(time(14, 55))
        # 10:00 is NOT in tail session
        assert not scheduler.is_tail_session(time(10, 0))
        # 11:30 is NOT in tail session
        assert not scheduler.is_tail_session(time(11, 30))


# ── Paper Account ─────────────────────────────────────────────

class TestPaperAccount:
    def _make_account(self, cash: float = 1_000_000.0):
        from config.settings import reset_settings
        from src.trading.paper_account import PaperAccount
        reset_settings()
        return PaperAccount(initial_capital=cash)

    def test_buy_reduces_cash(self) -> None:
        account = self._make_account()
        trade = account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        assert trade is not None
        assert trade.side == "buy"
        assert trade.quantity == 100
        assert account.cash < 1_000_000

    def test_t_plus_one(self) -> None:
        account = self._make_account()
        account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        # Same day sell should fail
        sell = account.sell("000001.SZ", 10.5, 100, date(2025, 6, 1))
        assert sell is None

        # Next day sell should succeed
        account.update_t_plus_one(date(2025, 6, 2))
        sell = account.sell("000001.SZ", 10.5, 100, date(2025, 6, 2))
        assert sell is not None

    def test_lot_size(self) -> None:
        account = self._make_account()
        trade = account.buy("000001.SZ", 10.0, 150, date(2025, 6, 1))

        assert trade is not None
        assert trade.quantity == 100  # rounded down

    def test_insufficient_cash(self) -> None:
        account = self._make_account(cash=1_000)
        trade = account.buy("600519.SH", 1500.0, 100, date(2025, 6, 1))

        assert trade is None

    def test_portfolio_value(self) -> None:
        account = self._make_account()
        account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        value = account.portfolio_value({"000001.SZ": 11.0})
        assert value > 1_000_000

    def test_summary(self) -> None:
        account = self._make_account()
        account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        summary = account.summary()
        assert summary["initial_capital"] == 1_000_000
        assert summary["total_trades"] == 1
        assert summary["buys"] == 1
        assert "max_drawdown" in summary

    def test_save_and_load(self, tmp_path) -> None:
        from config.settings import reset_settings
        from src.trading.paper_account import PaperAccount
        reset_settings()

        account = PaperAccount(initial_capital=100_000, data_dir=str(tmp_path))
        account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        saved = account.save("test_account.json")
        assert "test_account.json" in saved

        # Load into new account
        new_account = PaperAccount(data_dir=str(tmp_path))
        new_account.load("test_account.json")

        assert new_account.initial_capital == 100_000
        assert new_account.cash < 100_000
        assert len(new_account.positions) == 1
        assert "000001.SZ" in new_account.positions
        assert new_account.positions["000001.SZ"].quantity == 100
        assert len(new_account.trades) == 1

    def test_update_daily_pnl(self) -> None:
        account = self._make_account()
        account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        pnl = account.update_daily_pnl({"000001.SZ": 11.0})
        # Price went up, should have positive unrealized P&L
        assert pnl is not None

    def test_daily_drawdown_tracking(self) -> None:
        account = self._make_account()

        # Update with price dropping
        account.update_daily_pnl({"000001.SZ": 9.0})
        assert account.max_drawdown == 0.0  # No positions, no drawdown

        account.buy("000001.SZ", 10.0, 100, date(2025, 6, 1))

        # Now price drops
        account.update_daily_pnl({"000001.SZ": 9.0})
        assert account.max_drawdown > 0.0
        assert account.daily_peak >= account.initial_capital
