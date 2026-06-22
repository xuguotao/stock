from __future__ import annotations

import pandas as pd

from src.monitoring.watchlist import (
    WatchlistLevels,
    WatchlistStockConfig,
    classify_watchlist_stock,
    compute_stock_metrics,
    load_watchlist_config,
)


def test_load_watchlist_config_reads_stock_levels(tmp_path) -> None:
    config_path = tmp_path / "watchlist.yaml"
    config_path.write_text(
        """
stocks:
  - symbol: "601899"
    name: "紫金矿业"
    theme: "金铜资源"
    notes: "关注金铜价格。"
    levels:
      observe: [30.0, 30.5]
      entry: [29.5, 29.8]
      add: [28.5, 29.0]
      invalid: 27.0
      breakout: 32.0
""".strip(),
        encoding="utf-8",
    )

    config = load_watchlist_config(config_path)

    assert len(config.stocks) == 1
    assert config.stocks[0].symbol == "601899"
    assert config.stocks[0].levels.entry == (29.5, 29.8)


def test_classify_entry_zone_takes_precedence_over_hot_return() -> None:
    stock = WatchlistStockConfig(
        symbol="601899",
        name="紫金矿业",
        theme="金铜资源",
        notes="",
        levels=WatchlistLevels(
            observe=(30.0, 30.5),
            entry=(29.5, 29.8),
            add=(28.5, 29.0),
            invalid=27.0,
            breakout=32.0,
        ),
    )

    result = classify_watchlist_stock(
        stock,
        latest_price=29.7,
        daily_change_pct=2.0,
        return_5d=0.22,
        return_20d=0.4,
        volume_ratio=1.4,
        data_status="snapshot_ok",
        quote_snapshot_at="2026-06-17 10:58:08",
    )

    assert result.status == "entry_zone"
    assert result.quote_snapshot_at == "2026-06-17 10:58:08"
    assert result.data_status == "snapshot_ok"
    assert "试仓区" in " ".join(result.reasons)


def test_classify_hot_wait_after_large_recent_gain() -> None:
    stock = WatchlistStockConfig(
        symbol="000636",
        name="风华高科",
        theme="MLCC",
        notes="",
        levels=WatchlistLevels(
            observe=(68.0, 70.0),
            entry=(64.0, 66.0),
            add=(58.0, 60.0),
            invalid=54.0,
            breakout=72.0,
        ),
    )

    result = classify_watchlist_stock(
        stock,
        latest_price=73.0,
        daily_change_pct=5.0,
        return_5d=0.18,
        return_20d=0.6,
        volume_ratio=1.0,
    )

    assert result.status == "hot_wait"
    assert any("涨幅过大" in reason for reason in result.reasons)


def test_compute_stock_metrics_calculates_returns_and_volume_ratio() -> None:
    bars = pd.DataFrame({
        "close": [10, 11, 12, 13, 14, 15],
        "volume": [100, 100, 100, 100, 100, 250],
    })

    metrics = compute_stock_metrics(bars)

    assert metrics["return_5d"] == 0.5
    assert metrics["ma5"] == 13.0
    assert metrics["volume_ratio"] == 2.5
