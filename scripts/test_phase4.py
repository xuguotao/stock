#!/usr/bin/env python3
"""Test Phase 4: Paper Trading System."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from src.trading.paper_account import PaperAccount, PaperPosition, PaperTrade
from src.trading.risk_manager import RiskManager, RiskLevel
from src.trading.signal_engine import SignalEngine, Signal
from src.trading.scheduler import TradingScheduler
from src.core.types import Side
from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor
from src.data.aggregator import DataAggregator


def test_paper_account():
    """Test PaperAccount CRUD."""
    print("=" * 60)
    print("Phase 4 Test: PaperAccount")
    print("=" * 60)

    account = PaperAccount(initial_capital=1_000_000.0)

    # Buy
    print("\n[1] Buy operations:")
    t1 = account.buy("000001.SZ", 11.00, 100, date(2025, 6, 3))
    assert t1 is not None
    assert t1.side == "buy"
    assert t1.quantity == 100
    print(f"    {t1.trade_id}: BUY 000001.SZ x{t1.quantity} @ {t1.price:.2f}")
    print(f"    Commission: {t1.commission:.2f}")
    print(f"    Cash: {account.cash:.2f}")

    # T+1: can't sell same day
    print("\n[2] T+1 restriction:")
    t2 = account.sell("000001.SZ", 11.10, 100, date(2025, 6, 3))
    assert t2 is None
    print(f"    Same day sell: rejected (correct)")

    # T+1: can sell next day
    print("\n[3] Sell next day (T+1 passed):")
    account.update_t_plus_one(date(2025, 6, 4))
    t3 = account.sell("000001.SZ", 11.10, 100, date(2025, 6, 4))
    assert t3 is not None
    assert t3.side == "sell"
    print(f"    {t3.trade_id}: SELL x{t3.quantity} @ {t3.price:.2f}")
    print(f"    Realized P&L: {t3.realized_pnl:+.2f}")

    # Portfolio value
    print("\n[4] Portfolio value:")
    prices = {"600519.SH": 1500.0, "300750.SZ": 230.0}
    account.buy("600519.SH", 1500.0, 100, date(2025, 6, 4))
    account.buy("300750.SZ", 230.0, 200, date(2025, 6, 4))
    pv = account.portfolio_value(prices)
    print(f"    Cash: {account.cash:.2f}")
    print(f"    Positions: {len(account.positions)}")
    for sym, pos in account.positions.items():
        print(f"      {sym}: {pos.quantity} shares, cost={pos.avg_cost:.2f}")
    print(f"    Total value: {pv:.2f}")

    # Summary
    print("\n[5] Account summary:")
    summary = account.summary()
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # Save and load
    print("\n[6] Save/Load:")
    path = account.save("test_account.json")
    print(f"    Saved to: {path}")

    account2 = PaperAccount()
    account2.load("test_account.json")
    print(f"    Loaded: cash={account2.cash:.2f}, "
          f"positions={len(account2.positions)}, "
          f"trades={len(account2.trade_log)}")
    assert account2.cash == account.cash
    assert len(account2.positions) == len(account.positions)

    print(f"\n  ✅ PaperAccount tests passed")
    return True


def test_risk_manager():
    """Test RiskManager."""
    print("\n" + "=" * 60)
    print("Phase 4 Test: RiskManager")
    print("=" * 60)

    rm = RiskManager(
        max_daily_drawdown=0.03,
        max_single_weight=0.20,
        max_industry_weight=0.60,
        max_total_position=0.95,
    )

    account = PaperAccount(initial_capital=1_000_000.0)
    trade_date = date(2025, 6, 3)

    industry_map = {
        "000001.SZ": "银行", "600036.SH": "银行",
        "300750.SZ": "电气设备", "600519.SH": "食品饮料",
    }

    # 1. Normal buy
    print("\n[1] Normal buy (within limits):")
    result = rm.check_order("000001.SZ", "buy", 100, 11.00, account, trade_date, industry_map)
    print(f"    Result: {result.level.value}, passed={result.passed}")
    assert result.passed

    # 2. Large buy (concentration)
    print("\n[2] Large buy (single stock limit):")
    result = rm.check_order("000001.SZ", "buy", 20000, 11.00, account, trade_date, industry_map)
    print(f"    Result: {result.level.value}")
    print(f"    Message: {result.message[:80]}")

    # 3. Industry concentration
    print("\n[3] Industry concentration (same industry buy):")
    account2 = PaperAccount(initial_capital=1_000_000.0)
    account2.buy("000001.SZ", 11.00, 8000, trade_date)  # ~88k
    result = rm.check_order("600036.SH", "buy", 8000, 11.00, account2, trade_date, industry_map)
    print(f"    Result: {result.level.value}")
    # With 8000 shares each, total ~176k < 600k limit, should pass

    # 4. Max trades per day
    print("\n[4] Max trades per day:")
    rm2 = RiskManager(max_trades_per_day=3)
    for i in range(5):
        result = rm2.check_order("000001.SZ", "buy", 100, 11.00, account, trade_date)
        if i < 3:
            assert result.passed, f"Trade {i+1} should pass"
        else:
            assert not result.passed, f"Trade {i+1} should be blocked"
            print(f"    Trade {i+1}: BLOCKED - {result.message}")

    # 5. Daily drawdown
    print("\n[5] Daily drawdown check:")
    account3 = PaperAccount(initial_capital=1_000_000.0)
    account3.daily_peak = 1_000_000
    account3.max_drawdown = 0.025  # 2.5%, below 3% limit
    result = rm.check_daily_drawdown(account3)
    print(f"    Drawdown 2.5%: {result.level.value}")

    account3.max_drawdown = 0.035  # 3.5%, above limit
    result = rm.check_daily_drawdown(account3)
    print(f"    Drawdown 3.5%: {result.level.value} - {result.message[:60]}")
    assert not result.passed
    assert rm.is_trading_halted

    print(f"\n  ✅ RiskManager tests passed")
    return True


def test_signal_engine():
    """Test SignalEngine."""
    print("\n" + "=" * 60)
    print("Phase 4 Test: SignalEngine")
    print("=" * 60)

    agg = DataAggregator()
    symbols = ["600519.SH", "000001.SZ", "300750.SZ", "000858.SZ", "601318.SH",
               "600036.SH", "000333.SZ", "601888.SH", "002714.SZ", "600900.SH"]
    bars = agg.get_bars_batch(symbols, date(2025, 3, 1), date(2025, 6, 3))
    print(f"  Data: {len(bars)} bars, {bars.index.get_level_values(1).nunique()} symbols")

    engine = SignalEngine(top_n=3, rebalance_days=1, min_strength=0.3)

    factors = [
        MomentumFactor(window=10),
        TrendFactor(short_window=5, long_window=20),
    ]

    signals = engine.generate_signals(bars, factors, date(2025, 6, 3))
    print(f"\n  Signals generated: {len(signals)}")
    for sig in signals:
        side_icon = "BUY" if sig.side == Side.BUY else "SELL"
        print(f"    {side_icon} {sig.symbol}: strength={sig.strength:.3f}, reason={sig.reason}")

    # Check signal balance
    buy_signals = [s for s in signals if s.side == Side.BUY]
    sell_signals = [s for s in signals if s.side == Side.SELL]
    print(f"\n  Buy signals: {len(buy_signals)}, Sell signals: {len(sell_signals)}")
    assert len(buy_signals) <= 3  # top_n=3
    assert len(sell_signals) <= 3

    print(f"\n  ✅ SignalEngine tests passed")
    return True


def test_scheduler():
    """Test TradingScheduler."""
    print("\n" + "=" * 60)
    print("Phase 4 Test: TradingScheduler")
    print("=" * 60)

    scheduler = TradingScheduler()

    # Trading day check
    print("\n[1] Trading day checks:")
    test_dates = [
        (date(2025, 6, 3), True, "regular day"),
        (date(2025, 6, 7), False, "Saturday"),
        (date(2025, 10, 1), False, "National Day"),
        (date(2025, 1, 27), False, "Spring Festival"),
    ]
    for d, expected, desc in test_dates:
        result = scheduler.is_trading_day(d)
        status = "✅" if result == expected else "❌"
        print(f"    {status} {d.isoformat()} ({desc}): {result}")
        assert result == expected

    # Next/prev trading day
    print("\n[2] Trading day navigation:")
    today = date(2025, 6, 3)
    next_day = scheduler.next_trading_day(today)
    prev_day = scheduler.prev_trading_day(today)
    print(f"    Next after {today}: {next_day}")
    print(f"    Prev before {today}: {prev_day}")

    # Rebalance day
    print("\n[3] Rebalance day checks:")
    monday = date(2025, 6, 2)  # Monday
    friday = date(2025, 6, 6)  # Friday
    print(f"    Monday (weekly rebalance): {scheduler.is_rebalance_day(monday, 'weekly')}")
    print(f"    Friday (weekly rebalance): {scheduler.is_rebalance_day(friday, 'weekly')}")

    # Trading days count
    print("\n[4] Trading days in June 2025:")
    days = scheduler.get_trading_days(date(2025, 6, 1), date(2025, 6, 30))
    print(f"    {len(days)} trading days")

    print(f"\n  ✅ Scheduler tests passed")
    return True


def test_full_paper_trading():
    """Integration test: full paper trading flow."""
    print("\n" + "=" * 60)
    print("Phase 4 Test: Full Paper Trading Flow")
    print("=" * 60)

    # Setup
    account = PaperAccount(initial_capital=1_000_000.0)
    rm = RiskManager(max_single_weight=0.30, max_daily_drawdown=0.10)
    scheduler = TradingScheduler()
    signal_engine = SignalEngine(top_n=3, rebalance_days=1, min_strength=0.3)

    # Get data
    agg = DataAggregator()
    symbols = ["600519.SH", "000001.SZ", "300750.SZ", "000858.SZ", "601318.SH"]
    bars = agg.get_bars_batch(symbols, date(2025, 4, 1), date(2025, 6, 3))
    dates = sorted(bars.index.get_level_values(0).unique())

    factors = [
        MomentumFactor(window=5),
        TrendFactor(short_window=3, long_window=10),
    ]

    print(f"  Running paper trading simulation: {len(dates)} days, {len(symbols)} stocks")

    portfolio_history = []
    for d in dates:
        # T+1 update
        account.update_t_plus_one(d)

        # Reset risk manager
        rm.reset_daily(d)

        # Get today's prices
        try:
            today_prices = bars.loc[d]["close"].to_dict()
        except KeyError:
            continue

        # Generate signals
        historical = bars[bars.index.get_level_values(0) <= d]
        signals = signal_engine.generate_signals(historical, factors, d)

        # Execute signals
        for sig in signals:
            price = today_prices.get(sig.symbol, 0)
            if price <= 0:
                continue

            # Risk check
            result = rm.check_order(
                sig.symbol, sig.side.value, 100, price, account, d
            )
            if not result.passed:
                continue

            if sig.side == Side.BUY:
                account.buy(sig.symbol, price, 100, d)
            else:
                account.sell(sig.symbol, price, 100, d)

        # Record portfolio value
        pv = account.portfolio_value(today_prices)
        portfolio_history.append({"date": d, "value": pv})

    # Results
    summary = account.summary()
    print(f"\n  Results:")
    print(f"    Trading days: {len(dates)}")
    print(f"    Total trades: {summary['total_trades']}")
    print(f"    Final value: {summary.get('cash', 0):,.0f} cash + positions")

    if portfolio_history:
        initial = portfolio_history[0]["value"]
        final = portfolio_history[-1]["value"]
        ret = (final / initial - 1) * 100
        print(f"    Return: {ret:+.2f}% ({initial:,.0f} -> {final:,.0f})")

    print(f"    Max drawdown: {summary.get('max_drawdown', 0):.2f}%")

    # Save
    path = account.save("paper_test_run.json")
    print(f"    Saved to: {path}")

    print(f"\n  ✅ Full paper trading test passed")
    return True


if __name__ == "__main__":
    all_ok = True
    all_ok &= test_paper_account()
    all_ok &= test_risk_manager()
    all_ok &= test_signal_engine()
    all_ok &= test_scheduler()
    all_ok &= test_full_paper_trading()

    print("\n" + "=" * 60)
    print("ALL PHASE 4 TESTS PASSED" if all_ok else "Some tests failed")
    print("=" * 60)
