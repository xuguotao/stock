"""Shared strategy universe resolution for ClickHouse-backed workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

from src.core.constants import format_symbol, is_st


@dataclass(frozen=True)
class StrategyUniverseOptions:
    """Filters that define a strategy-tradable stock universe."""

    trade_date: date
    lookback_start: date | None = None
    min_daily_bars: int = 60
    require_latest_daily: bool = True
    require_minute5: bool = False
    include_st: bool = False
    min_amount: float = 0.0
    markets: Sequence[str] = ("SH", "SZ")


@dataclass(frozen=True)
class StrategyUniverseRow:
    """One stock that passed the shared strategy universe filters."""

    symbol: str
    code: str
    name: str
    market: str
    bars: int
    latest_date: date | None
    avg_amount: float
    avg_volume: float
    has_minute5: bool


def resolve_strategy_universe(
    client: Any,
    options: StrategyUniverseOptions,
    *,
    symbols_only: bool = False,
) -> list[StrategyUniverseRow] | list[str]:
    """Resolve the strategy-tradable universe using one canonical filter set."""
    profile_symbols = _eligible_profile_symbols(client)
    rows = _daily_candidates(client, options, symbols=profile_symbols)
    minute5_codes = _minute5_codes(client, options, rows) if options.require_minute5 else set()
    result = []
    for row in rows:
        code, name, market, bars, latest_date, avg_amount, avg_volume = row
        if int(bars or 0) < options.min_daily_bars:
            continue
        if float(avg_amount or 0) <= options.min_amount:
            continue
        code_text = str(code).zfill(6)
        market_text = _market_for(code_text, str(market or ""))
        symbol = _format_symbol_with_market(code_text, market_text)
        stock_name = str(name or "")
        if options.markets and market_text not in _normalized_markets(options.markets):
            continue
        if not options.include_st and is_st(stock_name):
            continue
        if options.require_latest_daily and latest_date != options.trade_date:
            continue
        has_minute5 = code_text in minute5_codes or symbol in minute5_codes
        if options.require_minute5 and not has_minute5:
            continue
        result.append(
            StrategyUniverseRow(
                symbol=symbol,
                code=code_text,
                name=stock_name,
                market=market_text,
                bars=int(bars or 0),
                latest_date=latest_date,
                avg_amount=float(avg_amount or 0),
                avg_volume=float(avg_volume or 0),
                has_minute5=has_minute5,
            )
        )
    if symbols_only:
        return [row.symbol for row in result]
    return result


def _daily_candidates(client: Any, options: StrategyUniverseOptions, *, symbols: tuple[str, ...] | None = None) -> list[tuple]:
    start = options.lookback_start or (options.trade_date - timedelta(days=365))
    profile_filter = "and d.symbol in %(symbols)s" if symbols is not None else ""
    rows = client.execute(
        f"""
        select
            d.symbol as symbol,
            any(s.name) as name,
            any(s.market) as market,
            count() as bars,
            max(d.date) as latest_date,
            avg(d.amount) as avg_amount,
            avg(d.volume) as avg_volume
        from daily_kline d
        any left join stocks s on d.symbol = s.symbol
        where d.date >= %(start)s and d.date <= %(end)s
            and d.volume > 0
            and d.amount > %(min_amount)s
            and d.open > 0
            and d.high > 0
            and d.low > 0
            and d.close > 0
            {profile_filter}
        group by d.symbol
        having bars >= %(min_daily_bars)s
        order by avg_amount desc, avg_volume desc, d.symbol asc
        """,
        {
            "start": start,
            "end": options.trade_date,
            "min_amount": options.min_amount,
            "min_daily_bars": options.min_daily_bars,
            **({"symbols": symbols} if symbols is not None else {}),
        },
    )
    return list(rows)


def _eligible_profile_symbols(client: Any) -> tuple[str, ...] | None:
    """Use the shared profile when present; tolerate databases not migrated yet."""
    try:
        rows = client.execute("select symbol from stock_universe_profiles final where universe_eligible = 1 order by symbol")
    except Exception:  # noqa: BLE001 - profile migration must not block live strategy execution.
        return None
    return tuple(str(row[0]).split(".", 1)[0].zfill(6) for row in rows) or None


def _minute5_codes(
    client: Any,
    options: StrategyUniverseOptions,
    candidates: list[tuple],
) -> set[str]:
    codes = tuple(str(row[0]).zfill(6) for row in candidates)
    if not codes:
        return set()
    rows = client.execute(
        """
        select distinct symbol
        from minute5_kline
        where toDate(datetime) = %(trade_date)s
            and symbol in %(symbols)s
        """,
        {"trade_date": options.trade_date, "symbols": codes},
    )
    result = set()
    for (symbol,) in rows:
        text = str(symbol)
        result.add(text.zfill(6) if "." not in text else format_symbol(text))
    return result


def _normalized_markets(markets: Sequence[str]) -> set[str]:
    return {str(market).strip().upper() for market in markets if str(market).strip()}


def _market_for(code: str, market: str) -> str:
    normalized = market.strip().upper()
    if normalized in {"SH", "SZ", "BJ"}:
        return normalized
    return format_symbol(code).split(".", 1)[1]


def _format_symbol_with_market(code: str, market: str) -> str:
    if market in {"SH", "SZ", "BJ"}:
        return f"{code.zfill(6)}.{market}"
    return format_symbol(code)
