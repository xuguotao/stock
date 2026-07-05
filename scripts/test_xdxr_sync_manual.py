#!/usr/bin/env python
"""Test xdxr_sync manually."""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.clickhouse_xdxr_sync import sync_clickhouse_xdxr_info, _ensure_table
from src.data.tdxrs_sync import fetch_xdxr_info, is_tdxrs_available


def main():
    print("=" * 80)
    print("测试 xdxr_sync")
    print("=" * 80)

    # Check tdxrs availability
    if not is_tdxrs_available():
        print("❌ tdxrs 未安装")
        return

    print("✅ tdxrs 已安装")

    # Get ClickHouse client
    print("\n连接 ClickHouse...")
    client = ClickHouseStockDataSource()._client_instance()

    # Ensure table exists
    print("创建 xdxr_info 表...")
    _ensure_table(client)
    print("✅ 表已创建/确认存在")

    # Get stock list
    print("\n获取股票列表...")
    stocks_result = client.execute("SELECT DISTINCT symbol FROM stocks WHERE market IN ('SZ', 'SH')")
    symbols = [row[0] for row in stocks_result]
    print(f"找到 {len(symbols)} 只股票")

    if not symbols:
        print("⚠️  股票列表为空，请先运行 stock_master_sync")
        return

    # Test with first 10 stocks
    test_symbols = symbols[:10]
    print(f"\n测试同步前 10 只股票: {test_symbols}")

    # Run sync
    print("\n开始同步...")
    result = sync_clickhouse_xdxr_info(
        client=client,
        fetch_fn=fetch_xdxr_info,
        symbols=test_symbols,
    )

    print(f"\n✅ 同步完成:")
    print(f"  插入记录数: {result['inserted']}")
    print(f"  失败数: {result['failed']}")

    # Verify data
    print("\n验证数据...")
    count_result = client.execute("SELECT count() FROM xdxr_info")
    total_count = count_result[0][0] if count_result else 0
    print(f"xdxr_info 表总记录数: {total_count}")

    if total_count > 0:
        print("\n示例数据:")
        sample_result = client.execute("""
            SELECT symbol, year, month, day, category, bonus_amount
            FROM xdxr_info
            ORDER BY symbol, ex_date DESC
            LIMIT 5
        """)
        for row in sample_result:
            print(f"  {row[0]} | {row[1]}-{row[2]:02d}-{row[3]:02d} | "
                  f"类型={row[4]} | 分红={row[5]:.3f}")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
