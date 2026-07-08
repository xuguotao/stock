"""Compare performance: old (whole market) vs new (batch streaming)."""
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline
from src.data.tencent_source import TencentQuoteSource

def test_batch_streaming():
    """Test with batch streaming (new approach)."""
    print("=" * 70)
    print("测试分片流式提交（新方案）")
    print("=" * 70)

    source = TencentQuoteSource(rate_limit=0.0, intraday_workers=30)

    start = time.time()
    result = sync_clickhouse_minute5_kline(
        trade_date=date.today(),
        source=source,
        fetch_batch_size=500,  # 每批 500 只
        commit_per_batch=True,  # 每批提交
        progress=lambda p, s, m, **kw: print(f"[{p:3d}%] {m}"),
    )
    elapsed = time.time() - start

    print("\n" + "=" * 70)
    print(f"总耗时: {elapsed:.2f} 秒")
    print(f"目标桶: {result['target_datetime']}")
    print(f"成功: {result['success']} / {result['target_symbols']}")
    print(f"插入: {result['inserted_rows']} 行")
    print("=" * 70)

    return elapsed, result

if __name__ == "__main__":
    print(f"\n开始测试: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    elapsed, result = test_batch_streaming()
    print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n结论: 分片流式提交可以在 {elapsed:.0f} 秒内完成全市场更新")
    print(f"      平均每批耗时: {elapsed / 10:.1f} 秒 (10 批 x 500 只)")
