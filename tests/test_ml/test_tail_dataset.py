from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd
import pytest

from src.ml.tail_dataset import build_tail_ml_samples
from src.ml.tail_dataset import build_tail_ml_samples_from_clickhouse
from src.ml.tail_dataset import write_tail_ml_samples_cache
from src.ml.tail_features import build_tail_feature_frame
from src.ml.tail_labels import build_tail_label_frame


def _daily_fixture() -> pd.DataFrame:
    rows = []
    base_dates = pd.bdate_range("2026-01-01", periods=28)
    for index, current_date in enumerate(base_dates):
        close = 10.0 + index * 0.1
        rows.append(
            {
                "symbol": "000001.SZ",
                "date": current_date.date(),
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 1_000_000 + index * 10_000,
                "amount": close * (1_000_000 + index * 10_000),
            }
        )
    # Next-session label row after the signal day.
    rows.append(
        {
            "symbol": "000001.SZ",
            "date": date(2026, 2, 10),
            "open": 13.1,
            "high": 13.6,
            "low": 12.7,
            "close": 13.3,
            "volume": 1_500_000,
            "amount": 13.3 * 1_500_000,
        }
    )
    return pd.DataFrame(rows)


def _minute5_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "datetime": datetime(2026, 2, 9, 14, 30),
                "open": 12.6,
                "high": 12.7,
                "low": 12.55,
                "close": 12.6,
                "volume": 50_000,
                "amount": 630_000,
            },
            {
                "symbol": "000001.SZ",
                "datetime": datetime(2026, 2, 9, 14, 35),
                "open": 12.6,
                "high": 12.8,
                "low": 12.58,
                "close": 12.75,
                "volume": 80_000,
                "amount": 1_020_000,
            },
            {
                "symbol": "000001.SZ",
                "datetime": datetime(2026, 2, 9, 14, 40),
                "open": 12.75,
                "high": 12.95,
                "low": 12.72,
                "close": 12.9,
                "volume": 120_000,
                "amount": 1_548_000,
            },
        ]
    )


def test_build_tail_feature_frame_uses_only_prior_daily_and_current_tail_bars() -> None:
    features = build_tail_feature_frame(
        daily_bars=_daily_fixture(),
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 35), time(14, 40)],
    )

    assert list(features["decision_time"]) == ["14:35", "14:40"]
    first = features.iloc[0]
    second = features.iloc[1]
    assert first["trade_date"] == date(2026, 2, 9)
    assert first["symbol"] == "000001.SZ"
    assert first["entry_price"] == pytest.approx(12.75)
    assert first["tail_return_from_1430"] == pytest.approx(12.75 / 12.6 - 1)
    assert second["entry_price"] == pytest.approx(12.9)
    assert second["tail_volume"] == 250_000
    assert second["tail_pullback_from_high"] == pytest.approx(12.9 / 12.95 - 1)
    # Prior close for 2026-02-09 is 12.6; the next day 2026-02-10 must not leak into features.
    assert second["prior_close"] == pytest.approx(12.6)
    assert second["daily_ret_5"] == pytest.approx(12.6 / 12.1 - 1)


def test_build_tail_label_frame_uses_next_session_returns_from_entry_price() -> None:
    features = build_tail_feature_frame(
        daily_bars=_daily_fixture(),
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 40)],
    )

    labels = build_tail_label_frame(daily_bars=_daily_fixture(), feature_frame=features)

    row = labels.iloc[0]
    assert row["outcome_date"] == date(2026, 2, 10)
    assert row["next_open_return"] == pytest.approx(13.1 / 12.9 - 1)
    assert row["next_high_return"] == pytest.approx(13.6 / 12.9 - 1)
    assert row["next_close_return"] == pytest.approx(13.3 / 12.9 - 1)
    assert row["next_low_return"] == pytest.approx(12.7 / 12.9 - 1)
    assert row["hit_next_high_1pct"] is True
    assert row["drawdown_breach_2pct"] is False


def test_build_tail_ml_samples_merges_features_labels_and_quality_summary() -> None:
    result = build_tail_ml_samples(
        daily_bars=_daily_fixture(),
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 35), time(14, 40)],
    )

    assert result.summary == {
        "feature_rows": 2,
        "label_rows": 2,
        "sample_rows": 2,
        "symbols": 1,
        "trade_dates": 1,
        "null_label_rows": 0,
    }
    assert len(result.samples) == 2
    assert {"daily_ret_5", "tail_return_from_1430", "next_high_return", "hit_next_high_1pct"}.issubset(result.samples.columns)


def test_build_tail_ml_samples_from_clickhouse_queries_daily_and_minute5() -> None:
    class FakeClickHouseClient:
        def __init__(self) -> None:
            self.queries: list[tuple[str, object | None]] = []

        def execute(self, query, params=None):
            self.queries.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from daily_kline" in normalized:
                return [
                    (row["symbol"].split(".")[0], row["date"], row["open"], row["high"], row["low"], row["close"], row["volume"], row["amount"])
                    for row in _daily_fixture().to_dict("records")
                ]
            if "from minute5_kline" in normalized:
                return [
                    (row["symbol"].split(".")[0], row["datetime"], row["open"], row["high"], row["low"], row["close"], row["volume"], row["amount"])
                    for row in _minute5_fixture().to_dict("records")
                ]
            return []

    client = FakeClickHouseClient()

    result = build_tail_ml_samples_from_clickhouse(
        client=client,
        start=date(2026, 2, 9),
        end=date(2026, 2, 9),
        symbols=["000001.SZ"],
        decision_times=[time(14, 40)],
    )

    assert len(result.samples) == 1
    assert result.samples.iloc[0]["symbol"] == "000001.SZ"
    assert any("from daily_kline" in query.lower() for query, _params in client.queries)
    assert any("from minute5_kline" in query.lower() for query, _params in client.queries)


def test_write_tail_ml_samples_cache_requires_non_empty_labels(tmp_path) -> None:
    result = build_tail_ml_samples(
        daily_bars=_daily_fixture(),
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 40)],
    )
    output_path = tmp_path / "tail_ml_samples.parquet"

    metadata = write_tail_ml_samples_cache(result, output_path)

    assert output_path.exists()
    assert metadata == {
        "path": str(output_path),
        "sample_rows": 1,
        "symbols": 1,
        "trade_dates": 1,
        "null_label_rows": 0,
    }
    loaded = pd.read_parquet(output_path)
    assert len(loaded) == 1
    assert loaded.iloc[0]["next_high_return"] == pytest.approx(result.samples.iloc[0]["next_high_return"])


def test_write_tail_ml_samples_cache_rejects_null_labels(tmp_path) -> None:
    daily = _daily_fixture()
    result = build_tail_ml_samples(
        daily_bars=daily[daily["date"] != date(2026, 2, 10)],
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 40)],
    )

    with pytest.raises(ValueError, match="null labels"):
        write_tail_ml_samples_cache(result, tmp_path / "bad.parquet")
