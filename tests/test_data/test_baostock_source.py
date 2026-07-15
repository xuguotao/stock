from __future__ import annotations

from datetime import date

import pytest

from src.data.baostock_source import BaostockQueryError, BaostockSource


class FakeResult:
    def __init__(self, *, error_code: str = "0", error_msg: str = "success", fields=None, rows=None) -> None:
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = fields or []
        self._rows = rows or []
        self._index = 0

    def next(self) -> bool:
        return self._index < len(self._rows)

    def get_row_data(self) -> list[str]:
        row = self._rows[self._index]
        self._index += 1
        return row


def test_fetch_daily_bars_maps_symbol_and_normalizes_values() -> None:
    login_calls = []
    logout_calls = []
    query_calls = []

    def query(**kwargs):
        query_calls.append(kwargs)
        return FakeResult(
            fields=["date", "open", "high", "low", "close", "volume", "amount", "tradestatus", "isST"],
            rows=[["2026-06-24", "10.1", "10.8", "10.0", "10.5", "100", "1234.5", "1", "0"]],
        )

    source = BaostockSource(
        login_fn=lambda: login_calls.append(True) or FakeResult(),
        logout_fn=lambda: logout_calls.append(True) or FakeResult(),
        query_fn=query,
    )

    frame = source.fetch_daily_bars("000524.SZ", date(2026, 6, 24), date(2026, 6, 24))

    assert login_calls == [True]
    assert logout_calls == [True]
    assert query_calls == [{
        "code": "sz.000524",
        "fields": "date,open,high,low,close,volume,amount,tradestatus,isST",
        "start_date": "2026-06-24",
        "end_date": "2026-06-24",
        "frequency": "d",
        "adjustflag": "3",
    }]
    assert frame.loc[0, "symbol"] == "000524.SZ"
    assert frame.loc[0, "date"] == date(2026, 6, 24)
    assert frame.loc[0, "amount"] == 1234.5
    assert frame.loc[0, "tradestatus"] == 1


def test_fetch_daily_bars_raises_when_query_fails() -> None:
    source = BaostockSource(
        login_fn=lambda: FakeResult(),
        logout_fn=lambda: FakeResult(),
        query_fn=lambda **_kwargs: FakeResult(error_code="10002007", error_msg="network error"),
    )

    with pytest.raises(BaostockQueryError, match="network error"):
        source.fetch_daily_bars("000524.SZ", date(2026, 6, 24), date(2026, 6, 24))
