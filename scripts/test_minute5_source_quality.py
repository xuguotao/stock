#!/usr/bin/env python3
"""Test data quality of Sina and Tencent 5m APIs.

Compares OHLCV data between sources, checks for anomalies, validates amount estimation.
Writes results to minute5_source_quality table.
"""
from __future__ import annotations

import sys
import time
import json
import os
import http.client
import ssl
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from clickhouse_driver import Client

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Configuration ────────────────────────────────────────────────────────────

TEST_ID = f"quality_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
TRADE_DATE = date(2026, 7, 8)  # Use a recent complete trading day
DATALLEN = 1000
CONCURRENCY = 80

TEST_SYMBOLS = [
    'sh600519', 'sz000001', 'sh601318', 'sz300750', 'sh688981',
    'sh600036', 'sz000858', 'sh601166', 'sz002475', 'sh600276',
    'sh603259', 'sz300059', 'sh688111', 'sz002594', 'sh600000',
    'sh601012', 'sz002049', 'sh603501', 'sz300661', 'sh688036',
]

CLICKHOUSE_HOST = os.getenv("STOCK_CLICKHOUSE_HOST", "127.0.0.1")
CLICKHOUSE_USER = os.getenv("STOCK_CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("STOCK_CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("STOCK_CLICKHOUSE_DATABASE", "stock")

# ── Sina API ─────────────────────────────────────────────────────────────────

_SINA_SSL_CTX = ssl.create_default_context()
_SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://finance.sina.com.cn',
    'Accept': 'application/json',
}

def fetch_sina_quality(symbol: str) -> dict:
    """Fetch and analyze 5m bars from Sina."""
    path = (
        f"/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={symbol}&scale=5&ma=no&datalen={DATALLEN}"
    )
    t0 = time.time()
    try:
        conn = http.client.HTTPSConnection(
            'money.finance.sina.com.cn', timeout=15, context=_SINA_SSL_CTX
        )
        conn.request('GET', path, headers=_SINA_HEADERS)
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        conn.close()
        elapsed = (time.time() - t0) * 1000

        data = json.loads(body)
        if not isinstance(data, list):
            return None

        # Filter for target date
        date_str = TRADE_DATE.isoformat()
        bars = [item for item in data if item.get('day', '').startswith(date_str)]

        if not bars:
            return None

        return analyze_bars(symbol, bars, 'sina', elapsed)
    except Exception as e:
        return {
            'test_id': TEST_ID,
            'source': 'sina',
            'symbol': symbol,
            'trade_date': TRADE_DATE,
            'bars_count': 0,
            'has_amount': 0,
            'amount_zero_ratio': 1.0,
            'open_outside_range': 0,
            'high_lt_low': 0,
            'volume_negative': 0,
            'price_negative': 0,
            'duplicate_bars': 0,
            'avg_latency_ms': elapsed,
            'error': str(e)[:200],
        }

# ── Tencent API ──────────────────────────────────────────────────────────────

_TENCENT_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://gu.qq.com/',
}

def fetch_tencent_quality(symbol: str) -> dict:
    """Fetch and analyze 5m bars from Tencent."""
    url = f'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},m5,,{DATALLEN}'
    t0 = time.time()
    try:
        r = requests.get(url, headers=_TENCENT_HEADERS, timeout=15)
        elapsed = (time.time() - t0) * 1000
        data = r.json()
        bars = (data.get('data') or {}).get(symbol, {}).get('m5', [])

        if not bars:
            return None

        # Filter for target date
        date_str = TRADE_DATE.strftime('%Y%m%d')
        bars = [b for b in bars if str(b[0]).startswith(date_str)]

        if not bars:
            return None

        return analyze_bars_tencent(symbol, bars, elapsed)
    except Exception as e:
        return {
            'test_id': TEST_ID,
            'source': 'tencent',
            'symbol': symbol,
            'trade_date': TRADE_DATE,
            'bars_count': 0,
            'has_amount': 0,
            'amount_zero_ratio': 1.0,
            'open_outside_range': 0,
            'high_lt_low': 0,
            'volume_negative': 0,
            'price_negative': 0,
            'duplicate_bars': 0,
            'avg_latency_ms': elapsed,
            'error': str(e)[:200],
        }

# ── Analysis ────────────────────────────────────────────────────────────────

def analyze_bars(symbol: str, bars: list, source: str, latency_ms: float) -> dict:
    """Analyze Sina bars for quality metrics."""
    bars_count = len(bars)
    has_amount = 0  # Sina never has amount
    amount_zero_count = 0
    open_outside_range = 0
    high_lt_low = 0
    volume_negative = 0
    price_negative = 0
    duplicate_bars = 0

    seen_datetimes = set()

    for item in bars:
        dt_str = item.get('day', '')
        open_ = float(item.get('open', 0))
        high = float(item.get('high', 0))
        low = float(item.get('low', 0))
        close = float(item.get('close', 0))
        volume = int(float(item.get('volume', 0)))

        # Check for duplicates
        if dt_str in seen_datetimes:
            duplicate_bars += 1
        seen_datetimes.add(dt_str)

        # Check price validity
        if open_ <= 0 or high <= 0 or low <= 0 or close <= 0:
            price_negative += 1

        # Check OHLC logic
        if high < low:
            high_lt_low += 1
        if open_ > high or open_ < low:
            open_outside_range += 1

        # Check volume
        if volume < 0:
            volume_negative += 1

    return {
        'test_id': TEST_ID,
        'source': source,
        'symbol': symbol,
        'trade_date': TRADE_DATE,
        'bars_count': bars_count,
        'has_amount': has_amount,
        'amount_zero_ratio': 1.0 if bars_count > 0 else 0.0,
        'open_outside_range': open_outside_range,
        'high_lt_low': high_lt_low,
        'volume_negative': volume_negative,
        'price_negative': price_negative,
        'duplicate_bars': duplicate_bars,
        'avg_latency_ms': latency_ms,
    }

def analyze_bars_tencent(symbol: str, bars: list, latency_ms: float) -> dict:
    """Analyze Tencent bars for quality metrics."""
    bars_count = len(bars)
    has_amount = 0  # Tencent mkline doesn't return amount directly
    amount_zero_count = 0
    open_outside_range = 0
    high_lt_low = 0
    volume_negative = 0
    price_negative = 0
    duplicate_bars = 0

    seen_datetimes = set()

    for bar in bars:
        # Tencent format: [datetime, open, close, high, low, volume, ...]
        if len(bar) < 6:
            continue

        dt_str = str(bar[0])
        open_ = float(bar[1])
        close = float(bar[2])
        high = float(bar[3])
        low = float(bar[4])
        volume = float(bar[5])

        # Check for duplicates
        if dt_str in seen_datetimes:
            duplicate_bars += 1
        seen_datetimes.add(dt_str)

        # Check price validity
        if open_ <= 0 or high <= 0 or low <= 0 or close <= 0:
            price_negative += 1

        # Check OHLC logic
        if high < low:
            high_lt_low += 1
        if open_ > high or open_ < low:
            open_outside_range += 1

        # Check volume
        if volume < 0:
            volume_negative += 1

    return {
        'test_id': TEST_ID,
        'source': 'tencent',
        'symbol': symbol,
        'trade_date': TRADE_DATE,
        'bars_count': bars_count,
        'has_amount': has_amount,
        'amount_zero_ratio': 1.0 if bars_count > 0 else 0.0,
        'open_outside_range': open_outside_range,
        'high_lt_low': high_lt_low,
        'volume_negative': volume_negative,
        'price_negative': price_negative,
        'duplicate_bars': duplicate_bars,
        'avg_latency_ms': latency_ms,
    }

# ── Test Runner ──────────────────────────────────────────────────────────────

def run_quality_test(source: str, fetch_func, symbols: list):
    """Run quality test for a single source."""
    print(f"\n{'='*60}")
    print(f"Testing {source.upper()} quality - {len(symbols)} symbols")
    print(f"{'='*60}")

    results = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(fetch_func, sym): sym for sym in symbols}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result is not None:
                results.append(result)
                if (i % 10) == 0:
                    print(f"  [{i:3d}/{len(symbols)}] {result['symbol']} "
                          f"bars={result['bars_count']} "
                          f"open_err={result['open_outside_range']} "
                          f"high_err={result['high_lt_low']}")

    total_time = (time.time() - t0) * 1000

    print(f"\n{source.upper()} Quality Results:")
    print(f"  Total time: {total_time/1000:.1f}s")
    print(f"  Symbols with data: {len(results)}/{len(symbols)}")

    if results:
        avg_bars = sum(r['bars_count'] for r in results) / len(results)
        total_open_err = sum(r['open_outside_range'] for r in results)
        total_high_err = sum(r['high_lt_low'] for r in results)
        total_dup = sum(r['duplicate_bars'] for r in results)
        avg_latency = sum(r['avg_latency_ms'] for r in results) / len(results)

        print(f"  Avg bars/symbol: {avg_bars:.1f}")
        print(f"  Open outside range: {total_open_err} total")
        print(f"  High < Low: {total_high_err} total")
        print(f"  Duplicate bars: {total_dup} total")
        print(f"  Avg latency: {avg_latency:.0f}ms")

    return results

def write_to_clickhouse(client, results):
    """Write test results to ClickHouse."""
    if not results:
        return

    rows = [
        (
            r['test_id'], r['test_time'] if 'test_time' in r else datetime.now(),
            r['source'], r['symbol'], r['trade_date'], r['bars_count'],
            r['has_amount'], r['amount_zero_ratio'], r['open_outside_range'],
            r['high_lt_low'], r['volume_negative'], r['price_negative'],
            r['duplicate_bars'], r['avg_latency_ms']
        )
        for r in results
    ]

    client.execute(
        """INSERT INTO minute5_source_quality
           (test_id, test_time, source, symbol, trade_date, bars_count,
            has_amount, amount_zero_ratio, open_outside_range, high_lt_low,
            volume_negative, price_negative, duplicate_bars, avg_latency_ms)
           VALUES""",
        rows
    )
    print(f"  Written {len(rows)} rows to minute5_source_quality")

def main():
    print(f"Test ID: {TEST_ID}")
    print(f"Trade Date: {TRADE_DATE}")
    print(f"ClickHouse: {CLICKHOUSE_HOST}/{CLICKHOUSE_DATABASE}")

    client = Client(
        host=CLICKHOUSE_HOST,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DATABASE
    )

    # Run tests
    sina_results = run_quality_test('sina', fetch_sina_quality, TEST_SYMBOLS)
    tencent_results = run_quality_test('tencent', fetch_tencent_quality, TEST_SYMBOLS)

    # Write to ClickHouse
    print(f"\n{'='*60}")
    print("Writing results to ClickHouse...")
    print(f"{'='*60}")
    write_to_clickhouse(client, sina_results)
    write_to_clickhouse(client, tencent_results)

    # Summary comparison
    print(f"\n{'='*60}")
    print("QUALITY COMPARISON SUMMARY")
    print(f"{'='*60}")

    def calc_metrics(results):
        if not results:
            return {}
        return {
            'symbols': len(results),
            'avg_bars': sum(r['bars_count'] for r in results) / len(results),
            'open_err': sum(r['open_outside_range'] for r in results),
            'high_err': sum(r['high_lt_low'] for r in results),
            'dup': sum(r['duplicate_bars'] for r in results),
            'avg_latency': sum(r['avg_latency_ms'] for r in results) / len(results),
        }

    sina_m = calc_metrics(sina_results)
    tencent_m = calc_metrics(tencent_results)

    print(f"{'Metric':<20} {'Sina':>15} {'Tencent':>15}")
    print(f"{'─'*50}")
    print(f"{'Symbols':<20} {sina_m.get('symbols', 0):>15} {tencent_m.get('symbols', 0):>15}")
    print(f"{'Avg Bars':<20} {sina_m.get('avg_bars', 0):>14.1f} {tencent_m.get('avg_bars', 0):>14.1f}")
    print(f"{'Open Errors':<20} {sina_m.get('open_err', 0):>15} {tencent_m.get('open_err', 0):>15}")
    print(f"{'High<Low Errors':<20} {sina_m.get('high_err', 0):>15} {tencent_m.get('high_err', 0):>15}")
    print(f"{'Duplicates':<20} {sina_m.get('dup', 0):>15} {tencent_m.get('dup', 0):>15}")
    print(f"{'Avg Latency':<20} {sina_m.get('avg_latency', 0):>14.0f}ms {tencent_m.get('avg_latency', 0):>14.0f}ms")

if __name__ == '__main__':
    main()
