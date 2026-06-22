from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from src.web.backend.app import create_app


class FakeFundTailRepository:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.import_calls = []
        self.watchlist_items = [
            {
                "fund_code": "001632",
                "fund_name": "天弘中证食品饮料ETF联接C",
                "status": "watching",
                "priority": "normal",
                "fund_type": "consumer",
                "enabled": True,
                "include_in_advice": True,
                "position_cost": None,
                "position_amount": None,
                "position_return_pct": None,
                "note": "",
            }
        ]

    def import_csv_directory(self, data_dir, *, fund_names, proxy_specs=None):
        self.import_calls.append((data_dir, fund_names, proxy_specs))
        return {"nav_rows": 1, "proxy_rows": 1, "benchmark_rows": 1}

    def list_universe(self, fund_names, *, proxy_specs=None):
        return [
            {
                "code": "001632",
                "name": fund_names["001632"],
                "proxy_provider": "cni",
                "proxy_code": "399396",
                "has_nav": True,
                "has_proxy": True,
                "latest_nav_date": "2026-06-11",
                "latest_proxy_date": "2026-06-12",
            }
        ]

    def read_nav(self, code):
        return pd.read_csv(self.data_dir / f"{code}_nav.csv")

    def read_proxy(self, code):
        return pd.read_csv(self.data_dir / f"{code}_proxy.csv")

    def read_benchmark(self):
        return pd.read_csv(self.data_dir / "benchmark.csv")

    def seed_watchlist_from_static_funds(self, fund_names, proxy_specs=None):
        return {"inserted": 0}

    def list_watchlist(self):
        return list(self.watchlist_items)

    def upsert_watchlist_item(self, item):
        normalized = {"fund_code": item["fund_code"], **item}
        self.watchlist_items = [
            existing for existing in self.watchlist_items
            if existing["fund_code"] != normalized["fund_code"]
        ]
        self.watchlist_items.append(normalized)
        return normalized

    def delete_watchlist_item(self, fund_code):
        self.watchlist_items = [
            existing for existing in self.watchlist_items
            if existing["fund_code"] != fund_code
        ]
        return {"deleted": 1}

    def advice_fund_codes_from_watchlist(self):
        return [
            item["fund_code"]
            for item in self.watchlist_items
            if item["enabled"] and item["include_in_advice"] and item["status"] != "paused"
        ]


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
        fund_tail_repository=FakeFundTailRepository(data_dir),
    )
    client = TestClient(app)

    response = client.get("/api/fund-tail/universe")

    assert response.status_code == 200
    first = next(item for item in response.json()["items"] if item["code"] == "001632")
    assert first["name"] == "天弘中证食品饮料ETF联接C"
    assert first["proxy_provider"] == "cni"
    assert first["has_nav"] is True
    assert first["has_proxy"] is True
    assert first["latest_nav_date"] == "2026-06-11"
    assert first["latest_proxy_date"] == "2026-06-12"


def test_fund_tail_watchlist_api_lists_and_updates_items(tmp_path) -> None:
    data_dir = tmp_path / "fund_tail"
    data_dir.mkdir()
    repository = FakeFundTailRepository(data_dir)
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_repository=repository,
    )
    client = TestClient(app)

    response = client.get("/api/fund-tail/watchlist")
    assert response.status_code == 200
    assert response.json()["items"][0]["fund_code"] == "001632"

    payload = {
        "fund_code": "001632",
        "fund_name": "天弘中证食品饮料ETF联接C",
        "status": "holding",
        "priority": "core",
        "fund_type": "consumer",
        "enabled": True,
        "include_in_advice": True,
        "position_cost": 1.23,
        "position_amount": 5000,
        "position_return_pct": -0.12,
        "note": "回踩再补",
    }
    put_response = client.put("/api/fund-tail/watchlist/001632", json=payload)
    assert put_response.status_code == 200
    assert put_response.json()["item"]["status"] == "holding"
    assert put_response.json()["item"]["priority"] == "core"

    delete_response = client.delete("/api/fund-tail/watchlist/001632")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": 1}


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
    assert response.json()["report_updated_at"]


def test_fund_tail_api_loads_latest_opportunities(tmp_path) -> None:
    report_path = tmp_path / "fund_tail_opportunities.csv"
    markdown_path = tmp_path / "opportunities.md"
    pd.DataFrame(
        [
            {
                "基金名称": "华夏中证500指数增强C",
                "基金代码": "007995",
                "机会类型": "新开仓候选",
                "机会建议": "可小额新开仓",
            }
        ]
    ).to_csv(report_path, index=False)
    markdown_path.write_text("# 基金尾盘机会发现\n", encoding="utf-8")
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_opportunity_report_path=report_path,
        fund_tail_opportunity_markdown_path=markdown_path,
    )
    client = TestClient(app)

    response = client.get("/api/fund-tail/opportunities/latest")

    assert response.status_code == 200
    assert response.json()["rows"][0]["基金代码"] == "007995"
    assert response.json()["markdown"] == "# 基金尾盘机会发现\n"
    assert response.json()["report_updated_at"]


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
        fund_tail_repository=FakeFundTailRepository(data_dir),
    )
    client = TestClient(app)

    response = client.post(
        "/api/fund-tail/advice",
        json={
            "trade_date": "2026-02-09",
            "fund_codes": ["001632", "017437", "007995", "005827"],
            "refresh_data": False,
        },
    )
    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["result"]["row_count"] == 4
    assert "# 基金尾盘操作建议 - 2026-02-09" in job["result"]["markdown"]
    assert job["result"]["storage"] == "clickhouse"


def test_fund_tail_api_runs_opportunity_discovery_job(tmp_path) -> None:
    advice_report = tmp_path / "fund_tail_backtest.csv"
    candidates = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {
                "基金代码": "000311",
                "基金名称": "景顺长城沪深300增强A",
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
                "000311,景顺长城沪深300增强A,broad_index,preferred,csindex,000300,低费率,7,true,true,",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_report_path=advice_report,
        fund_tail_opportunity_candidate_path=candidates,
        fund_tail_opportunity_report_path=tmp_path / "opportunities.csv",
        fund_tail_opportunity_markdown_path=tmp_path / "opportunities.md",
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/fund-tail/opportunities",
        json={"trade_date": "2026-06-22"},
    )
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["result"]["rows"][0]["机会类型"] == "新开仓候选"
    assert job["result"]["rows"][0]["机会建议"] == "可小额新开仓"


def test_fund_tail_advice_uses_watchlist_when_codes_are_omitted(tmp_path) -> None:
    data_dir = tmp_path / "fund_tail"
    data_dir.mkdir()
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    pd.DataFrame({"date": dates, "close": range(100, 140)}).to_csv(data_dir / "benchmark.csv", index=False)
    for code in ["001632", "017437"]:
        nav = pd.DataFrame({"date": dates, "close": [1 + index * 0.01 for index in range(40)]})
        proxy = pd.DataFrame({"date": dates, "close": [100 + index for index in range(40)]})
        nav.to_csv(data_dir / f"{code}_nav.csv", index=False)
        proxy.to_csv(data_dir / f"{code}_proxy.csv", index=False)
    repository = FakeFundTailRepository(data_dir)
    repository.watchlist_items = [
        {
            "fund_code": "001632",
            "fund_name": "天弘中证食品饮料ETF联接C",
            "status": "holding",
            "priority": "core",
            "fund_type": "consumer",
            "enabled": True,
            "include_in_advice": True,
            "position_cost": None,
            "position_amount": None,
            "position_return_pct": None,
            "note": "",
        },
        {
            "fund_code": "017437",
            "fund_name": "华宝纳斯达克精选股票(QDII)C",
            "status": "paused",
            "priority": "normal",
            "fund_type": "overseas",
            "enabled": True,
            "include_in_advice": True,
            "position_cost": None,
            "position_amount": None,
            "position_return_pct": None,
            "note": "",
        },
    ]
    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_data_dir=data_dir,
        fund_tail_report_path=tmp_path / "fund_tail_backtest.csv",
        fund_tail_raw_report_path=tmp_path / "fund_tail_backtest_raw.csv",
        fund_tail_advice_dir=tmp_path / "fund_tail_advice",
        run_jobs_inline=True,
        fund_tail_repository=repository,
    )
    client = TestClient(app)

    response = client.post(
        "/api/fund-tail/advice",
        json={
            "trade_date": "2026-02-09",
            "refresh_data": False,
        },
    )
    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["result"]["row_count"] == 1
    assert job["result"]["rows"][0]["基金代码"] == "001632"


def test_fund_tail_advice_refreshes_inputs_and_returns_data_status(tmp_path) -> None:
    data_dir = tmp_path / "fund_tail"
    data_dir.mkdir()
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    pd.DataFrame({"date": dates, "close": range(100, 140)}).to_csv(
        data_dir / "benchmark.csv",
        index=False,
    )
    for code in ["001632"]:
        nav = pd.DataFrame({"date": dates, "close": [1 + index * 0.01 for index in range(40)]})
        proxy = pd.DataFrame({"date": dates, "close": [100 + index for index in range(40)]})
        nav.to_csv(data_dir / f"{code}_nav.csv", index=False)
        proxy.to_csv(data_dir / f"{code}_proxy.csv", index=False)

    def downloader(data_root, start_date, end_date):
        assert start_date == "20250101"
        assert end_date == "20260612"
        refreshed_nav = pd.DataFrame({"date": ["2026-06-11"], "close": [1.52]})
        refreshed_proxy = pd.DataFrame({"date": ["2026-06-12"], "close": [156.0]})
        refreshed_nav.to_csv(data_root / "001632_nav.csv", index=False)
        refreshed_proxy.to_csv(data_root / "001632_proxy.csv", index=False)
        pd.DataFrame({"date": ["2026-06-12"], "close": [4000.0]}).to_csv(
            data_root / "benchmark.csv",
            index=False,
        )

    app = create_app(
        db_path=tmp_path / "jobs.sqlite3",
        fund_tail_data_dir=data_dir,
        fund_tail_report_path=tmp_path / "fund_tail_backtest.csv",
        fund_tail_raw_report_path=tmp_path / "fund_tail_backtest_raw.csv",
        fund_tail_advice_dir=tmp_path / "fund_tail_advice",
        run_jobs_inline=True,
        fund_tail_downloader=downloader,
        fund_tail_repository=FakeFundTailRepository(data_dir),
    )
    client = TestClient(app)

    response = client.post(
        "/api/fund-tail/advice",
        json={
            "trade_date": "2026-06-12",
            "fund_codes": ["001632"],
            "refresh_data": True,
        },
    )
    payload = response.json()
    job = client.get(f"/api/jobs/{payload['job_id']}").json()

    assert response.status_code == 200
    assert job["status"] == "success"
    assert job["result"]["data_refreshed"] is True
    assert job["result"]["data_status"][0]["code"] == "001632"
    assert job["result"]["data_status"][0]["latest_nav_date"] == "2026-06-11"
    assert job["result"]["data_status"][0]["latest_proxy_date"] == "2026-06-12"
    assert job["result"]["import_result"] == {"nav_rows": 1, "proxy_rows": 1, "benchmark_rows": 1}
