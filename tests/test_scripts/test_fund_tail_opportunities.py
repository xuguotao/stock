from __future__ import annotations

import subprocess
import sys

import pandas as pd


def test_discover_fund_tail_opportunities_writes_chinese_report(tmp_path) -> None:
    advice_report = tmp_path / "fund_tail_backtest.csv"
    candidates = tmp_path / "candidates.csv"
    output = tmp_path / "fund_tail_opportunities.csv"
    markdown = tmp_path / "latest.md"

    pd.DataFrame(
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
            }
        ]
    ).to_csv(advice_report, index=False)
    candidates.write_text(
        "\n".join(
            [
                "fund_code,fund_name,fund_type,candidate_tier,proxy_provider,proxy_code,fee_tag,min_holding_days,enabled,tail_strategy_eligible,exclude_reason",
                "007995,华夏中证500指数增强C,broad_index,preferred,csindex,000905,低费率,7,true,true,",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/discover_fund_tail_opportunities.py",
            "--trade-date",
            "2026-06-22",
            "--advice-report",
            str(advice_report),
            "--candidate-file",
            str(candidates),
            "--report",
            str(output),
            "--markdown",
            str(markdown),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    rows = pd.read_csv(output, dtype={"基金代码": str})
    assert rows.iloc[0]["机会类型"] == "新开仓候选"
    assert rows.iloc[0]["机会建议"] == "可小额新开仓"
    assert "# 基金尾盘机会发现 - 2026-06-22" in markdown.read_text(encoding="utf-8")
