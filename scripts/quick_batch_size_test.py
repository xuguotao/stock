"""Quick batch size comparison test (runs immediately, no market hours check)."""
import sys
import time
import json
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline
from src.data.tencent_source import TencentQuoteSource


def quick_test(batch_size: int, stock_count: int = 1000, offset: int = 0) -> dict:
    """Quick test with specific batch size."""
    from src.data.clickhouse_source import ClickHouseStockDataSource

    # Get stock subset
    client = ClickHouseStockDataSource()._client_instance()
    rows = client.execute(
        f"select symbol, market from stocks final where market in ('SH', 'SZ') order by symbol limit {stock_count} offset {offset}"
    )
    symbols = [f"{str(code).zfill(6)}.{market}" for code, market in rows]

    if not symbols:
        return {"batch_size": batch_size, "error": "No stocks found"}

    source = TencentQuoteSource(rate_limit=0.0, intraday_workers=30)

    start = time.time()
    result = sync_clickhouse_minute5_kline(
        trade_date=date.today(),
        source=source,
        symbols=symbols,
        fetch_batch_size=batch_size,
        commit_per_batch=True,
        progress=None,
    )
    elapsed = time.time() - start

    return {
        "batch_size": batch_size,
        "stock_count": len(symbols),
        "elapsed_seconds": round(elapsed, 2),
        "success": result["success"],
        "inserted_rows": result["inserted_rows"],
        "batches": (result["success"] + batch_size - 1) // batch_size if result["success"] > 0 else 0,
        "elapsed_per_batch": round(elapsed / max(1, (result["success"] + batch_size - 1) // batch_size), 2) if result["success"] > 0 else round(elapsed, 2),
        "elapsed_per_stock": round(elapsed / max(1, result["success"]), 4),
    }


def run_comparison_test():
    """Run comparison test for different batch sizes."""
    batch_sizes = [200, 300, 500, 800, 1000]
    stock_count = 1000  # Use 1000 stocks for quick test

    print(f"\n{'='*80}")
    print(f"快速批次阈值对比测试")
    print(f"{'='*80}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"股票数: {stock_count}")
    print(f"Batch sizes: {batch_sizes}")
    print(f"{'='*80}\n")

    results = []
    for i, size in enumerate(batch_sizes):
        offset = i * stock_count

        print(f"测试 batch_size={size}, offset={offset}...", end=" ", flush=True)

        try:
            metrics = quick_test(size, stock_count, offset)

            if "error" in metrics:
                print(f"错误: {metrics['error']}")
            else:
                print(f"耗时 {metrics['elapsed_seconds']}s, 成功 {metrics['success']}/{metrics['stock_count']}")

            results.append(metrics)

        except Exception as e:
            print(f"异常: {e}")
            results.append({"batch_size": size, "error": str(e)})

    # Print summary
    print(f"\n{'='*80}")
    print("性能对比")
    print(f"{'='*80}")
    print(f"{'Batch Size':<12} {'耗时(s)':<10} {'成功数':<10} {'批次':<8} {'每批(s)':<10} {'每股(s)':<10}")
    print("-"*80)

    valid_results = [r for r in results if "error" not in r and r["success"] > 0]
    for r in sorted(valid_results, key=lambda x: x["elapsed_seconds"]):
        print(f"{r['batch_size']:<12} {r['elapsed_seconds']:<10} {r['success']:<10} "
              f"{r['batches']:<8} {r['elapsed_per_batch']:<10} {r['elapsed_per_stock']:<10}")

    if valid_results:
        best = min(valid_results, key=lambda x: x["elapsed_seconds"])
        print(f"\n最优 batch_size: {best['batch_size']}")
        print(f"  - 耗时: {best['elapsed_seconds']}s")
        print(f"  - 每批: {best['elapsed_per_batch']}s")
        print(f"  - 每股: {best['elapsed_per_stock']}s")

        # Extrapolate to full market (5000 stocks)
        full_market_time = best['elapsed_per_stock'] * 5000
        full_market_batches = (5000 + best['batch_size'] - 1) // best['batch_size']
        print(f"\n预估全市场（5000 只）:")
        print(f"  - 总耗时: {full_market_time:.0f}s ({full_market_time/60:.1f}分钟)")
        print(f"  - 批次数: {full_market_batches}")
        print(f"  - 每批耗时: {best['elapsed_per_batch']}s")

    print(f"{'='*80}\n")

    # Save results
    output_file = f"logs/batch_size_quick_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": datetime.now().isoformat(),
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"结果已保存: {output_file}\n")

    return results


if __name__ == "__main__":
    run_comparison_test()
