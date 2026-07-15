"""Build the shared, latest-only A-share stock-universe profile snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class StockUniverseProfileRules:
    lookback_days: int = 20
    min_trading_days: int = 15
    min_average_amount: float = 10_000_000.0
    min_listing_age_days: int = 0
    include_beijing: bool = False

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "StockUniverseProfileRules":
        return cls(
            lookback_days=max(1, int(values.get("lookback_days") or 20)),
            min_trading_days=max(1, int(values.get("min_trading_days") or 15)),
            min_average_amount=max(0.0, float(values.get("min_average_amount") or 10_000_000)),
            min_listing_age_days=max(0, int(values.get("min_listing_age_days") or 0)),
            include_beijing=bool(values.get("include_beijing") or False),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_profile(
    *,
    catalog_row: tuple[str, str, str, bool, date | None],
    daily_metrics: tuple[date | None, int, int, float, float, int] | None,
    rules: StockUniverseProfileRules,
    rule_version: int,
    computed_at: datetime,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Calculate one explainable profile from catalog and daily facts."""
    symbol, _name, market, is_st, list_date = catalog_row
    as_of = as_of_date or (daily_metrics[0] if daily_metrics else None)
    if as_of is None:
        raise ValueError("as_of_date is required when no daily metrics are available")
    latest_date, bar_count, trading_days, avg_amount, median_amount, zero_volume_days = daily_metrics or (
        None,
        0,
        0,
        0.0,
        0.0,
        0,
    )
    market = str(market).upper()
    listing_age_days = max(0, (as_of - list_date).days) if list_date else 0
    allowed_markets = {"SH", "SZ"} | ({"BJ"} if rules.include_beijing else set())
    catalog_valid = market in allowed_markets and not is_st and (not list_date or listing_age_days >= rules.min_listing_age_days)
    latest_daily_valid = latest_date == as_of
    liquidity_qualified = trading_days >= rules.min_trading_days and avg_amount >= rules.min_average_amount
    liquidity_level = "high" if avg_amount >= rules.min_average_amount * 5 else "medium" if liquidity_qualified else "low"
    exclusion_reasons: list[str] = []
    if market not in allowed_markets:
        exclusion_reasons.append("market_excluded")
    if is_st:
        exclusion_reasons.append("st")
    if list_date and listing_age_days < rules.min_listing_age_days:
        exclusion_reasons.append("listing_age_below_minimum")
    if not latest_daily_valid:
        exclusion_reasons.append("latest_daily_missing")
    if trading_days < rules.min_trading_days:
        exclusion_reasons.append("insufficient_trading_days")
    if avg_amount < rules.min_average_amount:
        exclusion_reasons.append("low_average_amount")
    return {
        "symbol": str(symbol),
        "as_of_date": as_of,
        "computed_at": computed_at,
        "rule_version": int(rule_version),
        "market": market,
        "is_st": bool(is_st),
        "list_date": list_date,
        "listing_age_days": listing_age_days,
        "catalog_valid": catalog_valid,
        "latest_daily_valid": latest_daily_valid,
        "recent_20d_bar_count": int(bar_count),
        "recent_20d_trading_days": int(trading_days),
        "recent_20d_avg_amount": float(avg_amount),
        "recent_20d_median_amount": float(median_amount),
        "recent_20d_zero_volume_days": int(zero_volume_days),
        "liquidity_qualified": liquidity_qualified,
        "liquidity_level": liquidity_level,
        "universe_eligible": not exclusion_reasons,
        "exclusion_reasons": exclusion_reasons,
    }


def refresh_stock_universe_profiles(
    *,
    client: Any,
    rules: StockUniverseProfileRules,
    rule_version: int = 1,
    symbols: Sequence[str] | None = None,
    progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Recompute and atomically append a complete profile snapshot."""
    # The task is also manually runnable before the first scheduled mootdx sync.
    from src.data.mootdx_clickhouse_sync import ensure_mootdx_tables

    ensure_mootdx_tables(client)
    if progress:
        progress(10, "resolving_trade_date", "确定标签基准交易日")
    calendar_rows = client.execute(
        "select date from trade_calendar where is_open = 1 and date <= "
        "(select max(trade_date) from mootdx_stock_kline final where frequency = 'daily') "
        "order by date desc limit %(limit)s",
        {"limit": rules.lookback_days},
    )
    trade_dates = sorted({row[0] for row in calendar_rows if isinstance(row[0], date)})
    if not trade_dates:
        raise RuntimeError("no trading dates available for stock universe profiles")
    as_of_date = trade_dates[-1]
    filters = "and c.symbol in %(symbols)s" if symbols else ""
    params: dict[str, Any] = {"symbols": tuple(symbols or ())}
    catalog_rows = client.execute(
        "select c.symbol, c.name, multiIf(c.market = 0, 'SZ', c.market = 1, 'SH', c.market = 2, 'BJ', 'UNKNOWN'), "
        "c.is_st, toDateOrNull(nullIf(s.list_date, '')) "
        "from (select * from mootdx_stock_catalog final) as c "
        "left join (select * from stocks final) as s on s.symbol = splitByChar('.', c.symbol)[1] "
        f"where c.is_active = 1 {filters} order by c.symbol",
        params,
    )
    if progress:
        progress(30, "reading_daily", f"计算 {len(catalog_rows)} 只标的近 {rules.lookback_days} 日流动性")
    metric_rows = client.execute(
        "select symbol, maxIf(trade_date, open > 0 and high > 0 and low > 0 and close > 0 and volume > 0 and amount > 0), "
        "count(), countIf(open > 0 and high > 0 and low > 0 and close > 0 and volume > 0 and amount > 0), "
        "avgIf(amount, open > 0 and high > 0 and low > 0 and close > 0 and volume > 0 and amount > 0), "
        "quantileExactIf(0.5)(amount, open > 0 and high > 0 and low > 0 and close > 0 and volume > 0 and amount > 0), "
        "countIf(volume = 0) from mootdx_stock_kline final "
        "where frequency = 'daily' and trade_date in %(trade_dates)s "
        "group by symbol",
        {"trade_dates": tuple(trade_dates)},
    )
    metrics = {
        str(row[0]): (row[1], int(row[2]), int(row[3]), float(row[4] or 0), float(row[5] or 0), int(row[6]))
        for row in metric_rows
    }
    computed_at = datetime.now().replace(microsecond=0)
    profiles = [
        build_profile(
            catalog_row=(str(row[0]), str(row[1]), str(row[2]), bool(row[3]), row[4]),
            daily_metrics=metrics.get(str(row[0])),
            rules=rules,
            rule_version=rule_version,
            computed_at=computed_at,
            as_of_date=as_of_date,
        )
        for row in catalog_rows
    ]
    if progress:
        progress(80, "writing_profiles", f"写入 {len(profiles)} 条股票池标签")
    if profiles:
        client.execute(
            "insert into stock_universe_profiles "
            "(symbol, as_of_date, computed_at, rule_version, market, is_st, list_date, listing_age_days, catalog_valid, "
            "latest_daily_valid, recent_20d_bar_count, recent_20d_trading_days, recent_20d_avg_amount, "
            "recent_20d_median_amount, recent_20d_zero_volume_days, liquidity_qualified, liquidity_level, "
            "universe_eligible, exclusion_reasons) values",
            [
                (
                    profile["symbol"], profile["as_of_date"], profile["computed_at"], profile["rule_version"], profile["market"],
                    int(profile["is_st"]), profile["list_date"], profile["listing_age_days"], int(profile["catalog_valid"]),
                    int(profile["latest_daily_valid"]), profile["recent_20d_bar_count"], profile["recent_20d_trading_days"],
                    profile["recent_20d_avg_amount"], profile["recent_20d_median_amount"], profile["recent_20d_zero_volume_days"],
                    int(profile["liquidity_qualified"]), profile["liquidity_level"], int(profile["universe_eligible"]),
                    profile["exclusion_reasons"],
                )
                for profile in profiles
            ],
        )
    result = {
        "as_of_date": as_of_date.isoformat(),
        "computed_at": computed_at.isoformat(sep=" "),
        "rule_version": int(rule_version),
        "rules": rules.as_dict(),
        "symbols": len(profiles),
        "catalog_valid": sum(profile["catalog_valid"] for profile in profiles),
        "latest_daily_valid": sum(profile["latest_daily_valid"] for profile in profiles),
        "liquidity_qualified": sum(profile["liquidity_qualified"] for profile in profiles),
        "universe_eligible": sum(profile["universe_eligible"] for profile in profiles),
        "failed_samples": [],
    }
    if progress:
        progress(100, "completed", f"已生成 {result['universe_eligible']} 只默认可用标的")
    return result
