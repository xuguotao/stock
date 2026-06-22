from pathlib import Path


def test_fund_tail_table_supports_grade_sorting_and_filtering() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")

    assert ':default-sort="{ prop: \'操作等级\', order: \'ascending\' }"' in source
    assert 'prop="操作等级"' in source
    assert ':filters="gradeFilters"' in source
    assert ':filter-method="filterGrade"' in source


def test_fund_tail_table_exposes_prediction_confidence_columns() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")

    for label in [
        "代理标的",
        "匹配度",
        "评分",
        "3日胜率",
        "5日胜率",
        "5日中位收益",
        "跌超2%",
        "样本/可信度",
        "近5日",
        "20日回撤",
        "涨跌分位",
    ]:
        assert f'label="{label}"' in source
    assert "predictionConfidence" in source
    assert "confidenceType" in source


def test_fund_tail_table_exposes_sell_advice_columns() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")

    for label in [
        "卖出等级",
        "卖出建议",
        "卖出评分",
        "卖出原因",
    ]:
        assert f'label="{label}"' in source
    assert "sellScoreType" in source


def test_fund_tail_page_shows_report_update_time_and_chinese_data_labels() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")

    assert "报告更新" in source
    assert "formatDateTime(report.report_updated_at)" in source
    assert 'label="净值日期"' in source
    assert 'label="代理行情"' in source
    assert 'label="NAV"' not in source
    assert 'label="Proxy"' not in source


def test_fund_tail_page_exposes_watchlist_management_panel() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")

    assert "基金池管理" in source
    assert "持有中" in source
    assert "准备买入" in source
    assert "参与建议" in source
    assert "成本净值" in source
    assert "持仓金额" in source
    assert "浮盈亏%" in source
    assert "watchlistStatusText" in source


def test_fund_tail_watchlist_position_fields_use_plain_inputs() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")
    styles = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert 'placeholder="如 1.2345"' in source
    assert 'placeholder="如 5000"' in source
    assert 'placeholder="如 -12.50"' in source
    assert 'width="760px"' in source
    assert 'class="watchlist-dialog"' in source
    assert '<el-col :span="24">' in source
    assert ".watchlist-dialog" in styles
    assert "decimalToPercent" in source
    assert "percentToDecimal" in source
    assert 'label="持仓成本"' not in source
    assert 'label="持仓收益率"' not in source
    assert "el-input-number" not in source


def test_fund_tail_page_exposes_opportunity_discovery_panel() -> None:
    source = Path("frontend/src/pages/FundTail.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    for text in ["机会发现", "机会类型", "机会等级", "加入观察池"]:
        assert text in source
    assert "runOpportunityDiscovery" in source
    assert "addOpportunityToWatchlist" in source
    assert "submitFundTailOpportunities" in client
    assert "getFundTailOpportunities" in client
