from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_fund_tail_api_lists_universe_with_local_data_status(tmp_path) -> None:
    data_dir = tmp_path / "fund_tail"
    data_dir.mkdir()
    pd.DataFrame({"date": ["2026-06-10"], "close": [1.2]}).to_csv(
        data_dir / "001632_nav.csv",
        index=False,
    )
    pd.DataFrame({"date": ["2026-06-11"], "close": [100.0], "volume": [10]}).to_csv(
        data_dir / "001632_proxy.csv",
        index=False,
    )
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_data_dir=data_dir,
    )
    client = TestClient(app)

    response = client.get("/api/fund-tail/universe")

    assert response.status_code == 200
    first = next(item for item in response.json()["items"] if item["code"] == "001632")
    assert first["name"] == "天弘中证食品饮料ETF联接C"
    assert first["proxy_provider"] == "cni"
    assert first["has_nav"] is True
    assert first["has_proxy"] is True
    assert first["latest_nav_date"] == "2026-06-10"
    assert first["latest_proxy_date"] == "2026-06-11"


def test_fund_tail_api_loads_latest_report(tmp_path) -> None:
    report_path = tmp_path / "fund_tail_backtest.csv"
    markdown_path = tmp_path / "latest.md"
    pd.DataFrame(
        [
            {
                "基金名称": "天弘中证食品饮料ETF联接C",
                "基金代码": "001632",
                "今日代理涨跌率": "1.20%",
                "最终操作建议": "小额试探",
            }
        ]
    ).to_csv(report_path, index=False)
    markdown_path.write_text("# 基金尾盘操作建议\n", encoding="utf-8")
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_report_path=report_path,
        fund_tail_markdown_path=markdown_path,
    )
    client = TestClient(app)

    response = client.get("/api/fund-tail/report")

    assert response.status_code == 200
    assert response.json()["rows"][0]["基金代码"] == "001632"
    assert response.json()["markdown"] == "# 基金尾盘操作建议\n"


def test_fund_tail_api_runs_local_advice_job(tmp_path) -> None:
    data_dir = tmp_path / "fund_tail"
    data_dir.mkdir()
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    benchmark = pd.DataFrame({"date": dates, "close": range(100, 140)})
    benchmark.to_csv(data_dir / "benchmark.csv", index=False)
    for code in ["001632", "017437", "007995", "005827"]:
        nav = pd.DataFrame({"date": dates, "close": [1 + index * 0.01 for index in range(40)]})
        proxy = pd.DataFrame({"date": dates, "close": [100 + index for index in range(40)]})
        nav.to_csv(data_dir / f"{code}_nav.csv", index=False)
        proxy.to_csv(data_dir / f"{code}_proxy.csv", index=False)
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_data_dir=data_dir,
        fund_tail_report_path=tmp_path / "fund_tail_backtest.csv",
        fund_tail_raw_report_path=tmp_path / "fund_tail_backtest_raw.csv",
        fund_tail_advice_dir=tmp_path / "fund_tail_advice",
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/fund-tail/advice",
        json={
            "trade_date": "2026-02-09",
            "fund_codes": ["001632", "017437", "007995", "005827"],
        },
    )
    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["result"]["row_count"] == 4
    assert "# 基金尾盘操作建议 - 2026-02-09" in job["result"]["markdown"]
