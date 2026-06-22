from __future__ import annotations

import pandas as pd

from scripts.build_fund_tail_candidates import build_candidate_rows


def test_build_candidate_rows_maps_equity_funds_to_tail_proxies():
    source = pd.DataFrame(
        [
            {"基金代码": "110020", "基金简称": "易方达沪深300ETF联接A", "基金类型": "指数型-股票"},
            {"基金代码": "161028", "基金简称": "富国中证新能源汽车指数(LOF)A", "基金类型": "指数型-股票"},
            {"基金代码": "000001", "基金简称": "华夏成长混合", "基金类型": "混合型-灵活"},
            {"基金代码": "000003", "基金简称": "中海可转债债券A", "基金类型": "债券型-混合二级"},
            {"基金代码": "000198", "基金简称": "天弘余额宝货币A", "基金类型": "货币型"},
            {"基金代码": "110020", "基金简称": "易方达沪深300ETF联接A", "基金类型": "指数型-股票"},
        ]
    )

    rows = build_candidate_rows(source, limit=10)

    assert [row["fund_code"] for row in rows] == ["161028", "110020", "000001"]
    assert rows[0]["proxy_code"] == "399976"
    assert rows[0]["fund_type"] == "sector"
    assert rows[1]["proxy_provider"] == "csindex"
    assert rows[1]["proxy_code"] == "000300"
    assert rows[1]["fund_type"] == "broad_index"
    assert rows[2]["proxy_provider"] == "csindex"
    assert rows[2]["proxy_code"] == "000300"
    assert rows[2]["fund_type"] == "active_mixed"


def test_build_candidate_rows_keeps_builtin_watchlist_first():
    source = pd.DataFrame(
        [
            {"基金代码": "110003", "基金简称": "易方达上证50增强A", "基金类型": "指数型-股票"},
            {"基金代码": "007995", "基金简称": "华夏中证500指数增强C", "基金类型": "指数型-股票"},
        ]
    )

    rows = build_candidate_rows(source, limit=10)

    assert [row["fund_code"] for row in rows] == ["007995", "110003"]


def test_build_candidate_rows_excludes_unmapped_overseas_and_commodity_funds():
    source = pd.DataFrame(
        [
            {"基金代码": "000055", "基金简称": "广发纳斯达克100ETF联接美元(QDII)A", "基金类型": "QDII"},
            {"基金代码": "000071", "基金简称": "华夏恒生ETF联接A", "基金类型": "QDII"},
            {"基金代码": "000216", "基金简称": "华安黄金ETF联接A", "基金类型": "商品型"},
            {"基金代码": "000311", "基金简称": "景顺长城沪深300指数增强A", "基金类型": "指数型-股票"},
        ]
    )

    rows = build_candidate_rows(source, limit=10)

    assert [row["fund_code"] for row in rows] == ["000055", "000311"]
    assert rows[0]["proxy_provider"] == "us_sina"
    assert rows[0]["proxy_code"] == "QQQ"
