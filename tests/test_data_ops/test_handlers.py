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
