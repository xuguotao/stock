#!/usr/bin/env python3
"""Test network connectivity to Chinese financial APIs."""

import json
import os
import sys

# Force disable all proxy detection at the very beginning
for key in list(os.environ.keys()):
    if 'proxy' in key.lower():
        os.environ.pop(key, None)

# Patch requests BEFORE importing anything else
import requests
_original_session = requests.Session

class _NoProxySession(requests.Session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trust_env = False
        # Explicitly set no proxies
        self.proxies = {}

requests.Session = _NoProxySession

# Also patch urllib3's proxy detection
import urllib3
urllib3.util.proxy.connection_requires_http_tunnel = lambda *a, **k: False


def test_direct():
    """Test direct connection to East Money."""
    session = requests.Session()

    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": 101,
        "fqt": 1,
        "secid": "0.000001",
        "beg": "20250501",
        "end": "20250510",
    }

    try:
        resp = session.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("klines"):
            klines = data["data"]["klines"]
            print(f"✅ Direct requests: {len(klines)} bars")
            print(f"   {klines[0]}")
            return True
        print(f"❌ Direct requests: No data (status={resp.status_code})")
        return False
    except Exception as e:
        print(f"❌ Direct requests: {type(e).__name__}: {e}")
        return False


def test_sina():
    """Test Sina Finance API."""
    session = requests.Session()

    url = "https://hq.sinajs.cn/list=sh600519,sz000001"
    headers = {"Referer": "https://finance.sina.com.cn"}

    try:
        resp = session.get(url, headers=headers, timeout=10)
        if "var hq_str" in resp.text:
            print("✅ Sina Finance API: OK")
            for line in resp.text.strip().split("\n"):
                if "=" in line:
                    parts = line.split("=")
                    code = parts[0].split("_")[-1].strip("\"")
                    values = parts[1].strip("\";\n").split(",")
                    if len(values) > 3:
                        print(f"   {code}: {values[0]} @ {values[3]}")
            return True
        print(f"❌ Sina: Unexpected response")
        return False
    except Exception as e:
        print(f"❌ Sina: {type(e).__name__}: {e}")
        return False


def test_akshare():
    """Test AKShare with proxy patching."""
    # AKShare uses requests.Session() internally - our patch should intercept it
    try:
        import akshare as ak

        # Double-check: patch akshare's requests module if it has its own copy
        import importlib
        for mod_name in list(sys.modules.keys()):
            if 'akshare' in mod_name and 'requests' in mod_name:
                mod = sys.modules[mod_name]
                if hasattr(mod, 'Session'):
                    mod.Session = _NoProxySession

        df = ak.stock_zh_a_hist(
            symbol="000001",
            period="daily",
            start_date="20250501",
            end_date="20250510",
            adjust="qfq",
        )
        if not df.empty:
            print(f"✅ AKShare: {len(df)} rows")
            print(f"   Columns: {list(df.columns)}")
            return True
        print(f"❌ AKShare: Empty result")
        return False
    except Exception as e:
        print(f"❌ AKShare: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("A股量化工具 — 网络诊断 (No-Proxy Mode)")
    print("=" * 60)
    print()

    print("[1/3] Direct Connection:")
    r1 = test_direct()
    print()

    print("[2/3] Sina Finance API:")
    r2 = test_sina()
    print()

    print("[3/3] AKShare Library:")
    r3 = test_akshare()
    print()

    print("=" * 60)
    passed = sum([r1, r2, r3])
    print(f"Result: {passed}/3 passed")
    print("=" * 60)
