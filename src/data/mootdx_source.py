"""mootdx data source adapter.

The adapter keeps mootdx optional and explicit. It normalizes the online
standard stock market APIs into this project's existing DataSource schemas.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import pandas as pd

from src.core.constants import format_symbol, is_st
from src.data.base import DataSourceBase
from src.data.models import FinancialStatement, StockInfo


MootdxFactory = Callable[..., Any]

MOOTDX_FREQUENCIES: dict[str, str | int] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1h",
    "1h": "1h",
    "daily": "day",
    "day": "day",
    "week": "week",
    "month": "mon",
}

_MARKET_SUFFIX = {0: "SZ", 1: "SH", 2: "BJ"}


class MootdxSource(DataSourceBase):
    """Online mootdx source for A-share quotes, stock lists, and K-lines."""

    name = "mootdx"

    def __init__(
        self,
        *,
        client: Any | None = None,
        quotes_factory: MootdxFactory | None = None,
        rate_limit: float = 0.2,
        bestip: bool = False,
        server: tuple[str, int] | None = None,
        timeout: int = 15,
        quiet: bool = True,
        verbose: int = 0,
        include_beijing: bool = False,
        default_offset: int = 800,
        affair_files_fetcher: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__(rate_limit=rate_limit)
        self._client = client
        self._quotes_factory = quotes_factory
        self._bestip = bestip
        self._server = server
        self._timeout = timeout
        self._quiet = quiet
        self._verbose = verbose
        self._include_beijing = include_beijing
        self._default_offset = default_offset
        self._affair_files_fetcher = affair_files_fetcher

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            if self._quotes_factory is None:
                from mootdx.quotes import Quotes

                factory = Quotes.factory
            else:
                factory = self._quotes_factory
            kwargs: dict[str, Any] = {
                "market": "std",
                "bestip": self._bestip,
                "timeout": self._timeout,
                "quiet": self._quiet,
                "verbose": self._verbose,
            }
            if self._server is not None:
                kwargs["server"] = self._server
            self._client = factory(**kwargs)
        except ModuleNotFoundError as exc:
            raise RuntimeError("mootdx is not installed; install the market extra with `uv sync --extra market`.") from exc
        return self._client

    def fetch_stock_list(self) -> list[StockInfo]:
        client = self._client_instance()
        markets = [0, 1, *([2] if self._include_beijing else [])]
        stocks: list[StockInfo] = []
        seen: set[str] = set()
        for market in markets:
            self._wait_for_rate_limit()
            frame = client.stocks(market=market)
            if frame is None or frame.empty or "code" not in frame.columns:
                continue
            for _, row in frame.iterrows():
                code = str(row.get("code") or "").zfill(6)
                if not code or not code.isdigit():
                    continue
                if not _is_supported_stock_code(code, market):
                    continue
                symbol = _symbol_for_market(code, market)
                if symbol in seen:
                    continue
                name = _clean_text(row.get("name"))
                seen.add(symbol)
                stocks.append(StockInfo(symbol=symbol, code=code, name=name, is_st=is_st(name)))
        return stocks

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        client = self._client_instance()
        self._wait_for_rate_limit()
        frame = client.quotes(symbol=[_code(symbol) for symbol in symbols])
        return normalize_mootdx_quotes(frame)

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        if frequency not in {"daily", "day"}:
            return pd.DataFrame()
        client = self._client_instance()
        self._wait_for_rate_limit()
        frame = client.bars(symbol=_code(symbol), frequency=MOOTDX_FREQUENCIES["daily"], start=0, offset=self._default_offset)
        normalized = normalize_mootdx_bars(frame, symbol)
        if normalized.empty:
            return normalized
        daily = pd.DataFrame({
            "date": normalized["datetime"].dt.date,
            "open": normalized["open"],
            "high": normalized["high"],
            "low": normalized["low"],
            "close": normalized["close"],
            "volume": normalized["volume"],
            "amount": normalized["amount"],
            "adjusted_close": normalized["close"],
            "symbol": normalized["symbol"],
        })
        mask = (daily["date"] >= start) & (daily["date"] <= end)
        return daily.loc[mask].sort_values("date").reset_index(drop=True)

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        mootdx_frequency = MOOTDX_FREQUENCIES.get(frequency)
        if mootdx_frequency is None or frequency in {"daily", "day", "week", "month"}:
            return pd.DataFrame()
        client = self._client_instance()
        self._wait_for_rate_limit()
        frame = client.bars(symbol=_code(symbol), frequency=mootdx_frequency, start=0, offset=self._default_offset)
        normalized = normalize_mootdx_bars(frame, symbol)
        if normalized.empty:
            return normalized
        mask = normalized["datetime"].dt.date == trade_date
        return normalized.loc[mask].reset_index(drop=True)

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        return []

    def fetch_minutes(self, symbol: str, trade_date: date) -> pd.DataFrame:
        client = self._client_instance()
        self._wait_for_rate_limit()
        return _safe_frame(client.minutes(symbol=_code(symbol), date=trade_date.strftime("%Y%m%d")))

    def fetch_realtime_minute(self, symbol: str) -> pd.DataFrame:
        client = self._client_instance()
        self._wait_for_rate_limit()
        return _safe_frame(client.minute(symbol=_code(symbol)))

    def fetch_transactions(self, symbol: str, trade_date: date | None = None, *, start: int = 0, offset: int = 800) -> pd.DataFrame:
        client = self._client_instance()
        self._wait_for_rate_limit()
        if trade_date is None:
            return _safe_frame(client.transaction(symbol=_code(symbol), start=start, offset=offset))
        return _safe_frame(client.transactions(symbol=_code(symbol), start=start, offset=offset, date=trade_date.strftime("%Y%m%d")))

    def fetch_xdxr(self, symbol: str) -> pd.DataFrame:
        client = self._client_instance()
        self._wait_for_rate_limit()
        return _safe_frame(client.xdxr(symbol=_code(symbol)))

    def fetch_finance_frame(self, symbol: str) -> pd.DataFrame:
        client = self._client_instance()
        self._wait_for_rate_limit()
        return _safe_frame(client.finance(symbol=_code(symbol)))

    def fetch_index_bars(self, symbol: str = "000001", frequency: str = "daily") -> pd.DataFrame:
        mootdx_frequency = MOOTDX_FREQUENCIES.get(frequency, frequency)
        client = self._client_instance()
        self._wait_for_rate_limit()
        return _safe_frame(client.index(symbol=_code(symbol), frequency=mootdx_frequency, start=0, offset=self._default_offset))

    def fetch_f10_catalog(self, symbol: str) -> pd.DataFrame:
        client = self._client_instance()
        self._wait_for_rate_limit()
        return _safe_frame(client.F10C(symbol=_code(symbol)))

    def fetch_f10_detail(self, symbol: str, title: str) -> str:
        client = self._client_instance()
        self._wait_for_rate_limit()
        value = client.F10(symbol=_code(symbol), name=title)
        return "" if value is None else str(value)

    def fetch_affair_files(self) -> list[dict[str, Any]]:
        if self._affair_files_fetcher is not None:
            return self._affair_files_fetcher()
        try:
            from mootdx.affair import Affair
        except ModuleNotFoundError as exc:
            raise RuntimeError("mootdx is not installed; install the market extra with `uv sync --extra market`.") from exc
        return list(Affair.files())


def normalize_mootdx_quotes(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty or "code" not in frame.columns:
        return pd.DataFrame()
    rows = []
    for _, row in frame.iterrows():
        code = str(row.get("code") or "").zfill(6)
        if not code or not code.isdigit():
            continue
        price = _float(row.get("price"))
        prev_close = _float(row.get("last_close"))
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
        rows.append({
            "symbol": _symbol_from_row(code, row),
            "price": price,
            "open": _float(row.get("open")),
            "prev_close": prev_close,
            "high": _float(row.get("high")),
            "low": _float(row.get("low")),
            "volume": int(_float(row.get("volume", row.get("vol")))),
            "amount": _float(row.get("amount")),
            "change_pct": change_pct,
            "timestamp": str(row.get("servertime") or ""),
        })
    return pd.DataFrame(rows)


def normalize_mootdx_bars(frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    source = frame.reset_index(drop=True).copy()
    if "datetime" not in source.columns and isinstance(frame.index, pd.DatetimeIndex):
        source["datetime"] = frame.index
    if "datetime" not in source.columns:
        return pd.DataFrame()
    datetimes = pd.to_datetime(source["datetime"], errors="coerce")
    source = source.loc[datetimes.notna()].copy()
    datetimes = datetimes.loc[datetimes.notna()]
    if source.empty:
        return pd.DataFrame()
    rows = pd.DataFrame({
        "datetime": datetimes.reset_index(drop=True),
        "symbol": format_symbol(symbol),
        "open": source["open"].map(_float).reset_index(drop=True),
        "high": source["high"].map(_float).reset_index(drop=True),
        "low": source["low"].map(_float).reset_index(drop=True),
        "close": source["close"].map(_float).reset_index(drop=True),
        "volume": source.get("volume", source.get("vol", pd.Series([0] * len(source)))).map(_float).astype(int).reset_index(drop=True),
        "amount": source.get("amount", pd.Series([0.0] * len(source))).map(_float).reset_index(drop=True),
    })
    rows["time"] = rows["datetime"].dt.time
    return rows[["datetime", "time", "symbol", "open", "high", "low", "close", "volume", "amount"]].sort_values("datetime").reset_index(drop=True)


def _safe_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    return pd.DataFrame()


def _code(symbol: str) -> str:
    return symbol.strip().upper().split(".", 1)[0].zfill(6)


def _symbol_for_market(code: str, market: int) -> str:
    suffix = _MARKET_SUFFIX.get(int(market))
    if suffix is None:
        return format_symbol(code)
    return f"{code.zfill(6)}.{suffix}"


def _symbol_from_row(code: str, row: pd.Series) -> str:
    market = row.get("market")
    if market is None or pd.isna(market):
        return format_symbol(code)
    try:
        return _symbol_for_market(code, int(market))
    except (TypeError, ValueError):
        return format_symbol(code)


def _is_supported_stock_code(code: str, market: int) -> bool:
    if market == 0:
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if market == 1:
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if market == 2:
        return code.startswith(("4", "8", "9"))
    return False


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()


def _float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
