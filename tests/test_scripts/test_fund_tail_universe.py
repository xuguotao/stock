from scripts.backtest_fund_tail_advice import FUNDS, PROXY_INDEXES


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
