from pathlib import Path


def test_stock_trend_page_has_market_terminal_chart() -> None:
    page_source = Path("frontend/src/pages/StockTrend.vue").read_text(encoding="utf-8")

    assert "quote-strip" in page_source
    assert "candlestick" in page_source
    assert "MA5" in page_source
    assert "MA10" in page_source
    assert "MA20" in page_source
    assert "MA60" in page_source
    assert "成交量" in page_source
    assert "dataZoom" in page_source
    assert "stock-chart" in page_source
