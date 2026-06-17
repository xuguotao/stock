from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src.data.fund_tail_repository import ClickHouseFundTailRepository


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, object | None]] = []
        self.watchlist_rows: list[tuple] = []

    def execute(self, query, params=None):
        self.commands.append((query, params))
        normalized = " ".join(query.lower().split())
        if normalized.startswith("insert into fund_watchlist"):
            for row in params or []:
                self.watchlist_rows = [existing for existing in self.watchlist_rows if existing[0] != row[0]]
                self.watchlist_rows.append(row)
            return []
        if normalized.startswith("delete from fund_watchlist"):
            code = params["fund_code"]
            self.watchlist_rows = [row for row in self.watchlist_rows if row[0] != code]
            return []
        if "count()" in normalized and "from fund_watchlist" in normalized:
            return [(len(self.watchlist_rows),)]
        if "from fund_watchlist" in normalized:
            return self.watchlist_rows
        if "from fund_tail_nav" in normalized and "max(date)" in normalized:
            return [("001632", "天弘中证食品饮料ETF联接C", "2026-06-11")]
        if "from fund_tail_proxy" in normalized and "max(date)" in normalized:
            return [("001632", "cni", "399396", "2026-06-12")]
        if "from fund_tail_nav" in normalized:
            return [("2026-06-10", 1.2), ("2026-06-11", 1.21)]
        if "from fund_tail_proxy" in normalized:
            return [("2026-06-10", 100.0, 10.0), ("2026-06-12", 101.0, 12.0)]
        if "from fund_tail_benchmark" in normalized:
            return [("2026-06-10", 4000.0, 100.0)]
        return []


class ConcurrentSensitiveFakeClickHouseClient(FakeClickHouseClient):
    def __init__(self) -> None:
        super().__init__()
        self.active = False

    def execute(self, query, params=None):
        if self.active:
            raise RuntimeError("simultaneous execute")
        self.active = True
        try:
            time.sleep(0.01)
            return super().execute(query, params)
        finally:
            self.active = False


def test_import_csv_directory_writes_nav_proxy_and_benchmark_rows(tmp_path: Path) -> None:
    data_dir = tmp_path / "fund_tail"
    data_dir.mkdir()
    pd.DataFrame({"date": ["2026-06-11"], "close": [1.21]}).to_csv(data_dir / "001632_nav.csv", index=False)
    pd.DataFrame({"date": ["2026-06-12"], "close": [101.0], "volume": [12]}).to_csv(
        data_dir / "001632_proxy.csv",
        index=False,
    )
    pd.DataFrame({"date": ["2026-06-12"], "close": [4000.0]}).to_csv(data_dir / "benchmark.csv", index=False)
    client = FakeClickHouseClient()
    repo = ClickHouseFundTailRepository(client=client)

    result = repo.import_csv_directory(data_dir, fund_names={"001632": "天弘中证食品饮料ETF联接C"})

    assert result == {"nav_rows": 1, "proxy_rows": 1, "benchmark_rows": 1}
    inserts = [command for command in client.commands if command[0].lower().strip().startswith("insert into")]
    assert "insert into fund_tail_nav" in inserts[0][0].lower()
    assert "insert into fund_tail_proxy" in inserts[1][0].lower()
    assert "insert into fund_tail_benchmark" in inserts[2][0].lower()


def test_repository_reads_series_and_universe_status() -> None:
    repo = ClickHouseFundTailRepository(client=FakeClickHouseClient())

    universe = repo.list_universe({"001632": "天弘中证食品饮料ETF联接C"})
    nav = repo.read_nav("001632")
    proxy = repo.read_proxy("001632")
    benchmark = repo.read_benchmark()

    assert universe[0]["has_nav"] is True
    assert universe[0]["has_proxy"] is True
    assert universe[0]["latest_nav_date"] == "2026-06-11"
    assert universe[0]["latest_proxy_date"] == "2026-06-12"
    assert nav["close"].tolist() == [1.2, 1.21]
    assert proxy["volume"].tolist() == [10.0, 12.0]
    assert benchmark["close"].tolist() == [4000.0]


def test_repository_reads_final_rows_for_reimported_series() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseFundTailRepository(client=client)

    repo.read_nav("001632")
    repo.read_proxy("001632")
    repo.read_benchmark()

    read_queries = [
        " ".join(command[0].lower().split())
        for command in client.commands
        if command[0].lower().strip().startswith("select")
    ]
    assert any("from fund_tail_nav final" in query for query in read_queries)
    assert any("from fund_tail_proxy final" in query for query in read_queries)
    assert any("from fund_tail_benchmark final" in query for query in read_queries)


def test_repository_serializes_clickhouse_execute_calls() -> None:
    client = ConcurrentSensitiveFakeClickHouseClient()
    repo = ClickHouseFundTailRepository(client=client)

    def read_universe() -> list[dict]:
        return repo.list_universe({"001632": "天弘中证食品饮料ETF联接C"})

    def read_watchlist() -> list[dict]:
        return repo.list_watchlist()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda fn: fn(), [read_universe, read_watchlist]))

    assert results[0][0]["code"] == "001632"
    assert results[1] == []


def test_watchlist_crud_and_seed_from_static_funds() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseFundTailRepository(client=client)

    seeded = repo.seed_watchlist_from_static_funds({"001632": "天弘中证食品饮料ETF联接C"})
    assert seeded == {"inserted": 1}

    repo.upsert_watchlist_item({
        "fund_code": "001632",
        "fund_name": "天弘中证食品饮料ETF联接C",
        "status": "holding",
        "priority": "core",
        "fund_type": "consumer",
        "enabled": True,
        "include_in_advice": True,
        "position_cost": 1.23,
        "position_amount": 5000.0,
        "position_return_pct": -0.12,
        "note": "回踩再补",
    })

    rows = repo.list_watchlist()
    latest = rows[-1]
    assert latest["fund_code"] == "001632"
    assert latest["status"] == "holding"
    assert latest["priority"] == "core"
    assert latest["fund_type"] == "consumer"
    assert latest["enabled"] is True
    assert latest["include_in_advice"] is True
    assert latest["position_cost"] == 1.23
    assert latest["position_amount"] == 5000.0
    assert latest["position_return_pct"] == -0.12
    assert latest["note"] == "回踩再补"
    assert repo.advice_fund_codes_from_watchlist() == ["001632"]

    result = repo.delete_watchlist_item("001632")
    assert result == {"deleted": 1}
    assert any("delete from fund_watchlist" in command[0].lower() for command in client.commands)
