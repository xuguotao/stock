from __future__ import annotations

from datetime import date

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
        "--limit",
        "2",
        "--include-beijing",
        "--bestip",
        "--server",
        "119.147.212.81:7709",
        "--no-ensure-tables",
    ])

    assert args.symbols == ["000001.SZ", "600519.SH"]
    assert args.trade_date == date(2026, 7, 9)
    assert args.tasks == ["stock_catalog", "minutes_probe", "f10_catalog_probe", "affair_file_list_probe"]
    assert args.frequencies == ["5m", "daily"]
    assert args.limit == 2
    assert args.include_beijing is True
    assert args.bestip is True
    assert args.server == ("119.147.212.81", 7709)
    assert args.ensure_tables is False
