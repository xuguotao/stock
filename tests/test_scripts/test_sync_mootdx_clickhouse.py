from __future__ import annotations

from datetime import date

from scripts import sync_mootdx_clickhouse
from scripts.sync_mootdx_clickhouse import parse_args


def test_parse_args_supports_default_and_extended_tasks() -> None:
    args = parse_args([
        "--symbols",
        "000001.SZ,600519.SH",
        "--trade-date",
        "2026-07-09",
        "--tasks",
        "stock_catalog,minutes_probe,f10_catalog_probe,affair_file_list_probe",
        "--frequencies",
        "5m,daily",
        "--daily-mode",
        "backfill",
        "--daily-offset",
        "800",
        "--start-date",
        "2023-03-01",
        "--end-date",
        "2026-07-09",
        "--limit",
        "2",
        "--include-beijing",
        "--bestip",
        "--server",
        "119.147.212.81:7709",
        "--rate-limit",
        "0.05",
        "--recheck-no-data",
        "--daily-reconcile",
        "--no-ensure-tables",
    ])

    assert args.symbols == ["000001.SZ", "600519.SH"]
    assert args.trade_date == date(2026, 7, 9)
    assert args.tasks == ["stock_catalog", "minutes_probe", "f10_catalog_probe", "affair_file_list_probe"]
    assert args.frequencies == ["5m", "daily"]
    assert args.daily_mode == "backfill"
    assert args.daily_offset == 800
    assert args.start_date == date(2023, 3, 1)
    assert args.end_date == date(2026, 7, 9)
    assert args.limit == 2
    assert args.include_beijing is True
    assert args.bestip is True
    assert args.server == ("119.147.212.81", 7709)
    assert args.rate_limit == 0.05
    assert args.recheck_no_data is True
    assert args.daily_reconcile is True
    assert args.ensure_tables is False


def test_parse_args_defaults_to_benchmarked_mootdx_rate_limit() -> None:
    args = parse_args([])

    assert args.rate_limit == 0.02


def test_main_accepts_structured_daily_progress(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sync_mootdx_clickhouse, "MootdxSource", lambda **_kwargs: object())

    def fake_sync(**kwargs):
        kwargs["progress"](30, "stock_kline_daily", "同步日线 000001.SZ", processed=1, total=2)
        return {"failed": {}}

    monkeypatch.setattr(sync_mootdx_clickhouse, "sync_mootdx_offline_data", fake_sync)

    assert sync_mootdx_clickhouse.main(["--tasks", "stock_kline_daily", "--trade-date", "2026-07-10"]) == 0
    assert "[ 30%] stock_kline_daily: 同步日线 000001.SZ (1 / 2)" in capsys.readouterr().err
