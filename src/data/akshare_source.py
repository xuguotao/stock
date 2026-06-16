"""AKShare data source adapter.

AKShare is a free, open-source A-share data library.
Documentation: https://akshare.akfamily.xyz/

Supported endpoints:
  - stock_zh_a_hist: daily/weekly/monthly bars
  - stock_zh_a_spot_em: real-time quotes
  - stock_info_a_code_name: stock list
  - stock_a_indicator_lg: valuation indicators

Note: AKShare uses East Money API internally. If behind a proxy,
set environment variables HTTP_PROXY/HTTPS_PROXY or use the
fallback Sina API via _fetch_bars_sina().
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime

import pandas as pd

from src.data.base import DataSourceBase
from src.data.models import DailyBar, FinancialStatement, StockInfo
from src.core.constants import format_symbol

logger = logging.getLogger(__name__)


def _fetch_bars_sina(code: str, start: date, end: date) -> pd.DataFrame:
    """Fallback: fetch daily bars directly from Sina Finance API.

    Uses the current Sina finance endpoint with proper headers.
    """
    import urllib.request
    import json
    import re

    # Determine market prefix for Sina symbol
    suffix = "sh" if code.startswith(("600", "601", "603", "605", "688", "689")) else "sz"
    sina_symbol = f"{suffix}{code}"

    url = (
        f"https://stock2.finance.sina.com.cn/futures/api/openapi.php/"
        f"StockDayKLineService.getKLineData?symbol={sina_symbol}"
        f"&scale=240&ma=no&datalen=1000"
    )

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
    except Exception as e:
        logger.warning(f"Sina API failed: {e}")
        return pd.DataFrame()

    # Parse JSON response
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try JSONP format
        match = re.search(r"\[(.*)\]", text, re.DOTALL)
        if not match:
            return pd.DataFrame()
        try:
            data = json.loads(f"[{match.group(1)}]")
        except json.JSONDecodeError:
            return pd.DataFrame()

    if not data or "data" not in data:
        return pd.DataFrame()

    rows = []
    for item in data.get("data", []):
        d = datetime.strptime(item["day"], "%Y-%m-%d").date()
        if d < start or d > end:
            continue
        rows.append({
            "date": d,
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": float(item["volume"]),
            "amount": float(item.get("turnover", 0)),
            "adjusted_close": float(item["close"]),
            "symbol": format_symbol(code),
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _intraday_period(frequency: str) -> str | None:
    return {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "60m": "60",
    }.get(frequency)


def _parse_akshare_intraday_bars(
    df: pd.DataFrame,
    symbol: str,
    trade_date: date,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    col_map = {
        "时间": "datetime",
        "日期": "datetime",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    prepared = df.rename(columns=col_map).copy()
    if "datetime" not in prepared.columns:
        return pd.DataFrame()

    prepared["datetime"] = pd.to_datetime(prepared["datetime"], errors="coerce")
    prepared = prepared[prepared["datetime"].dt.date == trade_date].copy()
    if prepared.empty:
        return pd.DataFrame()

    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column not in prepared.columns:
            prepared[column] = 0.0
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce").fillna(0.0)

    prepared["time"] = prepared["datetime"].dt.time
    prepared["symbol"] = format_symbol(symbol)
    columns = ["time", "datetime", "open", "high", "low", "close", "volume", "amount", "symbol"]
    return prepared[columns].sort_values("datetime").reset_index(drop=True)


class AKShareSource(DataSourceBase):
    """AKShare data source with rate limiting and error handling."""

    name = "akshare"

    def __init__(self, rate_limit: float = 0.1):
        super().__init__(rate_limit=rate_limit)
        self._cache_bars: dict[str, pd.DataFrame] = {}

    # ── Daily Bars ─────────────────────────────────────────────

    def fetch_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        """Fetch daily bars from AKShare, with Sina fallback."""
        code = symbol.split(".")[0]

        # Try AKShare first
        try:
            self._wait_for_rate_limit()
            import akshare as ak

            df = ak.stock_zh_a_hist(
                symbol=code,
                period=frequency,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df is not None and not df.empty:
                return self._parse_akshare_bars(df, code)
        except Exception as e:
            logger.warning(f"AKShare fetch_bars failed for {symbol}: {e}")

        # Fallback to Sina API
        logger.info(f"Falling back to Sina API for {symbol}")
        time.sleep(0.3)
        return _fetch_bars_sina(code, start, end)

    def _parse_akshare_bars(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Parse AKShare bar data to standard format."""
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["symbol"] = format_symbol(code)
        df["adjusted_close"] = df["close"]

        required_cols = ["date", "open", "high", "low", "close",
                         "volume", "amount", "adjusted_close", "symbol"]
        return df[[c for c in required_cols if c in df.columns]].sort_values("date").reset_index(drop=True)

    def fetch_bars_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        frequency: str = "daily",
    ) -> pd.DataFrame:
        """Fetch bars for multiple symbols, returning MultiIndex DataFrame."""
        all_dfs = []
        for sym in symbols:
            df = self.fetch_bars(sym, start, end, frequency)
            if not df.empty:
                all_dfs.append(df)

        if not all_dfs:
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        combined["date"] = pd.to_datetime(combined["date"])
        return combined.set_index(["date", "symbol"])

    # ── Stock List ─────────────────────────────────────────────

    def fetch_stock_list(self) -> list[StockInfo]:
        """Fetch all A-share stock codes and names."""
        import akshare as ak

        self._wait_for_rate_limit()

        try:
            df = ak.stock_info_a_code_name()
        except Exception as e:
            logger.warning(f"AKShare fetch_stock_list failed: {e}")
            return []

        stocks = []
        for _, row in df.iterrows():
            code = str(row["code"]).zfill(6)
            symbol = format_symbol(code)
            stocks.append(StockInfo(
                symbol=symbol,
                code=code,
                name=str(row["name"]),
            ))
        return stocks

    # ── Real-time Quotes ───────────────────────────────────────

    def fetch_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch real-time quotes from East Money via AKShare."""
        import akshare as ak

        self._wait_for_rate_limit()

        try:
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.warning(f"AKShare fetch_realtime_quotes failed: {e}")
            return pd.DataFrame()

        if df.empty:
            return df

        col_map = {
            "代码": "code",
            "名称": "name",
            "最新价": "price",
            "涨跌幅": "change_pct",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=col_map)

        # Filter to requested symbols
        codes = [s.split(".")[0] for s in symbols]
        df = df[df["code"].isin(codes)]

        if not df.empty:
            df["symbol"] = df["code"].apply(format_symbol)
            df["timestamp"] = pd.Timestamp.now()

        return df

    def fetch_intraday_bars(
        self,
        symbol: str,
        trade_date: date,
        frequency: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday minute bars from East Money via AKShare."""
        import akshare as ak

        period = _intraday_period(frequency)
        if period is None:
            return pd.DataFrame()

        code = symbol.split(".")[0].zfill(6)
        self._wait_for_rate_limit()

        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=code,
                start_date=f"{trade_date.isoformat()} 09:30:00",
                end_date=f"{trade_date.isoformat()} 15:00:00",
                period=period,
                adjust="",
            )
        except Exception as e:
            logger.warning(f"AKShare fetch_intraday_bars failed for {symbol}: {e}")
            return pd.DataFrame()

        return _parse_akshare_intraday_bars(df, symbol, trade_date)

    # ── Financials ─────────────────────────────────────────────

    def fetch_financials(self, symbol: str) -> list[FinancialStatement]:
        """Fetch valuation indicators from AKShare."""
        import akshare as ak

        self._wait_for_rate_limit()
        code = symbol.split(".")[0]

        try:
            df = ak.stock_a_indicator_lg(symbol=code)
        except Exception as e:
            logger.warning(f"AKShare fetch_financials failed for {symbol}: {e}")
            return []

        if df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            report_date = row.get("trade_date") or row.get("date")
            if isinstance(report_date, str):
                report_date = datetime.strptime(report_date, "%Y%m%d").date()
            elif hasattr(report_date, "date"):
                report_date = report_date.date()
            else:
                continue

            results.append(FinancialStatement(
                symbol=symbol,
                report_date=report_date,
                publish_date=report_date,
                revenue=0.0,
                net_profit=0.0,
                total_assets=0.0,
                total_equity=0.0,
                eps=float(row.get("eps", 0) or 0),
                roe=float(row.get("roe", 0) or 0),
                pe_ratio=float(row.get("pe", 0) or 0) if row.get("pe") else None,
                pb_ratio=float(row.get("pb", 0) or 0) if row.get("pb") else None,
                ps_ratio=float(row.get("ps", 0) or 0) if row.get("ps") else None,
            ))

        return results
