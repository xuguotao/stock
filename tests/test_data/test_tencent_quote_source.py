from __future__ import annotations

from datetime import date

import pandas as pd

from src.data import tencent_source
from src.data.tencent_source import TencentQuoteSource, parse_tencent_quote_text


def test_parse_tencent_quote_text_outputs_standard_quote_columns() -> None:
    text = (
        'v_sh600519="1~贵州茅台~600519~1271.10~1291.91~1292.70~41586~17892~23693~'
        '1271.10~1~1271.00~2~1270.00~3~1269.00~4~1268.00~5~1272.00~1~1273.00~2~'
        '1274.00~3~1275.00~4~1276.00~5~~20260615150000~-20.81~-1.61~1298.00~'
        '1268.00~1271.10/41586/528000000~41586~52800~0.80~22.50~~1298.00~1268.00~'
        '2.32~16000.00~15000.00~8.50~1421.10~1162.72~18.00";\n'
        'v_sz000001="51~平安银行~000001~11.50~11.20~11.30~100000~50000~50000~'
        '11.50~1~11.49~2~11.48~3~11.47~4~11.46~5~11.51~1~11.52~2~11.53~3~'
        '11.54~4~11.55~5~~20260615150000~0.30~2.68~11.70~11.20~11.50/100000/115000000~'
        '100000~11500~1.20~6.50~~11.70~11.20~4.46~2200.00~2100.00~0.70~12.32~10.08~7.20";'
    )

    result = parse_tencent_quote_text(text)

    assert result["symbol"].tolist() == ["600519.SH", "000001.SZ"]
    assert result["price"].tolist() == [1271.10, 11.50]
    assert result["change_pct"].tolist() == [-1.61, 2.68]
    assert result["amount"].tolist() == [528_000_000.0, 115_000_000.0]
    assert result["pe_ttm"].tolist() == [22.5, 6.5]
    assert result["pb"].tolist() == [8.5, 0.7]
    assert result["limit_up"].tolist() == [1421.1, 12.32]
    assert result["limit_down"].tolist() == [1162.72, 10.08]


def test_tencent_quote_source_uses_injected_http_get() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append((url, headers, timeout))
        return (
            'v_sh600519="1~贵州茅台~600519~1271.10~1291.91~1292.70~0~0~0~'
            '0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~20260615150000~'
            '-20.81~-1.61~1298.00~1268.00~1271.10/41586/528000000~41586~52800~'
            '0.80~22.50~~1298.00~1268.00~2.32~16000.00~15000.00~8.50~1421.10~'
            '1162.72~18.00";'
        )

    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get)

    result = source.fetch_realtime_quotes(["600519.SH"])

    assert isinstance(result, pd.DataFrame)
    assert result.iloc[0]["symbol"] == "600519.SH"
    assert result.iloc[0]["float_mcap"] == 1_500_000_000_000.0
    assert calls[0][0].endswith("q=sh600519")


def test_tencent_quote_source_respects_explicit_exchange_suffix_for_indexes() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append(url)
        return (
            '{"code":0,"msg":"","data":{"sh000300":{"m5":['
            '["202606181500","4940.00","4941.60","4945.00","4938.00","1200.00",{},"1.20"]'
            ']}}}'
        )

    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get)

    result = source.fetch_intraday_bars("000300.SH", date(2026, 6, 18), "5m")

    assert calls[0].endswith("param=sh000300,m5,,320")
    assert result.iloc[0]["symbol"] == "000300.SH"
    assert result.iloc[0]["close"] == 4941.6


def test_parse_tencent_quote_text_preserves_sz_index_suffix() -> None:
    text = (
        'v_sz399396="51~国证食品~399396~14026.16~14319.00~14300.00~100~0~0~'
        '0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~20260618161436~'
        '-292.84~-2.04~14400.00~14000.00~14026.16/100/1402616~100~140~'
        '0.00~0.00~~14400.00~14000.00~2.80~0.00~0.00~0.00~-1~-1~1.00";'
    )

    result = parse_tencent_quote_text(text)

    assert result.iloc[0]["symbol"] == "399396.SZ"


def test_tencent_quote_source_batches_realtime_quotes_to_avoid_long_urls() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append(url)
        query = url.split("q=", 1)[1]
        lines = []
        for raw_symbol in query.split(","):
            code = raw_symbol[2:]
            lines.append(
                f'v_{raw_symbol}="1~测试{code}~{code}~10.00~9.90~9.95~0~0~0~'
                '0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~20260615150000~'
                '0.10~1.01~10.20~9.80~10.00/100/100000~100~10~1.00~12.00~~'
                '10.20~9.80~4.00~100.00~90.00~1.20~10.89~8.91~1.10";'
            )
        return "\n".join(lines)

    symbols = [f"{code:06d}.SZ" for code in range(1, 1201)]
    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get, realtime_chunk_size=400)

    result = source.fetch_realtime_quotes(symbols)

    assert len(calls) == 3
    assert all(url.count(",") < 400 for url in calls)
    assert len(result) == 1200
    assert result["symbol"].iloc[0] == "000001.SZ"
    assert result["symbol"].iloc[-1] == "001200.SZ"


def test_parse_tencent_kline_json_outputs_5m_intraday_bars() -> None:
    payload = {
        "code": 0,
        "msg": "",
        "data": {
            "sz000001": {
                "m5": [
                    ["202606171430", "10.80", "10.82", "10.85", "10.78", "1200.00", {}, "0.62"],
                    ["202606171435", "10.82", "10.88", "10.90", "10.81", "1500.00", {}, "0.77"],
                ]
            }
        },
    }

    result = tencent_source.parse_tencent_kline_json(payload, "000001.SZ", "5m")

    assert result["symbol"].tolist() == ["000001.SZ", "000001.SZ"]
    assert result["datetime"].tolist() == [
        pd.Timestamp("2026-06-17 14:30:00"),
        pd.Timestamp("2026-06-17 14:35:00"),
    ]
    assert result["open"].tolist() == [10.80, 10.82]
    assert result["high"].tolist() == [10.85, 10.90]
    assert result["low"].tolist() == [10.78, 10.81]
    assert result["close"].tolist() == [10.82, 10.88]
    assert result["volume"].tolist() == [1200.0, 1500.0]


def test_tencent_quote_source_fetches_5m_intraday_bars_for_trade_date() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append((url, headers, timeout))
        return (
            '{"code":0,"msg":"","data":{"sz000001":{"m5":['
            '["202606161500","10.00","10.10","9.90","10.05","900.00",{},"0.46"],'
            '["202606171430","10.80","10.82","10.85","10.78","1200.00",{},"0.62"],'
            '["202606171435","10.82","10.88","10.90","10.81","1500.00",{},"0.77"]'
            ']}}}'
        )

    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 17), "5m")

    assert result["datetime"].tolist() == [
        pd.Timestamp("2026-06-17 14:30:00"),
        pd.Timestamp("2026-06-17 14:35:00"),
    ]
    assert result.iloc[-1]["time"] == pd.Timestamp("2026-06-17 14:35:00").time()
    assert calls[0][0] == "https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sz000001,m5,,320"


def test_tencent_quote_source_returns_empty_for_unsupported_intraday_frequency() -> None:
    source = TencentQuoteSource(rate_limit=0.0, http_get=lambda **_: "{}")

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 17), "15m")

    assert result.empty


def test_tencent_quote_source_fetches_intraday_bars_batch() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append(url)
        if "sz000001" in url:
            return (
                '{"code":0,"msg":"","data":{"sz000001":{"m5":['
                '["202606171430","10.80","10.85","10.78","10.82","1200.00",{},"0.62"]'
                ']}}}'
            )
        return (
            '{"code":0,"msg":"","data":{"sh600000":{"m5":['
            '["202606171430","9.10","9.20","9.00","9.15","2200.00",{},"0.42"]'
            ']}}}'
        )

    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get, intraday_workers=2)

    result = source.fetch_intraday_bars_batch(["000001.SZ", "600000.SH"], date(2026, 6, 17), "5m")

    assert sorted(result["symbol"].unique().tolist()) == ["000001.SZ", "600000.SH"]
    assert len(result) == 2
    assert len(calls) == 2


def test_tencent_quote_source_fetches_1m_intraday_bars_with_incremental_volume() -> None:
    calls = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        calls.append(url)
        return (
            '{"code":0,"msg":"","data":{"sz000001":{"data":{"date":"20260617","data":['
            '"0930 10.97 6058 6645626.00",'
            '"0931 10.94 26828 29373159.21",'
            '"0932 10.95 31406 34384878.21",'
            '"1506 10.96 32000 35000000.00"'
            ']}}}}'
        )

    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 17), "1m")

    assert result["datetime"].tolist() == [
        pd.Timestamp("2026-06-17 09:30:00"),
        pd.Timestamp("2026-06-17 09:31:00"),
        pd.Timestamp("2026-06-17 09:32:00"),
    ]
    assert result["close"].tolist() == [10.97, 10.94, 10.95]
    assert result["open"].tolist() == [10.97, 10.94, 10.95]
    assert result["volume"].tolist() == [6058.0, 20770.0, 4578.0]
    assert result["amount"].tolist() == [6645626.0, 22727533.21, 5011719.0]
    assert calls[0] == "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sz000001"


def test_tencent_quote_source_rejects_1m_payload_for_different_trade_date() -> None:
    def fake_get(url: str, *, headers: dict[str, str], timeout: int):
        return (
            '{"code":0,"msg":"","data":{"sz000001":{"data":{"date":"20260617","data":['
            '"0930 10.97 6058 6645626.00"'
            ']}}}}'
        )

    source = TencentQuoteSource(rate_limit=0.0, http_get=fake_get)

    result = source.fetch_intraday_bars("000001.SZ", date(2026, 6, 16), "1m")

    assert result.empty
