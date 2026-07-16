from __future__ import annotations

from datetime import date

import pytest

from src.data_ops.handlers import build_default_handlers


def test_handlers_call_injected_runners_without_web_dependencies() -> None:
    calls: list[str] = []
    handlers = build_default_handlers(
        minute5_runner=lambda **kwargs: calls.append("minute5") or {"inserted_rows": 5},
        quote_snapshot_runner=lambda **kwargs: calls.append("quote") or {"inserted_rows": 10},
        quote_rollup_runner=lambda **kwargs: calls.append("rollup") or {"optimized": True},
        data_status_runner=lambda **kwargs: calls.append("status") or {"quality": {"status": "ok"}},
        quality_snapshot_writer=lambda **kwargs: calls.append("quality") or {"rows": 3},
        daily_repair_runner=lambda **kwargs: calls.append("daily") or {"rows": 2},
        index_daily_sync_runner=lambda **kwargs: calls.append("index") or {"rows": 1},
        stock_master_runner=lambda **kwargs: calls.append("stock_master") or {"inserted_rows": 2},
    )

    assert handlers["stock_master_sync"]({})["inserted_rows"] == 2
    assert handlers["minute5_intraday_sync"]({"trade_date": "2026-06-12"})["inserted_rows"] == 5
    assert handlers["quote_snapshot_capture"]({})["inserted_rows"] == 10
    assert handlers["quote_rollup_refresh"]({})["optimized"] is True
    assert handlers["quality_snapshot"]({})["rows"] == 3
    result = handlers["post_close_maintenance"]({"trade_date": "2026-06-12"})

    assert result["trade_date"] == date(2026, 6, 12).isoformat()
    assert calls == [
        "stock_master",
        "minute5",
        "quote",
        "rollup",
        "status",
        "quality",
        "minute5",
        "status",
        "quality",
        "daily",
        "index",
    ]


def test_handler_exceptions_are_not_swallowed() -> None:
    handlers = build_default_handlers(minute5_runner=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        handlers["minute5_intraday_sync"]({"trade_date": "2026-06-12"})


def test_quote_snapshot_handler_passes_endpoint_and_chunk_size() -> None:
    calls = []

    def fake_quote_snapshot(**kwargs):
        calls.append(kwargs)
        return {"inserted_rows": 10, "quote_endpoint": kwargs["quote_endpoint"]}

    handlers = build_default_handlers(quote_snapshot_runner=fake_quote_snapshot)

    result = handlers["quote_snapshot_capture"]({"chunk_size": 500, "quote_endpoint": "sqt_utf8"})

    assert result["quote_endpoint"] == "sqt_utf8"
    assert calls[0]["chunk_size"] == 500
    assert calls[0]["quote_endpoint"] == "sqt_utf8"


def test_mootdx_handlers_run_independent_catalog_daily_and_reconciliation_tasks() -> None:
    calls = []

    def fake_mootdx_sync(**kwargs):
        calls.append(kwargs)
        return {"tasks": kwargs["tasks"], "daily_reconcile": kwargs.get("daily_reconcile", False)}

    handlers = build_default_handlers(mootdx_sync_runner=fake_mootdx_sync)

    assert handlers["mootdx_stock_catalog_sync"]({"trade_date": "2026-07-09"})["tasks"] == ["stock_catalog"]
    assert handlers["mootdx_daily_kline_sync"]({"trade_date": "2026-07-09"})["tasks"] == ["stock_kline_daily"]
    assert handlers["mootdx_daily_kline_reconcile"]({"trade_date": "2026-07-09"})["daily_reconcile"] is True
    assert handlers["mootdx_xdxr_sync"]({"trade_date": "2026-07-09"})["tasks"] == ["xdxr"]
    assert [call["daily_reconcile"] for call in calls] == [False, False, True, False]
    assert all(call["trade_date"] == date(2026, 7, 9) for call in calls)


def test_mootdx_handler_passes_configured_connection_to_one_source_instance(monkeypatch) -> None:
    created = []
    calls = []

    class FakeMootdxSource:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr("src.data_ops.handlers.MootdxSource", FakeMootdxSource)

    def fake_mootdx_sync(**kwargs):
        calls.append(kwargs)
        return {"tasks": kwargs["tasks"]}

    handler = build_default_handlers(mootdx_sync_runner=fake_mootdx_sync)["mootdx_daily_kline_sync"]
    result = handler({
        "trade_date": "2026-07-09",
        "rate_limit": 0.02,
        "timeout": 20,
        "bestip": True,
        "server": "127.0.0.1:7709",
    })

    assert result == {"tasks": ["stock_kline_daily"]}
    assert created == [{
        "rate_limit": 0.02,
        "timeout": 20,
        "bestip": True,
        "server": ("127.0.0.1", 7709),
        "include_beijing": False,
    }]
    assert calls[0]["source"] is not None
    assert calls[0]["source"].__class__ is FakeMootdxSource


def test_mootdx_handler_uses_benchmarked_connection_defaults(monkeypatch) -> None:
    created = []

    class FakeMootdxSource:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr("src.data_ops.handlers.MootdxSource", FakeMootdxSource)
    handler = build_default_handlers(mootdx_sync_runner=lambda **kwargs: {"tasks": kwargs["tasks"]})["mootdx_daily_kline_sync"]

    handler({"trade_date": "2026-07-09"})

    assert created == [{
        "rate_limit": 0.02,
        "timeout": 15,
        "bestip": False,
        "server": None,
        "include_beijing": False,
    }]


def test_mootdx_handler_rejects_invalid_pinned_server() -> None:
    handler = build_default_handlers(mootdx_sync_runner=lambda **kwargs: {"tasks": kwargs["tasks"]})["mootdx_daily_kline_sync"]

    with pytest.raises(ValueError, match="host:port"):
        handler({"trade_date": "2026-07-09", "server": "not-a-server"})


def test_mootdx_handler_raises_when_sync_audit_is_failed() -> None:
    handlers = build_default_handlers(
        mootdx_sync_runner=lambda **kwargs: {
            "diagnostics": {"stock_kline_daily": {"audit": {"status": "failed", "reasons": ["coverage_below_target"]}}}
        }
    )

    with pytest.raises(RuntimeError, match="coverage_below_target"):
        handlers["mootdx_daily_kline_sync"]({"trade_date": "2026-07-09"})


def test_mootdx_handler_raises_when_inner_sync_returns_failed() -> None:
    handler = build_default_handlers(
        mootdx_sync_runner=lambda **_: {
            "tasks": ["stock_catalog"],
            "failed": {"stock_catalog": "AttributeError: bad code"},
        }
    )["mootdx_stock_catalog_sync"]

    with pytest.raises(RuntimeError, match=r"stock_catalog.*AttributeError: bad code"):
        handler({"trade_date": "2026-07-16"})


def test_stock_universe_profile_handler_passes_configured_rules() -> None:
    calls = []
    handlers = build_default_handlers(stock_universe_profile_runner=lambda **kwargs: calls.append(kwargs) or {"universe_eligible": 2})

    result = handlers["stock_universe_profile_refresh"]({
        "lookback_days": 30,
        "min_trading_days": 20,
        "min_average_amount": 20_000_000,
        "min_listing_age_days": 60,
        "include_beijing": True,
        "symbols": ["000001.SZ"],
    })

    assert result["universe_eligible"] == 2
    assert calls[0]["rules"].lookback_days == 30
    assert calls[0]["rules"].min_trading_days == 20
    assert calls[0]["rules"].include_beijing is True
    assert calls[0]["symbols"] == ["000001.SZ"]


def test_default_handlers_do_not_register_retired_xdxr_sync() -> None:
    assert "xdxr_sync" not in build_default_handlers()
