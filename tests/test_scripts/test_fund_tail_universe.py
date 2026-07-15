import pandas as pd

from scripts.backtest_fund_tail_advice import (
    FUNDS,
    PROXY_INDEXES,
    download_fund_nav,
    load_fund_universe,
    proxy_info_for,
)


def test_requested_funds_are_in_tail_advice_universe():
    requested = {
        "161604",
        "161005",
        "162412",
        "161028",
        "000696",
        "260108",
        "000977",
        "012968",
        "320007",
        "110020",
        "163406",
        "004851",
        "005827",
    }

    assert requested.issubset(FUNDS)


def test_index_like_requested_funds_have_proxy_mapping():
    expected = {
        "161604": ("cni", "399330", "sz399330"),
        "162412": ("csindex", "399989", "sz399989"),
        "161028": ("csindex", "399976", "sz399976"),
        "110020": ("csindex", "000300", "sh000300"),
    }

    for code, proxy in expected.items():
        assert PROXY_INDEXES[code] == proxy


def test_candidate_file_can_expand_backtest_universe(tmp_path):
    candidates = tmp_path / "candidates.csv"
    candidates.write_text(
        "\n".join(
            [
                "fund_code,fund_name,fund_type,candidate_tier,proxy_provider,proxy_code,fee_tag,min_holding_days,enabled,tail_strategy_eligible,exclude_reason",
                "110003,易方达上证50增强A,broad_index,preferred,csindex,000016,低费率,7,true,true,",
                "000001,华夏成长混合,active_mixed,cautious,nav,000001,普通费率,7,true,true,",
                "000002,无效债券,bond,excluded,nav,000002,普通费率,7,true,true,",
            ]
        ),
        encoding="utf-8",
    )

    funds, proxy_indexes, proxy_names = load_fund_universe(candidates)

    assert funds == {
        "110003": "易方达上证50增强A",
        "000001": "华夏成长混合",
    }
    assert proxy_indexes["110003"] == ("csindex", "000016", "sh000016")
    assert "000001" not in proxy_indexes
    assert proxy_info_for("110003", proxy_indexes, proxy_names) == {
        "proxy_provider": "csindex",
        "proxy_code": "000016",
        "proxy_name": "上证50",
    }


def test_download_fund_nav_parses_eastmoney_js_without_akshare_js_runtime(monkeypatch):
    def fake_urlopen(req, timeout):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'var Data_netWorthTrend = [{"x":1438099200000,"y":1.0,'
                    b'"equityReturn":0,"unitMoney":""}];'
                )

        return Response()

    import scripts.backtest_fund_tail_advice as advice

    monkeypatch.setattr(advice.urllib.request, "urlopen", fake_urlopen)

    result = download_fund_nav("001632")

    assert result.to_dict(orient="records") == [
        {"date": pd.Timestamp("2015-07-29"), "close": 1.0}
    ]
