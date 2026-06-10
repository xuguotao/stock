from __future__ import annotations

from datetime import date

from src.strategy.executor import RealTimeExecutor
from src.strategy.scanner import TailSessionSignal
from src.trading.paper_account import PaperAccount
from src.trading.risk_manager import RiskManager


def test_realtime_executor_buys_confirmed_tail_signal(tmp_path) -> None:
    account = PaperAccount(initial_capital=100_000, data_dir=str(tmp_path))
    executor = RealTimeExecutor(
        account=account,
        risk_manager=RiskManager(max_single_weight=0.25, max_total_position=0.8),
        max_single_weight=0.2,
    )
    signal = TailSessionSignal(
        symbol="000001.SZ",
        trade_date=date(2025, 6, 3),
        strength=0.9,
        last_price=10.0,
        volume_ratio=2.0,
        tail_return=0.02,
        reason="tail price-volume confirmation",
    )

    trades = executor.execute_buy_signals(
        [signal],
        prices={"000001.SZ": 10.0},
        trade_date=date(2025, 6, 3),
    )

    assert len(trades) == 1
    assert trades[0].symbol == "000001.SZ"
    assert trades[0].side == "buy"
    assert account.positions["000001.SZ"].quantity == 2000


def test_realtime_executor_sells_on_take_profit(tmp_path) -> None:
    account = PaperAccount(initial_capital=100_000, data_dir=str(tmp_path))
    account.buy("000001.SZ", 10.0, 1000, date(2025, 6, 3))
    account.update_t_plus_one(date(2025, 6, 4))
    executor = RealTimeExecutor(account=account, risk_manager=RiskManager())

    trades = executor.sell_positions(
        prices={"000001.SZ": 10.3},
        trade_date=date(2025, 6, 4),
    )

    assert len(trades) == 1
    assert trades[0].side == "sell"
    assert "000001.SZ" not in account.positions


def test_realtime_executor_holds_when_exit_rules_not_triggered(tmp_path) -> None:
    account = PaperAccount(initial_capital=100_000, data_dir=str(tmp_path))
    account.buy("000001.SZ", 10.0, 1000, date(2025, 6, 3))
    account.update_t_plus_one(date(2025, 6, 4))
    executor = RealTimeExecutor(account=account, risk_manager=RiskManager())

    trades = executor.sell_positions(
        prices={"000001.SZ": 10.1},
        trade_date=date(2025, 6, 4),
    )

    assert trades == []
    assert "000001.SZ" in account.positions
