"""ClickHouse repository for fund tail-session data."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.clickhouse_source import ClickHouseStockDataSource


class ClickHouseFundTailRepository:
    """Store and read fund NAV, proxy, and benchmark series from ClickHouse."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = ClickHouseStockDataSource()._client_instance()
        return self._client

    def ensure_tables(self) -> None:
        self.client.execute(
            """
            create table if not exists fund_tail_nav (
                fund_code String,
                fund_name String,
                date Date,
                close Float64,
                updated_at DateTime default now()
            )
            engine = ReplacingMergeTree(updated_at)
            order by (fund_code, date)
            """
        )
        self.client.execute(
            """
            create table if not exists fund_tail_proxy (
                fund_code String,
                proxy_provider String,
                proxy_code String,
                date Date,
                close Float64,
                volume Nullable(Float64),
                updated_at DateTime default now()
            )
            engine = ReplacingMergeTree(updated_at)
            order by (fund_code, date)
            """
        )
        self.client.execute(
            """
            create table if not exists fund_tail_benchmark (
                date Date,
                close Float64,
                volume Nullable(Float64),
                updated_at DateTime default now()
            )
            engine = ReplacingMergeTree(updated_at)
            order by date
            """
        )

    def ensure_watchlist_table(self) -> None:
        self.client.execute(
            """
            create table if not exists fund_watchlist (
                fund_code String,
                fund_name String,
                status String,
                priority String,
                fund_type String,
                enabled UInt8,
                include_in_advice UInt8,
                position_cost Nullable(Float64),
                position_amount Nullable(Float64),
                position_return_pct Nullable(Float64),
                note String,
                created_at DateTime default now(),
                updated_at DateTime default now()
            )
            engine = ReplacingMergeTree(updated_at)
            order by fund_code
            """
        )

    def list_watchlist(self) -> list[dict[str, Any]]:
        self.ensure_watchlist_table()
        rows = self.client.execute(
            """
            select
                fund_code,
                fund_name,
                status,
                priority,
                fund_type,
                enabled,
                include_in_advice,
                position_cost,
                position_amount,
                position_return_pct,
                note
            from fund_watchlist final
            order by fund_code
            """
        )
        return [_watchlist_row(row) for row in rows]

    def upsert_watchlist_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.ensure_watchlist_table()
        row = (
            str(item["fund_code"]).zfill(6),
            str(item["fund_name"]),
            str(item.get("status") or "watching"),
            str(item.get("priority") or "normal"),
            str(item.get("fund_type") or "other"),
            1 if bool(item.get("enabled", True)) else 0,
            1 if bool(item.get("include_in_advice", True)) else 0,
            _float_or_none(item.get("position_cost")),
            _float_or_none(item.get("position_amount")),
            _float_or_none(item.get("position_return_pct")),
            str(item.get("note") or ""),
        )
        self.client.execute(
            """
            insert into fund_watchlist (
                fund_code,
                fund_name,
                status,
                priority,
                fund_type,
                enabled,
                include_in_advice,
                position_cost,
                position_amount,
                position_return_pct,
                note
            ) values
            """,
            [row],
        )
        return _watchlist_row(row)

    def delete_watchlist_item(self, fund_code: str) -> dict[str, int]:
        self.ensure_watchlist_table()
        self.client.execute(
            "delete from fund_watchlist where fund_code = %(fund_code)s",
            {"fund_code": str(fund_code).zfill(6)},
        )
        return {"deleted": 1}

    def seed_watchlist_from_static_funds(
        self,
        fund_names: dict[str, str],
        proxy_specs: dict[str, tuple[Any, ...]] | None = None,
    ) -> dict[str, int]:
        self.ensure_watchlist_table()
        count = self.client.execute("select count() from fund_watchlist")
        existing_count = int(count[0][0]) if count else 0
        if existing_count > 0:
            return {"inserted": 0}
        inserted = 0
        proxy_specs = proxy_specs or {}
        for code, name in fund_names.items():
            self.upsert_watchlist_item({
                "fund_code": code,
                "fund_name": name,
                "status": "watching",
                "priority": "normal",
                "fund_type": _fund_type_from_proxy(code, proxy_specs),
                "enabled": True,
                "include_in_advice": True,
                "position_cost": None,
                "position_amount": None,
                "position_return_pct": None,
                "note": "",
            })
            inserted += 1
        return {"inserted": inserted}

    def advice_fund_codes_from_watchlist(self) -> list[str]:
        return [
            row["fund_code"]
            for row in self.list_watchlist()
            if row["enabled"] and row["include_in_advice"] and row["status"] != "paused"
        ]

    def import_csv_directory(
        self,
        data_dir: str | Path,
        *,
        fund_names: dict[str, str],
        proxy_specs: dict[str, tuple[Any, ...]] | None = None,
    ) -> dict[str, int]:
        """Import local CSV files into ClickHouse fund-tail tables."""
        self.ensure_tables()
        root = Path(data_dir)
        proxy_specs = proxy_specs or {}
        nav_rows: list[tuple[Any, ...]] = []
        proxy_rows: list[tuple[Any, ...]] = []
        benchmark_rows: list[tuple[Any, ...]] = []

        for code, name in fund_names.items():
            nav_path = root / f"{code}_nav.csv"
            if nav_path.exists():
                nav_rows.extend(
                    (code, name, row["date"], float(row["close"]))
                    for row in _read_series_csv(nav_path).to_dict(orient="records")
                )
            proxy_path = root / f"{code}_proxy.csv"
            if proxy_path.exists():
                provider, proxy_code = _proxy_identity(code, proxy_specs)
                proxy_rows.extend(
                    (
                        code,
                        provider,
                        proxy_code,
                        row["date"],
                        float(row["close"]),
                        _float_or_none(row.get("volume")),
                    )
                    for row in _read_series_csv(proxy_path).to_dict(orient="records")
                )

        benchmark_path = root / "benchmark.csv"
        if benchmark_path.exists():
            benchmark_rows.extend(
                (row["date"], float(row["close"]), _float_or_none(row.get("volume")))
                for row in _read_series_csv(benchmark_path).to_dict(orient="records")
            )

        if nav_rows:
            self.client.execute(
                "insert into fund_tail_nav (fund_code, fund_name, date, close) values",
                nav_rows,
            )
        if proxy_rows:
            self.client.execute(
                "insert into fund_tail_proxy (fund_code, proxy_provider, proxy_code, date, close, volume) values",
                proxy_rows,
            )
        if benchmark_rows:
            self.client.execute(
                "insert into fund_tail_benchmark (date, close, volume) values",
                benchmark_rows,
            )
        return {
            "nav_rows": len(nav_rows),
            "proxy_rows": len(proxy_rows),
            "benchmark_rows": len(benchmark_rows),
        }

    def list_universe(
        self,
        fund_names: dict[str, str],
        *,
        proxy_specs: dict[str, tuple[Any, ...]] | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_tables()
        proxy_specs = proxy_specs or {}
        nav_dates = {
            str(code): _date_string(latest)
            for code, _name, latest in self.client.execute(
                """
                select fund_code, any(fund_name), max(date)
                from fund_tail_nav
                group by fund_code
                """
            )
        }
        proxy_dates = {
            str(code): _date_string(latest)
            for code, _provider, _proxy_code, latest in self.client.execute(
                """
                select fund_code, any(proxy_provider), any(proxy_code), max(date)
                from fund_tail_proxy
                group by fund_code
                """
            )
        }
        items = []
        for code, name in fund_names.items():
            provider, proxy_code = _proxy_identity(code, proxy_specs)
            items.append(
                {
                    "code": code,
                    "name": name,
                    "proxy_provider": provider,
                    "proxy_code": proxy_code,
                    "has_nav": code in nav_dates,
                    "has_proxy": code in proxy_dates,
                    "latest_nav_date": nav_dates.get(code),
                    "latest_proxy_date": proxy_dates.get(code),
                }
            )
        return items

    def read_nav(self, fund_code: str) -> pd.DataFrame:
        self.ensure_tables()
        rows = self.client.execute(
            """
            select date, close
            from fund_tail_nav
            where fund_code = %(fund_code)s
            order by date
            """,
            {"fund_code": fund_code},
        )
        return _series_frame(rows, ["date", "close"])

    def read_proxy(self, fund_code: str) -> pd.DataFrame:
        self.ensure_tables()
        rows = self.client.execute(
            """
            select date, close, volume
            from fund_tail_proxy
            where fund_code = %(fund_code)s
            order by date
            """,
            {"fund_code": fund_code},
        )
        return _series_frame(rows, ["date", "close", "volume"])

    def read_benchmark(self) -> pd.DataFrame | None:
        self.ensure_tables()
        rows = self.client.execute(
            """
            select date, close, volume
            from fund_tail_benchmark
            order by date
            """
        )
        if not rows:
            return None
        return _series_frame(rows, ["date", "close", "volume"])


def _read_series_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df or "close" not in df:
        raise ValueError(f"missing required columns in {path}")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.date
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    if "volume" in result:
        result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
    return result.dropna(subset=["date", "close"])


def _series_frame(rows: list[tuple[Any, ...]], columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "volume" in df:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df


def _proxy_identity(code: str, proxy_specs: dict[str, tuple[Any, ...]]) -> tuple[str, str]:
    spec = proxy_specs.get(code)
    if not spec:
        return "nav", code
    return str(spec[0]), str(spec[1])


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _date_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _watchlist_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "fund_code": str(row[0]).zfill(6),
        "fund_name": str(row[1]),
        "status": str(row[2]),
        "priority": str(row[3]),
        "fund_type": str(row[4]),
        "enabled": bool(row[5]),
        "include_in_advice": bool(row[6]),
        "position_cost": _float_or_none(row[7]),
        "position_amount": _float_or_none(row[8]),
        "position_return_pct": _float_or_none(row[9]),
        "note": str(row[10] or ""),
    }


def _fund_type_from_proxy(code: str, proxy_specs: dict[str, tuple[Any, ...]]) -> str:
    spec = proxy_specs.get(code)
    if not spec:
        return "other"
    provider = str(spec[0])
    proxy_code = str(spec[1])
    if provider == "us_sina":
        return "overseas"
    if proxy_code in {"000300", "000905", "399330", "110020"}:
        return "broad_index"
    if proxy_code in {"399396", "930653", "931152"}:
        return "consumer"
    if proxy_code in {"399989", "930641"}:
        return "medical"
    if "债" in str(spec):
        return "bond"
    return "sector"
