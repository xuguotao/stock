from __future__ import annotations

from datetime import date

from src.strategy.reports import render_tail_session_report, write_tail_session_report
from src.strategy.scanner import TailSessionSignal
from src.core.broker_base import BrokerTrade


def _signal(symbol: str = "000001.SZ") -> TailSessionSignal:
    return TailSessionSignal(
        symbol=symbol,
        trade_date=date(2025, 6, 3),
        strength=0.82,
        last_price=10.5,
        volume_ratio=1.8,
        tail_return=0.021,
        reason="tail price-volume confirmation",
    )


def _trade() -> BrokerTrade:
    return BrokerTrade(
        trade_id="T000001",
        symbol="000001.SZ",
        side="buy",
        price=10.5,
        quantity=1000,
        amount=10_500,
        commission=5.25,
        date=date(2025, 6, 3),
    )


def test_render_tail_session_report_contains_daily_sections() -> None:
    report = render_tail_session_report(
        trade_date=date(2025, 6, 3),
        scanned_count=20,
        candidates=[_signal()],
        confirmed=[_signal()],
        trades=[_trade()],
        account_summary={"cash": 89_494.75, "total_value": 100_000, "total_trades": 1},
    )

    assert "# 尾盘策略日报 2025-06-03" in report
    assert "扫描股票数: 20" in report
    assert "## 候选信号" in report
    assert "000001.SZ" in report
    assert "## 成交记录" in report
    assert "BUY" in report
    assert "## 账户摘要" in report
    assert "cash" in report


def test_write_tail_session_report_creates_markdown_file(tmp_path) -> None:
    path = write_tail_session_report(
        output_dir=tmp_path,
        trade_date=date(2025, 6, 3),
        scanned_count=1,
        candidates=[_signal()],
        confirmed=[],
        trades=[],
        account_summary={"cash": 100_000},
    )

    assert path.name == "tail_session_2025-06-03.md"
    assert path.exists()
    assert "确认信号: 0" in path.read_text(encoding="utf-8")
