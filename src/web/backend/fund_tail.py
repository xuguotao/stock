"""Fund tail-session advice API helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from scripts.backtest_fund_tail_advice import FUNDS, PROXY_INDEXES, download_inputs, proxy_info_for
from scripts.daily_fund_tail_advice import build_markdown_report
from src.research.fund_tail_backtest import (
    classify_tail_signals,
    evaluate_forward_returns,
    evaluate_latest_condition,
    evaluate_proxy_fit,
    evaluate_prediction_profile,
    summarize_latest_signal,
    to_chinese_report,
)

FundTailDownloader = Callable[[Path, str, str], None]
FundTailProxyRefresher = Callable[..., dict[str, Any]]
ProgressCallback = Callable[[int, str, str], None]


class FundTailAdviceRequest(BaseModel):
    """Request body for local fund-tail advice jobs."""

    trade_date: date
    fund_codes: list[str] | None = Field(default=None)
    refresh_data: bool = Field(default=True)
    download_start_date: date = Field(default=date(2025, 1, 1))


class FundWatchlistItemRequest(BaseModel):
    """Manual fund watchlist item managed from the dashboard."""

    fund_code: str = Field(min_length=1)
    fund_name: str = Field(min_length=1)
    status: str = "watching"
    priority: str = "normal"
    fund_type: str = "other"
    enabled: bool = True
    include_in_advice: bool = True
    position_cost: float | None = None
    position_amount: float | None = None
    position_return_pct: float | None = None
    note: str = ""

    @field_validator("fund_code")
    @classmethod
    def validate_fund_code(cls, value: str) -> str:
        code = value.strip().zfill(6)
        if not code.isdigit() or len(code) != 6:
            raise ValueError("基金代码需为 6 位数字")
        return code

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"holding", "candidate", "watching", "paused"}
        if value not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        allowed = {"core", "normal", "low"}
        if value not in allowed:
            raise ValueError(f"priority must be one of {sorted(allowed)}")
        return value

    @field_validator("fund_type")
    @classmethod
    def validate_fund_type(cls, value: str) -> str:
        allowed = {"broad_index", "consumer", "medical", "overseas", "bond", "sector", "other"}
        if value not in allowed:
            raise ValueError(f"fund_type must be one of {sorted(allowed)}")
        return value


@dataclass(frozen=True)
class FundTailPaths:
    """Configured local paths used by fund-tail dashboard features."""

    data_dir: Path = Path("data/fund_tail")
    report_path: Path = Path("reports/fund_tail_backtest.csv")
    raw_report_path: Path = Path("reports/fund_tail_backtest_raw.csv")
    advice_dir: Path = Path("reports/fund_tail_advice")
    markdown_path: Path = Path("reports/fund_tail_advice/latest.md")


def list_fund_universe(data_dir: str | Path) -> list[dict[str, Any]]:
    """Return configured fund universe plus local CSV availability."""
    root = Path(data_dir)
    items = []
    for code, name in FUNDS.items():
        proxy = PROXY_INDEXES.get(code)
        nav_path = root / f"{code}_nav.csv"
        proxy_path = root / f"{code}_proxy.csv"
        items.append(
            {
                "code": code,
                "name": name,
                "proxy_provider": proxy[0] if proxy else "nav",
                "proxy_code": proxy[1] if proxy else code,
                "has_nav": nav_path.exists(),
                "has_proxy": proxy_path.exists(),
                "latest_nav_date": _latest_csv_date(nav_path),
                "latest_proxy_date": _latest_csv_date(proxy_path),
            }
        )
    return items


def list_fund_universe_from_repository(repository) -> list[dict[str, Any]]:
    """Return configured fund universe plus ClickHouse availability."""
    return repository.list_universe(FUNDS, proxy_specs=PROXY_INDEXES)


def list_fund_watchlist(repository) -> list[dict[str, Any]]:
    """Return editable fund watchlist, seeding from static funds when empty."""
    repository.seed_watchlist_from_static_funds(FUNDS, proxy_specs=PROXY_INDEXES)
    return repository.list_watchlist()


def upsert_fund_watchlist_item(repository, request: FundWatchlistItemRequest) -> dict[str, Any]:
    """Create or update a fund watchlist item."""
    return repository.upsert_watchlist_item(request.model_dump())


def delete_fund_watchlist_item(repository, fund_code: str) -> dict[str, int]:
    """Delete a fund watchlist item."""
    code = FundWatchlistItemRequest.validate_fund_code(fund_code)
    return repository.delete_watchlist_item(code)


def load_latest_fund_tail_report(
    report_path: str | Path,
    markdown_path: str | Path,
    repository=None,
) -> dict[str, Any]:
    """Load the latest Chinese CSV and Markdown advice report."""
    if repository is not None:
        persisted = repository.load_latest_advice_report()
        if persisted is not None:
            return persisted
    report = Path(report_path)
    markdown = Path(markdown_path)
    rows: list[dict[str, Any]] = []
    if report.exists():
        rows = pd.read_csv(report, dtype={"基金代码": str}).fillna("").to_dict(orient="records")
    return {
        "rows": rows,
        "markdown": markdown.read_text(encoding="utf-8") if markdown.exists() else "",
        "report_path": str(report),
        "markdown_path": str(markdown),
        "report_updated_at": _path_updated_at(report),
        "markdown_updated_at": _path_updated_at(markdown),
    }


def run_local_fund_tail_advice(
    paths: FundTailPaths,
    request: FundTailAdviceRequest,
    *,
    downloader: FundTailDownloader = download_inputs,
    proxy_refresher: FundTailProxyRefresher | None = None,
    repository=None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Generate fund-tail advice, optionally refreshing local CSV inputs first."""
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.advice_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)

    all_fund_names = _fund_names(repository)
    selected_funds = _selected_funds(request.fund_codes, repository=repository, fund_names=all_fund_names)
    proxy_refresh = None
    if request.refresh_data:
        if proxy_refresher is not None and repository is not None:
            _report_progress(progress, 20, "refreshing_proxy", "刷新基金代理行情")
            proxy_refresh = proxy_refresher(
                repository=repository,
                fund_codes=list(selected_funds),
                trade_date=request.trade_date,
            )
        else:
            _report_progress(progress, 20, "refreshing_data", "刷新基金净值和代理指数数据")
            downloader(
                paths.data_dir,
                request.download_start_date.strftime("%Y%m%d"),
                request.trade_date.strftime("%Y%m%d"),
            )

    import_result = None
    if repository is not None and proxy_refresh is None:
        _report_progress(progress, 40, "importing_clickhouse", "导入基金尾盘数据到 ClickHouse")
        import_result = repository.import_csv_directory(
            paths.data_dir,
            fund_names=all_fund_names,
            proxy_specs=PROXY_INDEXES,
        )

    _report_progress(progress, 55, "analyzing_signals", "计算基金尾盘信号")
    benchmark_path = paths.data_dir / "benchmark.csv"
    benchmark = _read_benchmark(paths, repository)
    rows = []
    for code, name in selected_funds.items():
        proxy = _read_proxy(paths, code, repository)
        nav = _read_nav(paths, code, repository, proxy)
        signals = classify_tail_signals(proxy, benchmark=benchmark)
        metrics = evaluate_forward_returns(signals, nav)
        condition = evaluate_latest_condition(signals, nav)
        prediction = evaluate_prediction_profile(signals, nav)
        proxy_fit = evaluate_proxy_fit(nav, proxy)
        rows.append(
            summarize_latest_signal(
                name,
                code,
                signals,
                metrics,
                condition,
                prediction,
                proxy_info_for(code),
                proxy_fit,
            )
        )

    _report_progress(progress, 85, "writing_report", "写入基金尾盘报告")
    report = pd.DataFrame(rows)
    report.to_csv(paths.raw_report_path, index=False)
    chinese_report = to_chinese_report(report)
    chinese_report.to_csv(paths.report_path, index=False)
    markdown = build_markdown_report(chinese_report, request.trade_date.isoformat())

    dated_path = paths.advice_dir / f"{request.trade_date.isoformat()}.md"
    dated_path.write_text(markdown, encoding="utf-8")
    paths.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    paths.markdown_path.write_text(markdown, encoding="utf-8")
    rows_for_api = chinese_report.fillna("").astype(str).to_dict(orient="records")
    data_status = _fund_data_status(paths.data_dir, selected_funds, repository=repository)
    saved_report = None
    metadata = {
        "storage": "clickhouse" if repository is not None else "csv",
        "data_refreshed": request.refresh_data,
        "row_count": int(len(chinese_report)),
        "import_result": import_result,
        "proxy_refresh": proxy_refresh,
    }
    if repository is not None:
        saved_report = repository.save_advice_report(
            trade_date=request.trade_date.isoformat(),
            rows=rows_for_api,
            markdown=markdown,
            data_status=data_status,
            metadata=metadata,
        )
    return {
        "row_count": int(len(chinese_report)),
        "rows": rows_for_api,
        "markdown": markdown,
        "data_refreshed": request.refresh_data,
        "storage": "clickhouse" if repository is not None else "csv",
        "import_result": import_result,
        "proxy_refresh": proxy_refresh,
        "saved_report": saved_report,
        "data_status": data_status,
        "report_path": str(paths.report_path),
        "raw_report_path": str(paths.raw_report_path),
        "markdown_path": str(dated_path),
        "report_updated_at": _path_updated_at(paths.report_path),
        "markdown_updated_at": _path_updated_at(dated_path),
    }


def _fund_names(repository=None) -> dict[str, str]:
    names = dict(FUNDS)
    if repository is None:
        return names
    repository.seed_watchlist_from_static_funds(FUNDS, proxy_specs=PROXY_INDEXES)
    for item in repository.list_watchlist():
        names[str(item["fund_code"]).zfill(6)] = str(item["fund_name"])
    return names


def _selected_funds(
    fund_codes: list[str] | None,
    repository=None,
    fund_names: dict[str, str] | None = None,
) -> dict[str, str]:
    available = fund_names or FUNDS
    if not fund_codes and repository is not None:
        repository.seed_watchlist_from_static_funds(FUNDS, proxy_specs=PROXY_INDEXES)
        fund_codes = repository.advice_fund_codes_from_watchlist()
    if not fund_codes:
        return dict(available)
    fund_codes = [str(code).zfill(6) for code in fund_codes]
    missing = [code for code in fund_codes if code not in available]
    if missing:
        raise ValueError(f"Unknown fund codes: {', '.join(missing)}")
    return {code: available[code] for code in fund_codes}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing input file: {path}")
    return pd.read_csv(path)


def _read_proxy(paths: FundTailPaths, code: str, repository) -> pd.DataFrame:
    if repository is not None:
        proxy = repository.read_proxy(code)
        if not proxy.empty:
            return proxy
    return _read_csv(paths.data_dir / f"{code}_proxy.csv")


def _read_nav(paths: FundTailPaths, code: str, repository, proxy: pd.DataFrame) -> pd.DataFrame:
    if repository is not None:
        nav = repository.read_nav(code)
        if not nav.empty:
            return nav
    nav_path = paths.data_dir / f"{code}_nav.csv"
    return _read_csv(nav_path) if nav_path.exists() else proxy


def _read_benchmark(paths: FundTailPaths, repository) -> pd.DataFrame | None:
    if repository is not None:
        benchmark = repository.read_benchmark()
        if benchmark is not None and not benchmark.empty:
            return benchmark
    benchmark_path = paths.data_dir / "benchmark.csv"
    return _read_csv(benchmark_path) if benchmark_path.exists() else None


def _latest_csv_date(path: Path) -> str | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=["date"])
    if df.empty:
        return None
    return str(df["date"].iloc[-1])[:10]


def _path_updated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _fund_data_status(data_dir: Path, selected_funds: dict[str, str], repository=None) -> list[dict[str, Any]]:
    if repository is not None:
        status_by_code = {
            item["code"]: item
            for item in repository.list_universe(selected_funds, proxy_specs=PROXY_INDEXES)
        }
        return [status_by_code[code] for code in selected_funds if code in status_by_code]
    rows = []
    for code, name in selected_funds.items():
        nav_path = data_dir / f"{code}_nav.csv"
        proxy_path = data_dir / f"{code}_proxy.csv"
        rows.append(
            {
                "code": code,
                "name": name,
                "latest_nav_date": _latest_csv_date(nav_path),
                "latest_proxy_date": _latest_csv_date(proxy_path),
                "has_nav": nav_path.exists(),
                "has_proxy": proxy_path.exists(),
            }
        )
    return rows


def _report_progress(
    progress: ProgressCallback | None,
    percent: int,
    stage: str,
    message: str,
) -> None:
    if progress is not None:
        progress(percent, stage, message)
