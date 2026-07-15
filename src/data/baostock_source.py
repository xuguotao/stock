"""Baostock adapter for explicit historical daily-bar verification."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import pandas as pd


DAILY_FIELDS = "date,open,high,low,close,volume,amount,tradestatus,isST"


class BaostockQueryError(RuntimeError):
    """Raised when the Baostock session or query cannot complete."""


class BaostockSource:
    def __init__(
        self,
        *,
        login_fn: Callable[[], Any] | None = None,
        logout_fn: Callable[[], Any] | None = None,
        query_fn: Callable[..., Any] | None = None,
    ) -> None:
        if login_fn is None or logout_fn is None or query_fn is None:
            try:
                import baostock as bs
            except ModuleNotFoundError as exc:
                raise RuntimeError("baostock is not installed; run uv sync --extra market") from exc
            login_fn = login_fn or bs.login
            logout_fn = logout_fn or bs.logout
            query_fn = query_fn or bs.query_history_k_data_plus
        self._login_fn = login_fn
        self._logout_fn = logout_fn
        self._query_fn = query_fn

    def fetch_daily_bars(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        if end_date < start_date:
            raise ValueError("end_date must not be earlier than start_date")
        login = self._login_fn()
        _raise_for_error(login, "login")
        try:
            result = self._query_fn(
                code=_to_baostock_symbol(symbol),
                fields=DAILY_FIELDS,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            _raise_for_error(result, "query_history_k_data_plus")
            return _normalize_daily_bars(result, symbol)
        finally:
            self._logout_fn()


def _to_baostock_symbol(symbol: str) -> str:
    code, _, market = symbol.strip().upper().partition(".")
    if len(code) != 6 or market not in {"SH", "SZ"}:
        raise ValueError(f"unsupported A-share symbol: {symbol}")
    return f"{market.lower()}.{code}"


def _raise_for_error(result: Any, operation: str) -> None:
    error_code = str(getattr(result, "error_code", ""))
    if error_code == "0":
        return
    error_message = str(getattr(result, "error_msg", "unknown error"))
    raise BaostockQueryError(f"baostock {operation} failed ({error_code}): {error_message}")


def _normalize_daily_bars(result: Any, symbol: str) -> pd.DataFrame:
    fields = [str(field) for field in getattr(result, "fields", [])]
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    frame = pd.DataFrame(rows, columns=fields)
    if frame.empty:
        return pd.DataFrame(columns=[*DAILY_FIELDS.split(","), "symbol"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    for field in ("open", "high", "low", "close", "amount"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    for field in ("volume", "tradestatus", "isST"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce").fillna(0).astype(int)
    frame["symbol"] = symbol
    return frame[[*DAILY_FIELDS.split(","), "symbol"]]
