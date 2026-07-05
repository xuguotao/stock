"""Test script to explore tdxrs data source capabilities."""
from __future__ import annotations

import time
from datetime import date, datetime

import tdxrs
from tdxrs import TdxHqClient

print("=" * 80)
print("TDXRS 数据源能力测试")
print("=" * 80)
print(f"tdxrs version: {tdxrs.__version__}")
print()

# Test 1: Connection
print("[Test 1] 连接通达信服务器")
print("-" * 80)
client = TdxHqClient()
# Use a known stable server (海通证券)
server_ip = "58.63.254.191"
server_port = 7709
start_time = time.time()
connected = client.connect(server_ip, server_port)
connect_time = time.time() - start_time
print(f"连接状态: {'成功' if connected else '失败'}")
print(f"连接服务器: {server_ip}:{server_port}")
print(f"连接耗时: {connect_time:.3f}s")
print()

if not connected:
    print("连接失败，退出测试")
    exit(1)

# Test 2: Security count
print("[Test 2] 证券数量查询")
print("-" * 80)
for market_name, market_code in [("深圳", 0), ("上海", 1), ("北京", 2)]:
    try:
        count = client.get_security_count(market_code)
        print(f"{market_name}市场 (market={market_code}): {count} 只证券")
    except Exception as e:
        print(f"{market_name}市场 (market={market_code}): 查询失败 - {e}")
print()

# Test 3: Security list (sample)
print("[Test 3] 证券列表（前 10 只）")
print("-" * 80)
try:
    stocks = client.get_security_list(0, 0)[:10]  # SZ market, first 10
    print(f"深圳市场前 10 只证券:")
    for s in stocks:
        print(f"  {s.get('code', ''):8s} | {s.get('name', ''):20s} | "
              f"小数位={s.get('decimal_point', 2)} | "
              f"前收盘价={s.get('pre_close', 0):.2f}")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 4: K-line bars (different frequencies)
print("[Test 4] K线数据（不同周期）")
print("-" * 80)
test_symbol = ("000001", 1)  # 平安银行 SH (实际上 000001 是 SZ，这里测试用)
test_symbol = ("000001", 0)  # 深圳市场

freq_map = {
    "1分钟": 8,
    "5分钟": 0,
    "15分钟": 1,
    "30分钟": 2,
    "60分钟": 3,
    "日线": 4,
    "周线": 5,
    "月线": 6,
}

for freq_name, category in freq_map.items():
    try:
        start_time = time.time()
        bars = client.get_security_bars(category, test_symbol[1], test_symbol[0], 0, 10)
        elapsed = time.time() - start_time
        if bars:
            print(f"{freq_name:8s} | 获取 {len(bars):3d} 条 | 耗时 {elapsed:.3f}s | "
                  f"最新: {bars[-1].get('datetime', '')} close={bars[-1].get('close', 0):.2f}")
        else:
            print(f"{freq_name:8s} | 无数据")
    except Exception as e:
        print(f"{freq_name:8s} | 失败: {e}")
print()

# Test 5: Historical K-line depth (how far back can we go?)
print("[Test 5] 历史K线深度（最大回补范围）")
print("-" * 80)
for freq_name, category in [("日线", 4), ("5分钟", 0), ("1分钟", 8)]:
    try:
        # Try to get as many bars as possible
        bars = client.get_security_bars(category, 0, "000001", 0, 800)
        if bars:
            earliest = bars[0].get('datetime', '')
            latest = bars[-1].get('datetime', '')
            print(f"{freq_name:8s} | {len(bars):4d} 条 | "
                  f"最早: {earliest[:10] if earliest else 'N/A'} | "
                  f"最新: {latest[:10] if latest else 'N/A'}")
        else:
            print(f"{freq_name:8s} | 无数据")
    except Exception as e:
        print(f"{freq_name:8s} | 失败: {e}")
print()

# Test 6: Real-time quotes (五档盘口)
print("[Test 6] 实时行情（五档盘口）")
print("-" * 80)
try:
    quotes = client.get_security_quotes([(0, "000001"), (1, "600000")])  # 平安银行, 浦发银行
    if quotes:
        for q in quotes:
            print(f"股票: {q.get('code', '')} | "
                  f"最新价={q.get('price', 0):.2f} | "
                  f"涨幅={q.get('change_pct', 0):.2f}% | "
                  f"成交量={q.get('vol', 0)} | "
                  f"成交额={q.get('amount', 0):.0f}")
            # Show bid/ask 5 levels if available
            for i in range(1, 6):
                bid_price = q.get(f'bid{i}', 0)
                bid_vol = q.get(f'bid_vol{i}', 0)
                ask_price = q.get(f'ask{i}', 0)
                ask_vol = q.get(f'ask_vol{i}', 0)
                if bid_price > 0 or ask_price > 0:
                    print(f"  档位 {i} | 买{bid_price:.2f}×{bid_vol} | 卖{ask_price:.2f}×{ask_vol}")
    else:
        print("无实时行情数据（可能非交易时段）")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 7: XDXR info (除权除息)
print("[Test 7] 除权除息数据")
print("-" * 80)
try:
    xdxr_list = client.get_xdxr_info(0, "000001")  # 平安银行
    if xdxr_list:
        print(f"平安银行 (000001) 除权除息记录数: {len(xdxr_list)}")
        for x in xdxr_list[:5]:  # Show first 5
            print(f"  {x.get('year', 0)}-{x.get('month', 0):02d}-{x.get('day', 0):02d} | "
                  f"类型={x.get('category', 0)} | "
                  f"分红={x.get('bonus_amount', 0):.3f} | "
                  f"送股={x.get('ratening_amount', 0):.3f} | "
                  f"配股={x.get('increased_amount', 0):.3f}")
        if len(xdxr_list) > 5:
            print(f"  ... (还有 {len(xdxr_list) - 5} 条记录)")
    else:
        print("无除权除息数据")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 8: Finance info
print("[Test 8] 财务数据")
print("-" * 80)
try:
    finance = client.get_finance_info(0, "000001")
    if finance:
        print(f"平安银行 (000001) 财务数据:")
        for key in ["total_capital", "liquid_capital", "eps", "net_asset_per_share"]:
            if key in finance:
                print(f"  {key:25s} = {finance[key]}")
    else:
        print("无财务数据")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 9: Transaction data (逐笔成交)
print("[Test 9] 逐笔成交数据")
print("-" * 80)
try:
    transactions = client.get_transaction_data(0, "000001", 0, 10)
    if transactions:
        print(f"平安银行 (000001) 当日逐笔成交（前 10 笔）:")
        for t in transactions:
            print(f"  {t.get('time', '')} | "
                  f"价格={t.get('price', 0):.2f} | "
                  f"成交量={t.get('vol', 0)} | "
                  f"买卖方向={t.get('buyorsell', 0)}")
    else:
        print("无逐笔成交数据（可能非交易时段）")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 10: Minute time data (分时数据)
print("[Test 10] 分时数据")
print("-" * 80)
try:
    minute_data = client.get_minute_time_data(0, "000001")
    if minute_data:
        print(f"平安银行 (000001) 当日分时数据条数: {len(minute_data)}")
        if minute_data:
            print(f"  最新: {minute_data[-1]}")
    else:
        print("无分时数据（可能非交易时段）")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 11: Block info (板块数据)
print("[Test 11] 板块数据")
print("-" * 80)
try:
    # Get block metadata
    block_meta = client.get_block_info_meta()
    if block_meta:
        print(f"板块元数据: {block_meta}")
    else:
        print("无板块元数据")

    # Try to get block list
    blocks = client.get_and_parse_block_info("ZS")  # 指数板块
    if blocks:
        print(f"指数板块数量: {len(blocks)}")
        for b in blocks[:5]:
            print(f"  {b.get('blockname', ''):20s} | 股票数={b.get('stock_list', []) and len(b.get('stock_list', []))}")
    else:
        print("无板块数据")
except Exception as e:
    print(f"查询失败: {e}")
print()

# Test 12: Performance benchmark
print("[Test 12] 性能基准测试")
print("-" * 80)
test_cases = [
    ("日线 800 条", lambda: client.get_security_bars(4, 0, "000001", 0, 800)),
    ("5分钟 800 条", lambda: client.get_security_bars(0, 0, "000001", 0, 800)),
    ("实时行情 10 只", lambda: client.get_security_quotes([(0, f"00000{i}") for i in range(10)])),
    ("证券列表 1000 只", lambda: client.get_security_list(0, 0)),
]

for name, func in test_cases:
    try:
        iterations = 5
        times = []
        for _ in range(iterations):
            start_time = time.time()
            result = func()
            elapsed = time.time() - start_time
            times.append(elapsed)
        avg_time = sum(times) / len(times)
        print(f"{name:20s} | 平均 {avg_time:.3f}s | 吞吐 {1/avg_time:.1f} 次/秒")
    except Exception as e:
        print(f"{name:20s} | 失败: {e}")
print()

# Cleanup
print("[Cleanup] 断开连接")
print("-" * 80)
client.disconnect()
print("已断开连接")
print()

print("=" * 80)
print("测试完成")
print("=" * 80)
