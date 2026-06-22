import pandas as pd

from src.research.fund_tail_opportunities import (
    build_opportunity_rows,
    filter_eligible_candidates,
    load_candidates,
)


def test_load_candidates_normalizes_codes_and_filters_tail_strategy_types(tmp_path):
    candidate_file = tmp_path / "candidates.csv"
    candidate_file.write_text(
        "\n".join(
            [
                "fund_code,fund_name,fund_type,candidate_tier,proxy_provider,proxy_code,fee_tag,min_holding_days,enabled,tail_strategy_eligible,exclude_reason",
                "7995,华夏中证500指数增强C,broad_index,preferred,csindex,000905,低费率,7,true,true,",
                "000001,华夏成长混合,active_mixed,cautious,csindex,000300,普通费率,7,true,true,",
                "000002,货币基金,money,excluded,nav,000002,低风险,1,true,false,货基不适合尾盘策略",
                "000003,暂停基金,sector,preferred,csindex,399006,普通费率,7,false,true,暂停观察",
            ]
        ),
        encoding="utf-8",
    )

    candidates = load_candidates(candidate_file)
    eligible = filter_eligible_candidates(candidates)

    assert [candidate.fund_code for candidate in candidates] == ["007995", "000001", "000002", "000003"]
    assert [candidate.fund_code for candidate in eligible] == ["007995", "000001"]
    assert eligible[0].candidate_tier == "preferred"


def test_build_opportunity_rows_labels_new_add_hold_and_excluded_candidates():
    report = pd.DataFrame(
        [
            {
                "基金代码": "007995",
                "基金名称": "华夏中证500指数增强C",
                "操作等级": "A",
                "最终操作建议": "尾盘加仓",
                "建议原因": "预测优势较强",
                "预测加仓评分": 72.5,
                "5日预测上涨概率": 0.68,
                "5日预测中位数收益": 0.012,
                "5日预测跌超2%概率": 0.06,
                "代理匹配等级": "高",
                "代理匹配度": 0.97,
                "今日代理涨跌率": "0.85%",
            },
            {
                "基金代码": "161028",
                "基金名称": "富国中证新能源汽车指数(LOF)A",
                "操作等级": "B",
                "最终操作建议": "小额试探",
                "建议原因": "预测优势一般",
                "预测加仓评分": 61.0,
                "5日预测上涨概率": 0.63,
                "5日预测中位数收益": 0.008,
                "5日预测跌超2%概率": 0.20,
                "代理匹配等级": "高",
                "代理匹配度": 0.99,
                "今日代理涨跌率": "1.20%",
            },
            {
                "基金代码": "005827",
                "基金名称": "易方达蓝筹精选混合",
                "操作等级": "D",
                "最终操作建议": "不加仓",
                "建议原因": "同类历史下跌概率更高",
                "预测加仓评分": 35.0,
                "5日预测上涨概率": 0.45,
                "5日预测中位数收益": -0.002,
                "5日预测跌超2%概率": 0.18,
                "代理匹配等级": "中",
                "代理匹配度": 0.65,
                "今日代理涨跌率": "2.10%",
            },
        ]
    )
    candidates = load_candidates(
        pd.DataFrame(
            [
                {
                    "fund_code": "007995",
                    "fund_name": "华夏中证500指数增强C",
                    "fund_type": "broad_index",
                    "candidate_tier": "preferred",
                    "proxy_provider": "csindex",
                    "proxy_code": "000905",
                    "fee_tag": "低费率",
                    "min_holding_days": 7,
                    "enabled": True,
                    "tail_strategy_eligible": True,
                    "exclude_reason": "",
                },
                {
                    "fund_code": "161028",
                    "fund_name": "富国中证新能源汽车指数(LOF)A",
                    "fund_type": "sector",
                    "candidate_tier": "preferred",
                    "proxy_provider": "csindex",
                    "proxy_code": "399976",
                    "fee_tag": "普通费率",
                    "min_holding_days": 7,
                    "enabled": True,
                    "tail_strategy_eligible": True,
                    "exclude_reason": "",
                },
                {
                    "fund_code": "005827",
                    "fund_name": "易方达蓝筹精选混合",
                    "fund_type": "active_mixed",
                    "candidate_tier": "cautious",
                    "proxy_provider": "csindex",
                    "proxy_code": "000300",
                    "fee_tag": "普通费率",
                    "min_holding_days": 7,
                    "enabled": True,
                    "tail_strategy_eligible": True,
                    "exclude_reason": "",
                },
            ]
        )
    )

    rows = build_opportunity_rows(report, candidates, watchlist_codes={"161028"})

    by_code = {row["基金代码"]: row for row in rows}
    assert by_code["007995"]["机会类型"] == "新开仓候选"
    assert by_code["007995"]["机会建议"] == "可小额新开仓"
    assert by_code["161028"]["机会类型"] == "已在观察池"
    assert by_code["161028"]["机会建议"] == "已有池内小额加仓观察"
    assert by_code["005827"]["机会类型"] == "明确排除"
    assert by_code["005827"]["机会建议"] == "不参与"
    assert by_code["005827"]["机会原因"] == "同类历史下跌概率更高"
