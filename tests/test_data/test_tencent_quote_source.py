from __future__ import annotations

import pandas as pd

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
