"""Test minute5 sync performance with Tencent source."""
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline
from src.data.tencent_source import TencentQuoteSource

def test_performance():
    """Test full market sync performance."""
    print(f"开始测试: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("数据源: TencentQuoteSource")
    print("目标: 全市场 5m 分钟线同步")
    print("-" * 60)

    start_time = time.time()

    # Use Tencent source with default settings (30 workers)
    source = TencentQuoteSource(rate_limit=0.0, intraday_workers=30)

    result = sync_clickhouse_minute5_kline(
        trade_date=date.today(),
        source=source,
        include_st=False,
        progress=lambda percent, stage, message: print(f"[{percent:3d}%] {stage}: {message}"),
    )

    elapsed = time.time() - start_time

    print("-" * 60)
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总耗时: {elapsed:.2f} 秒")
    print(f"\n结果统计:")
    print(f"  目标股票数: {result.get('target_symbols', 0)}")
    print(f"  跳过 (已完整): {result.get('skipped', 0)}")
    print(f"  成功更新: {result.get('success', 0)}")
    print(f"  无数据: {result.get('no_data', 0)}")
    print(f"  失败: {result.get('failed', 0)}")
    print(f"  插入行数: {result.get('inserted_rows', 0)}")
    print(f"  目标时间: {result.get('target_datetime')}")
    print(f"  是否部分: {result.get('partial', False)}")
    print(f"  剩余股票: {result.get('remaining_symbols', 0)}")

    return elapsed, result

if __name__ == "__main__":
    test_performance()
