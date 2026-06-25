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


def test_build_tail_feature_frame_adds_prior_market_context_without_future_leakage() -> None:
    daily = _daily_fixture()
    peer_rows = []
    for row in daily.to_dict("records"):
        peer = dict(row)
        peer["symbol"] = "000002.SZ"
        peer["close"] = float(peer["close"]) * 2
        peer["open"] = float(peer["open"]) * 2
        peer["high"] = float(peer["high"]) * 2
        peer["low"] = float(peer["low"]) * 2
        peer["amount"] = float(peer["amount"]) * 2
        peer_rows.append(peer)
    # This future daily jump must not leak into the 2026-02-09 feature row.
    daily.loc[daily["date"] == date(2026, 2, 10), "close"] = 99.0
    daily = pd.concat([daily, pd.DataFrame(peer_rows)], ignore_index=True)

    features = build_tail_feature_frame(
        daily_bars=daily,
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 40)],
    )

    row = features.iloc[0]
    expected_market_ret_5 = ((12.6 / 12.1 - 1) + (25.2 / 24.2 - 1)) / 2
    assert row["market_ret_5"] == pytest.approx(expected_market_ret_5)
    assert row["market_breadth_20"] == pytest.approx(1.0)
    assert row["relative_ret_5"] == pytest.approx(row["daily_ret_5"] - row["market_ret_5"])


def test_build_tail_feature_frame_precomputes_daily_context(monkeypatch) -> None:
    import src.ml.tail_features as tail_features

    daily = pd.concat([_daily_fixture().assign(symbol="000001.SZ"), _daily_fixture().assign(symbol="000002.SZ")], ignore_index=True)
    minute5 = pd.concat([_minute5_fixture().assign(symbol="000001.SZ"), _minute5_fixture().assign(symbol="000002.SZ")], ignore_index=True)
    calls = 0
    original_daily_features = tail_features._daily_features

    def counting_daily_features(prior_daily):
        nonlocal calls
        calls += 1
        return original_daily_features(prior_daily)

    monkeypatch.setattr(tail_features, "_daily_features", counting_daily_features)

    features = tail_features.build_tail_feature_frame(
        daily_bars=daily,
        minute5_bars=minute5,
        decision_times=[time(14, 35), time(14, 40)],
    )

    assert len(features) == 4
    assert calls <= 2


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


def test_build_tail_ml_samples_marks_dirty_outcome_prices_as_null_labels() -> None:
    daily = _daily_fixture()
    dirty_date = date(2026, 2, 10)
    daily.loc[daily["date"] == dirty_date, ["open", "high", "low", "close"]] = 0.0

    result = build_tail_ml_samples(
        daily_bars=daily,
        minute5_bars=_minute5_fixture(),
        decision_times=[time(14, 40)],
    )

    assert result.summary["null_label_rows"] == 1
    row = result.samples.iloc[0]
    assert pd.isna(row["next_open_return"])
    assert pd.isna(row["next_high_return"])
    assert pd.isna(row["next_close_return"])
    assert pd.isna(row["next_low_return"])


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
    minute5_query, minute5_params = next((query, params) for query, params in client.queries if "from minute5_kline" in query.lower())
    normalized_minute5_query = " ".join(minute5_query.lower().split())
    assert "tohour(datetime) = %(tail_start_hour)s" in normalized_minute5_query
    assert "tominute(datetime) >= %(tail_start_minute)s" in normalized_minute5_query
    assert minute5_params["tail_start_hour"] == 14
    assert minute5_params["tail_start_minute"] == 30


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
