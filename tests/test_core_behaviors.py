from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.core.types import Side
from src.research.factor_analysis.neutralization import FactorNeutralizer
from src.strategy.execution.broker import SimulatedBroker
from src.strategy.execution.order import Order
from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor
from src.trading.signal_engine import SignalEngine


def _sample_bars() -> pd.DataFrame:
    symbols = ["000001.SZ", "600519.SH", "300750.SZ", "000858.SZ", "601318.SH"]
    dates = pd.bdate_range("2025-01-01", periods=30)
    rows = []

    for symbol_idx, symbol in enumerate(symbols):
        price = 10 + symbol_idx * 5
        for day_idx, d in enumerate(dates):
            price *= 1 + 0.001 * (symbol_idx + 1) + 0.0002 * day_idx
            rows.append(
                {
                    "date": d,
                    "symbol": symbol,
                    "open": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price,
                    "volume": 1_000_000,
                    "amount": price * 1_000_000,
                    "adjusted_close": price,
                }
            )

    return pd.DataFrame(rows).set_index(["date", "symbol"])


def test_broker_enforces_t_plus_one_and_lot_size() -> None:
    broker = SimulatedBroker(initial_capital=100_000)
    buy_day = date(2025, 6, 3)
    sell_day = date(2025, 6, 4)

    buy = broker.submit_order(
        Order(symbol="000001.SZ", side=Side.BUY, quantity=150),
        buy_day,
        current_price=10.0,
    )

    assert buy.is_filled
    assert buy.filled_quantity == 100

    same_day_sell = broker.submit_order(
        Order(symbol="000001.SZ", side=Side.SELL, quantity=100),
        buy_day,
        current_price=10.1,
    )
    assert same_day_sell.is_rejected
    assert "T+1" in same_day_sell.reject_reason

    broker.update_available_positions(sell_day)
    next_day_sell = broker.submit_order(
        Order(symbol="000001.SZ", side=Side.SELL, quantity=100),
        sell_day,
        current_price=10.1,
    )
    assert next_day_sell.is_filled


def test_factor_neutralizer_preserves_valid_cross_section_values() -> None:
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
        factor,
        industry_codes=industry,
        market_cap=market_cap,
    )

    assert neutral.index.equals(factor.index)
    assert neutral.columns.tolist() == ["momentum"]
    assert neutral["momentum"].notna().all()
    assert abs(float(neutral.groupby(level=0)["momentum"].mean().max())) < 1e-8


def test_signal_engine_matches_date_against_timestamp_index() -> None:
    bars = _sample_bars()
    engine = SignalEngine(top_n=2, rebalance_days=1, min_strength=0.0)

    signals = engine.generate_signals(
        bars,
        [MomentumFactor(window=5), TrendFactor(short_window=3, long_window=10)],
        trade_date=date(2025, 2, 11),
    )

    buys = [signal for signal in signals if signal.side == Side.BUY]
    assert len(buys) == 2
    assert all(0 <= signal.strength <= 1 for signal in buys)
