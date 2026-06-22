"""ClickHouse repository for fund tail-session data."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.data.clickhouse_source import ClickHouseStockDataSource


class ClickHouseFundTailRepository:
    """Store and read fund NAV, proxy, and benchmark series from ClickHouse."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._lock = RLock()

    @property
    def client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = ClickHouseStockDataSource()._client_instance()
            return self._client

    def _execute(self, query: str, params: Any | None = None) -> Any:
        # clickhouse-driver Client uses a single connection and is not safe for
        # simultaneous execute calls from FastAPI worker threads.
        with self._lock:
            if params is None:
                return self.client.execute(query)
            return self.client.execute(query, params)

    def ensure_tables(self) -> None:
        self._execute(
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
        self._execute(
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
        self._execute(
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
        self._execute(
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

    def ensure_advice_report_table(self) -> None:
        self._execute(
            """
            create table if not exists fund_tail_advice_runs (
                trade_date Date,
                rows_json String,
                markdown String,
                data_status_json String,
                metadata_json String,
                updated_at DateTime default now()
            )
            engine = ReplacingMergeTree(updated_at)
            order by (trade_date, updated_at)
            """
        )

    def list_watchlist(self) -> list[dict[str, Any]]:
        self.ensure_watchlist_table()
        rows = self._execute(
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
        items = [_watchlist_row(row) for row in rows]
        self._attach_watchlist_market_snapshot(items)
        return items

    def _attach_watchlist_market_snapshot(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        self.ensure_tables()
        codes = [item["fund_code"] for item in items]
        nav_rows = self._execute(
            """
            select
                fund_code,
                date,
                close
            from (
                select
                    fund_code,
                    date,
                    close,
                    row_number() over (partition by fund_code order by date desc) as rn
                from fund_tail_nav final
                where fund_code in %(codes)s
            )
            where rn = 1
            """,
            {"codes": tuple(codes)},
        )
        proxy_rows = self._execute(
            """
            select
                fund_code,
                date,
                close,
                prev_close,
                volume
            from (
                select
                    fund_code,
                    date,
                    close,
                    lagInFrame(close) over (
                        partition by fund_code
                        order by date
                        rows between unbounded preceding and unbounded following
                    ) as prev_close,
                    volume,
                    row_number() over (partition by fund_code order by date desc) as rn
                from fund_tail_proxy final
                where fund_code in %(codes)s
            )
            where rn = 1
            """,
            {"codes": tuple(codes)},
        )
        nav_by_code = {
            str(code): {"latest_nav_date": _date_string(day), "latest_nav": _float_or_none(close)}
            for code, day, close in nav_rows
        }
        proxy_by_code = {}
        for code, day, close, prev_close, volume in proxy_rows:
            latest = _float_or_none(close)
            previous = _float_or_none(prev_close)
            proxy_return = latest / previous - 1 if latest is not None and previous and previous > 0 else None
            proxy_by_code[str(code)] = {
                "latest_proxy_date": _date_string(day),
                "latest_proxy_close": latest,
                "proxy_prev_close": previous,
                "proxy_volume": _float_or_none(volume),
                "proxy_return_pct": proxy_return,
                "estimated_change_pct": proxy_return,
            }
        for item in items:
            item.update(nav_by_code.get(item["fund_code"], {
                "latest_nav_date": None,
                "latest_nav": None,
            }))
            item.update(proxy_by_code.get(item["fund_code"], {
                "latest_proxy_date": None,
                "latest_proxy_close": None,
                "proxy_prev_close": None,
                "proxy_volume": None,
                "proxy_return_pct": None,
                "estimated_change_pct": None,
            }))

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
        self._execute(
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
        self._execute(
            "delete from fund_watchlist where fund_code = %(fund_code)s",
            {"fund_code": str(fund_code).zfill(6)},
        )
        return {"deleted": 1}

    def save_advice_report(
        self,
        *,
        trade_date: str | date,
        rows: list[dict[str, Any]],
        markdown: str,
        data_status: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        """Persist a generated fund-tail advice report for dashboard/history use."""
        self.ensure_advice_report_table()
        row = (
            _date_value(trade_date),
            json.dumps(rows, ensure_ascii=False),
            markdown,
            json.dumps(data_status, ensure_ascii=False),
            json.dumps(metadata or {}, ensure_ascii=False),
        )
        self._execute(
            """
            insert into fund_tail_advice_runs (
                trade_date,
                rows_json,
                markdown,
                data_status_json,
                metadata_json
            ) values
            """,
            [row],
        )
        return {"saved": 1, "row_count": len(rows)}

    def load_latest_advice_report(self) -> dict[str, Any] | None:
        """Return the latest persisted advice report, if one exists."""
        self.ensure_advice_report_table()
        rows = self._execute(
            """
            select
                trade_date,
                rows_json,
                markdown,
                data_status_json,
                metadata_json,
                updated_at
            from fund_tail_advice_runs final
            order by updated_at desc
            limit 1
            """
        )
        if not rows:
            return None
        trade_date, rows_json, markdown, data_status_json, metadata_json, updated_at = rows[0]
        metadata = _json_object(metadata_json)
        updated_at_text = _datetime_string(updated_at)
        return {
            "rows": _json_list(rows_json),
            "markdown": str(markdown or ""),
            "data_status": _json_list(data_status_json),
            "data_refreshed": bool(metadata.get("data_refreshed", False)),
            "proxy_refresh": metadata.get("proxy_refresh"),
            "report_path": "clickhouse:fund_tail_advice_runs",
            "markdown_path": "clickhouse:fund_tail_advice_runs",
            "report_updated_at": updated_at_text,
            "markdown_updated_at": updated_at_text,
            "trade_date": _date_string(trade_date),
            "metadata": metadata,
        }

    def seed_watchlist_from_static_funds(
        self,
        fund_names: dict[str, str],
        proxy_specs: dict[str, tuple[Any, ...]] | None = None,
    ) -> dict[str, int]:
        self.ensure_watchlist_table()
        count = self._execute("select count() from fund_watchlist")
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
            self._execute(
                "insert into fund_tail_nav (fund_code, fund_name, date, close) values",
                nav_rows,
            )
        if proxy_rows:
            self._execute(
                "insert into fund_tail_proxy (fund_code, proxy_provider, proxy_code, date, close, volume) values",
                proxy_rows,
            )
        if benchmark_rows:
            self._execute(
                "insert into fund_tail_benchmark (date, close, volume) values",
                benchmark_rows,
            )
        return {
            "nav_rows": len(nav_rows),
            "proxy_rows": len(proxy_rows),
            "benchmark_rows": len(benchmark_rows),
        }

    def insert_proxy_quotes(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        """Append latest proxy quote rows produced by the fast quote refresher."""
        self.ensure_tables()
        values = [
            (
                str(row["fund_code"]).zfill(6),
                str(row["proxy_provider"]),
                str(row["proxy_code"]),
                _date_value(row["date"]),
                float(row["close"]),
                _float_or_none(row.get("volume")),
            )
            for row in rows
        ]
        if values:
            self._execute(
                "insert into fund_tail_proxy (fund_code, proxy_provider, proxy_code, date, close, volume) values",
                values,
            )
        return {"proxy_rows": len(values)}

    def insert_benchmark_quotes(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        """Append latest benchmark quote rows produced by the fast quote refresher."""
        self.ensure_tables()
        values = [
            (
                _date_value(row["date"]),
                float(row["close"]),
                _float_or_none(row.get("volume")),
            )
            for row in rows
        ]
        if values:
            self._execute(
                "insert into fund_tail_benchmark (date, close, volume) values",
                values,
            )
        return {"benchmark_rows": len(values)}

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
            for code, _name, latest in self._execute(
                """
                select fund_code, any(fund_name), max(date)
                from fund_tail_nav
                group by fund_code
                """
            )
        }
        proxy_dates = {
            str(code): _date_string(latest)
            for code, _provider, _proxy_code, latest in self._execute(
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
        rows = self._execute(
            """
            select date, close
            from fund_tail_nav final
            where fund_code = %(fund_code)s
            order by date
            """,
            {"fund_code": fund_code},
        )
        return _series_frame(rows, ["date", "close"])

    def read_proxy(self, fund_code: str) -> pd.DataFrame:
        self.ensure_tables()
        rows = self._execute(
            """
            select date, close, volume
            from fund_tail_proxy final
            where fund_code = %(fund_code)s
            order by date
            """,
            {"fund_code": fund_code},
        )
        return _series_frame(rows, ["date", "close", "volume"])

    def read_benchmark(self) -> pd.DataFrame | None:
        self.ensure_tables()
        rows = self._execute(
            """
            select date, close, volume
            from fund_tail_benchmark final
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


def _datetime_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        source = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return source.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None).isoformat(timespec="seconds")
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(timespec="seconds")
        except TypeError:
            return value.isoformat()
    return str(value)


def _date_value(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _json_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, dict) else {}


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
