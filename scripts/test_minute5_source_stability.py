#!/usr/bin/env python3
"""Test continuous calling stability of Sina and Tencent 5m APIs.

Writes results to minute5_source_stability table.
"""
from __future__ import annotations

import sys
import time
import uuid
import json
import os
import http.client
import ssl
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from clickhouse_driver import Client

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Configuration ────────────────────────────────────────────────────────────

TEST_ID = f"stability_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
REQUESTS_PER_SOURCE = 500  # Total requests per source
CONCURRENCY = 80  # Optimal concurrency from benchmark
DATALLEN = 1000  # Bars per request

# Real stock symbols for testing
TEST_SYMBOLS = [
    'sh600519', 'sz000001', 'sh601318', 'sz300750', 'sh688981',
    'sh600036', 'sz000858', 'sh601166', 'sz002475', 'sh600276',
    'sh603259', 'sz300059', 'sh688111', 'sz002594', 'sh600000',
    'sh601012', 'sz002049', 'sh603501', 'sz300661', 'sh688036',
    'sh600809', 'sz000568', 'sh601888', 'sz002714', 'sh603288',
    'sh600887', 'sz300124', 'sh688396', 'sz002352', 'sh601225',
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

def fetch_sina(symbol: str, datalen: int, request_order: int) -> dict:
    """Fetch 5m bars from Sina Finance API."""
    path = (
        f"/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={symbol}&scale=5&ma=no&datalen={datalen}"
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
        bars = len(data) if isinstance(data, list) else 0
        return {
            'test_id': TEST_ID,
            'source': 'sina',
            'symbol': symbol,
            'datalen': datalen,
            'request_order': request_order,
            'http_status': resp.status,
            'success': 1 if (resp.status == 200 and bars > 0) else 0,
            'bars_returned': bars,
            'latency_ms': elapsed,
            'error_message': '',
        }
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {
            'test_id': TEST_ID,
            'source': 'sina',
            'symbol': symbol,
            'datalen': datalen,
            'request_order': request_order,
            'http_status': 0,
            'success': 0,
            'bars_returned': 0,
            'latency_ms': elapsed,
            'error_message': str(e)[:200],
        }

# ── Tencent API ──────────────────────────────────────────────────────────────

_TENCENT_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://gu.qq.com/',
}

def fetch_tencent(symbol: str, datalen: int, request_order: int) -> dict:
    """Fetch 5m bars from Tencent mkline API."""
    url = f'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},m5,,{datalen}'
    t0 = time.time()
    try:
        r = requests.get(url, headers=_TENCENT_HEADERS, timeout=15)
        elapsed = (time.time() - t0) * 1000
        data = r.json()
        bars = (data.get('data') or {}).get(symbol, {}).get('m5', [])
        return {
            'test_id': TEST_ID,
            'source': 'tencent',
            'symbol': symbol,
            'datalen': datalen,
            'request_order': request_order,
            'http_status': r.status_code,
            'success': 1 if (r.status_code == 200 and len(bars) > 0) else 0,
            'bars_returned': len(bars),
            'latency_ms': elapsed,
            'error_message': '',
        }
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {
            'test_id': TEST_ID,
            'source': 'tencent',
            'symbol': symbol,
            'datalen': datalen,
            'request_order': request_order,
            'http_status': 0,
            'success': 0,
            'bars_returned': 0,
            'latency_ms': elapsed,
            'error_message': str(e)[:200],
        }

# ── Test Runner ──────────────────────────────────────────────────────────────

def run_stability_test(source: str, fetch_func, total_requests: int, concurrency: int):
    """Run stability test for a single source."""
    print(f"\n{'='*60}")
    print(f"Testing {source.upper()} - {total_requests} requests, concurrency={concurrency}")
    print(f"{'='*60}")

    results = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for i in range(total_requests):
            symbol = TEST_SYMBOLS[i % len(TEST_SYMBOLS)]
            future = pool.submit(fetch_func, symbol, DATALLEN, i + 1)
            futures[future] = i

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if (result['request_order'] % 100) == 0:
                print(f"  [{result['request_order']:4d}/{total_requests}] "
                      f"success={result['success']} latency={result['latency_ms']:.0f}ms")

    total_time = (time.time() - t0) * 1000
    successes = sum(1 for r in results if r['success'])
    failures = total_requests - successes
    avg_latency = sum(r['latency_ms'] for r in results) / len(results)
    latencies = sorted([r['latency_ms'] for r in results])
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    print(f"\n{source.upper()} Results:")
    print(f"  Total time: {total_time/1000:.1f}s")
    print(f"  Success: {successes}/{total_requests} ({successes/total_requests*100:.1f}%)")
    print(f"  Failures: {failures}/{total_requests} ({failures/total_requests*100:.1f}%)")
    print(f"  Latency: avg={avg_latency:.0f}ms, p50={p50:.0f}ms, p95={p95:.0f}ms, p99={p99:.0f}ms")

    return results

def write_to_clickhouse(client, results):
    """Write test results to ClickHouse."""
    if not results:
        return

    rows = [
        (
            r['test_id'], r['test_time'] if 'test_time' in r else datetime.now(),
            r['source'], r['symbol'], r['datalen'], r['request_order'],
            r['http_status'], r['success'], r['bars_returned'],
            r['latency_ms'], r['error_message']
        )
        for r in results
    ]

    client.execute(
        """INSERT INTO minute5_source_stability
           (test_id, test_time, source, symbol, datalen, request_order,
            http_status, success, bars_returned, latency_ms, error_message)
           VALUES""",
        rows
    )
    print(f"  Written {len(rows)} rows to minute5_source_stability")

def main():
    print(f"Test ID: {TEST_ID}")
    print(f"ClickHouse: {CLICKHOUSE_HOST}/{CLICKHOUSE_DATABASE}")

    client = Client(
        host=CLICKHOUSE_HOST,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DATABASE
    )

    # Run tests
    sina_results = run_stability_test('sina', fetch_sina, REQUESTS_PER_SOURCE, CONCURRENCY)
    tencent_results = run_stability_test('tencent', fetch_tencent, REQUESTS_PER_SOURCE, CONCURRENCY)

    # Write to ClickHouse
    print(f"\n{'='*60}")
    print("Writing results to ClickHouse...")
    print(f"{'='*60}")
    write_to_clickhouse(client, sina_results)
    write_to_clickhouse(client, tencent_results)

    # Summary comparison
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")

    sina_ok = sum(1 for r in sina_results if r['success'])
    tencent_ok = sum(1 for r in tencent_results if r['success'])

    print(f"{'Metric':<20} {'Sina':>15} {'Tencent':>15}")
    print(f"{'─'*50}")
    print(f"{'Success Rate':<20} {sina_ok/REQUESTS_PER_SOURCE*100:>14.1f}% {tencent_ok/REQUESTS_PER_SOURCE*100:>14.1f}%")

    sina_lat = [r['latency_ms'] for r in sina_results]
    tencent_lat = [r['latency_ms'] for r in tencent_results]

    print(f"{'Avg Latency':<20} {sum(sina_lat)/len(sina_lat):>14.0f}ms {sum(tencent_lat)/len(tencent_lat):>14.0f}ms")
    print(f"{'P50 Latency':<20} {sorted(sina_lat)[len(sina_lat)//2]:>14.0f}ms {sorted(tencent_lat)[len(tencent_lat)//2]:>14.0f}ms")
    print(f"{'P95 Latency':<20} {sorted(sina_lat)[int(len(sina_lat)*0.95)]:>14.0f}ms {sorted(tencent_lat)[int(len(tencent_lat)*0.95)]:>14.0f}ms")

if __name__ == '__main__':
    main()
