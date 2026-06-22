"""Fast market data refresh for fund tail-session proxy series."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.data.tencent_source import TencentQuoteSource


def refresh_fund_tail_proxy_quotes(
    repository,
    *,
    fund_codes: list[str],
    proxy_specs: dict[str, tuple[Any, ...]],
    quote_source=None,
    trade_date: date,
) -> dict[str, Any]:
    """Refresh only the proxy quotes needed by the selected fund pool."""
    source = quote_source or TencentQuoteSource(rate_limit=0.0)
    symbol_map: dict[str, list[tuple[str, str, str]]] = {}
    skipped_funds = []
    for fund_code in fund_codes:
        spec = proxy_specs.get(str(fund_code).zfill(6))
        if not spec:
            skipped_funds.append(str(fund_code).zfill(6))
            continue
        provider, proxy_code, *realtime = spec
        symbol = _quote_symbol(str(proxy_code), realtime[0] if realtime else None)
        if symbol is None:
            skipped_funds.append(str(fund_code).zfill(6))
            continue
        symbol_map.setdefault(symbol, []).append((str(fund_code).zfill(6), str(provider), str(proxy_code)))

    benchmark_symbol = "000300.SH"
    symbols = list(symbol_map)
    if benchmark_symbol not in symbols:
        symbols.append(benchmark_symbol)
    quotes = source.fetch_realtime_quotes(symbols)
    quote_by_symbol = _quote_rows_by_symbol(quotes)

    proxy_rows = []
    missing_symbols = []
    for symbol, fund_specs in symbol_map.items():
        quote = quote_by_symbol.get(symbol)
        if quote is None:
            missing_symbols.append(symbol)
            continue
        for fund_code, provider, proxy_code in fund_specs:
            proxy_rows.append({
                "fund_code": fund_code,
                "proxy_provider": provider,
                "proxy_code": proxy_code,
                "date": trade_date,
                "close": float(quote["price"]),
                "volume": float(quote.get("volume") or 0.0),
                "source": source.name,
                "timestamp": str(quote.get("timestamp") or ""),
            })

    benchmark_rows = []
    benchmark_quote = quote_by_symbol.get(benchmark_symbol)
    if benchmark_quote is None:
        missing_symbols.append(benchmark_symbol)
    else:
        benchmark_rows.append({
            "date": trade_date,
            "close": float(benchmark_quote["price"]),
            "volume": float(benchmark_quote.get("volume") or 0.0),
            "source": source.name,
            "timestamp": str(benchmark_quote.get("timestamp") or ""),
        })

    proxy_result = repository.insert_proxy_quotes(proxy_rows)
    benchmark_result = repository.insert_benchmark_quotes(benchmark_rows)
    return {
        "source": source.name,
        "requested_symbols": symbols,
        "proxy_rows": int(proxy_result.get("proxy_rows", 0)),
        "benchmark_rows": int(benchmark_result.get("benchmark_rows", 0)),
        "missing_symbols": sorted(set(missing_symbols)),
        "skipped_funds": skipped_funds,
        "latest_timestamp": _latest_timestamp([*proxy_rows, *benchmark_rows]),
    }


def _quote_symbol(proxy_code: str, realtime_symbol: str | None) -> str | None:
    if realtime_symbol:
        lower = realtime_symbol.lower()
        if lower.startswith("sh"):
            return f"{realtime_symbol[2:].zfill(6)}.SH"
        if lower.startswith("sz"):
            return f"{realtime_symbol[2:].zfill(6)}.SZ"
        if lower.startswith("bj"):
            return f"{realtime_symbol[2:].zfill(6)}.BJ"
        # Tencent supports US quotes through symbols such as usQQQ, but those
        # use a different payload shape. Keep them as a later adapter instead
        # of pretending they are A-share proxy symbols.
        return None
    if not proxy_code.isdigit():
        return None
    code = proxy_code.zfill(6)
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _quote_rows_by_symbol(quotes: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if quotes is None or quotes.empty:
        return {}
    rows = {}
    for row in quotes.to_dict(orient="records"):
        symbol = str(row.get("symbol") or "")
        if symbol:
            rows[symbol] = row
    return rows


def _latest_timestamp(rows: list[dict[str, Any]]) -> str | None:
    timestamps = sorted(str(row.get("timestamp") or "") for row in rows if row.get("timestamp"))
    return timestamps[-1] if timestamps else None
