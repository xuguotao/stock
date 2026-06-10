from datetime import date
import pandas as pd
from src.strategy.filters import DailyBreakoutFilter

def _bars(closes: list[float], symbol: str = "000001.SZ") -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=len(closes))
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "date": dates[i], "symbol": symbol,
            "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 1_000_000,
            "amount": c * 1_000_000, "adjusted_close": c,
        })
    return pd.DataFrame(rows).set_index(["date", "symbol"])

def test_ma_cross_filter_passes_golden_cross() -> None:
    closes = [10.0] * 25  # flat
    # Last few days rising sharply to push MA5 above MA20
    closes[-5:] = [10.5, 10.6, 10.7, 10.8, 10.9]
    bars = _bars(closes)
    f = DailyBreakoutFilter(breakout_window=20)
    result = f.filter(bars, date(2025, 2, 4), mode="ma_cross")
    assert "000001.SZ" in result

def test_creates_20_day_breakout_signal() -> None:
    # Create 25 days of data, last day breaks previous 20-day high
    closes = [10.0 + 0.01 * i for i in range(24)] + [10.5]
    bars = _bars(closes)
    f = DailyBreakoutFilter(breakout_window=20)
    result = f.filter(bars, date(2025, 2, 4))  # Day 25
    assert "000001.SZ" in result

def test_breakout_filter_ignores_data_after_trade_date() -> None:
    closes = [10.0] * 25 + [12.0]
    bars = _bars(closes)
    trade_date = bars.index.get_level_values("date")[24].date()

    result = DailyBreakoutFilter(breakout_window=20).filter(bars, trade_date)

    assert "000001.SZ" not in result

def test_trend_filter_passes_rising_prices() -> None:
    from src.strategy.filters import DailyTrendFilter
    closes = [10.0, 10.1, 10.2, 10.3, 10.5]  # rising
    bars = _bars(closes)
    f = DailyTrendFilter(trend_window=5, min_slope=0.0)
    result = f.filter(bars, date(2025, 1, 7))
    assert "000001.SZ" in result

def test_trend_filter_rejects_falling_prices() -> None:
    from src.strategy.filters import DailyTrendFilter
    closes = [10.5, 10.3, 10.2, 10.1, 10.0]  # falling
    bars = _bars(closes)
    f = DailyTrendFilter(trend_window=5, min_slope=0.0)
    result = f.filter(bars, date(2025, 1, 7))
    assert "000001.SZ" not in result

def test_breakout_filter_rejects_no_breakout() -> None:
    closes = [10.0] * 25
    bars = _bars(closes)
    f = DailyBreakoutFilter(breakout_window=20)
    result = f.filter(bars, date(2025, 2, 4))
    assert "000001.SZ" not in result

def test_filters_return_empty_for_empty_bars() -> None:
    from src.strategy.filters import DailyTrendFilter
    empty_bars = pd.DataFrame()
    assert DailyBreakoutFilter().filter(empty_bars, date(2025, 1, 1)) == []
    assert DailyTrendFilter().filter(empty_bars, date(2025, 1, 1)) == []


def test_stocks_pool_excludes_st_stocks() -> None:
    from src.strategy.filters import StockPoolFilter
    f = StockPoolFilter(min_list_days=60, min_avg_amount=5_000_000)
    stock_info = {
        "000001.SZ": {"name": "平安银行", "list_date": date(1991, 4, 3)},
        "*ST123.SZ": {"name": "*ST某某", "list_date": date(2020, 1, 1)},
    }
    bars = _bars([10.0] * 70, "000001.SZ")
    bars2 = _bars([5.0] * 70, "*ST123.SZ")
    all_bars = pd.concat([bars, bars2])

    result = f.filter(all_bars, date(2025, 4, 1), stock_info=stock_info)
    assert "000001.SZ" in result
    assert "*ST123.SZ" not in result
