from __future__ import annotations

from datetime import date
from typing import Any

from src.data.strategy_universe import StrategyUniverseOptions, resolve_strategy_universe


class FakeUniverseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def execute(self, query: str, params: dict[str, Any] | None = None) -> list[tuple]:
        self.calls.append((query, params))
        if "from daily_kline d" in query:
            return [
                ("000001", "平安银行", "SZ", 62, date(2026, 6, 24), 100_000_000, 10_000_000),
                ("600000", "浦发银行", "SH", 61, date(2026, 6, 24), 90_000_000, 9_000_000),
                ("300001", "特锐德", "SZ", 12, date(2026, 6, 24), 80_000_000, 8_000_000),
                ("600001", "退市ST样本", "SH", 70, date(2026, 6, 24), 70_000_000, 7_000_000),
                ("688001", "华兴源创", "SH", 70, date(2026, 6, 20), 60_000_000, 6_000_000),
                ("430001", "北交样本", "BJ", 70, date(2026, 6, 24), 50_000_000, 5_000_000),
            ]
        if "from minute5_kline" in query:
            return [("000001",), ("600000",), ("430001",)]
        raise AssertionError(query)


def test_resolve_strategy_universe_applies_shared_filters() -> None:
    client = FakeUniverseClient()

    rows = resolve_strategy_universe(
        client,
        StrategyUniverseOptions(
            trade_date=date(2026, 6, 24),
            lookback_start=date(2026, 1, 1),
            min_daily_bars=60,
            require_latest_daily=True,
            require_minute5=True,
            include_st=False,
            markets=("SH", "SZ"),
        ),
    )

    assert [row.symbol for row in rows] == ["000001.SZ", "600000.SH"]
    assert rows[0].bars == 62
    assert rows[0].latest_date == date(2026, 6, 24)
    assert rows[0].market == "SZ"
    assert rows[0].has_minute5 is True


def test_resolve_strategy_universe_can_return_symbols_only() -> None:
    client = FakeUniverseClient()

    symbols = resolve_strategy_universe(
        client,
        StrategyUniverseOptions(
            trade_date=date(2026, 6, 24),
            lookback_start=date(2026, 1, 1),
            min_daily_bars=60,
            require_latest_daily=True,
            require_minute5=False,
            include_st=True,
            markets=("SH", "SZ", "BJ"),
        ),
        symbols_only=True,
    )

    assert symbols == [
        "000001.SZ",
        "600000.SH",
        "600001.SH",
        "430001.BJ",
    ]
