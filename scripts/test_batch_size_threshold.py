"""Test different batch sizes for minute5 sync performance."""
import sys
import time
import json
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.clickhouse_minute5_sync import sync_clickhouse_minute5_kline
from src.data.tencent_source import TencentQuoteSource


def test_batch_size(batch_size: int, stock_limit: int = 2000, stock_offset: int = 0) -> dict:
    """Test a specific batch size and return performance metrics."""
    source = TencentQuoteSource(rate_limit=0.0, intraday_workers=30)

    # Use offset to ensure each test uses different stocks
    # This prevents incremental sync from skewing results
    symbols = _get_test_symbols(stock_limit, stock_offset)

    start = time.time()
    result = sync_clickhouse_minute5_kline(
        trade_date=date.today(),
        source=source,
        symbols=symbols,
        fetch_batch_size=batch_size,
        commit_per_batch=True,
        progress=None,  # Disable progress for accurate timing
    )
    elapsed = time.time() - start

    return {
        "batch_size": batch_size,
        "stock_limit": stock_limit,
        "stock_offset": stock_offset,
        "elapsed_seconds": round(elapsed, 2),
        "target_datetime": result["target_datetime"],
        "success": result["success"],
        "no_data": result["no_data"],
        "failed": result["failed"],
        "inserted_rows": result["inserted_rows"],
        "elapsed_per_stock": round(elapsed / max(1, result["success"]), 3),
        "batches": (result["success"] + batch_size - 1) // batch_size,
        "elapsed_per_batch": round(elapsed / max(1, (result["success"] + batch_size - 1) // batch_size), 2),
    }


def _get_test_symbols(limit: int, offset: int) -> list[str] | None:
    """Get a subset of symbols for testing."""
    from src.data.clickhouse_source import ClickHouseStockDataSource

    client = ClickHouseStockDataSource()._client_instance()
    rows = client.execute(
        f"select symbol, market from stocks final where market in ('SH', 'SZ') order by symbol limit {limit} offset {offset}"
    )
    symbols = [f"{str(code).zfill(6)}.{market}" for code, market in rows]
    return symbols if symbols else None


def run_test_suite(batch_sizes: list[int], stock_limit: int = 2000) -> list[dict]:
    """Run tests for all batch sizes, each using different stock subsets."""
    results = []
    for i, size in enumerate(batch_sizes):
        offset = i * stock_limit  # Each test uses a different subset

        print(f"\n{'='*70}")
        print(f"测试 batch_size={size}, limit={stock_limit}, offset={offset}")
        print(f"{'='*70}")

        try:
            metrics = test_batch_size(size, stock_limit, offset)
            results.append(metrics)

            print(f"耗时: {metrics['elapsed_seconds']}s")
            print(f"成功: {metrics['success']} / {stock_limit}")
            print(f"插入: {metrics['inserted_rows']} 行")
            print(f"批次: {metrics['batches']}")
            print(f"平均每批: {metrics['elapsed_per_batch']}s")
            print(f"每股耗时: {metrics['elapsed_per_stock']}s")

        except Exception as e:
            print(f"错误: {e}")
            results.append({
                "batch_size": size,
                "stock_limit": stock_limit,
                "stock_offset": offset,
                "error": str(e),
            })

    return results


def save_results(results: list[dict], filename: str):
    """Save results to JSON file."""
    output_path = Path(__file__).parent.parent / "logs" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "test_time": datetime.now().isoformat(),
        "trade_date": date.today().isoformat(),
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_path}")


def print_summary(results: list[dict]):
    """Print a summary table of results."""
    print("\n" + "="*100)
    print("性能对比总结")
    print("="*100)
    print(f"{'Batch Size':<12} {'耗时(s)':<10} {'成功数':<10} {'批次':<8} {'每批(s)':<10} {'每股(s)':<10} {'插入行':<10}")
    print("-"*100)

    valid_results = [r for r in results if "error" not in r]
    for r in sorted(valid_results, key=lambda x: x["elapsed_seconds"]):
        print(f"{r['batch_size']:<12} {r['elapsed_seconds']:<10} {r['success']:<10} "
              f"{r['batches']:<8} {r['elapsed_per_batch']:<10} {r['elapsed_per_stock']:<10} "
              f"{r['inserted_rows']:<10}")

    if valid_results:
        best = min(valid_results, key=lambda x: x["elapsed_seconds"])
        print(f"\n最优 batch_size: {best['batch_size']} (耗时 {best['elapsed_seconds']}s)")
    print("="*100)


if __name__ == "__main__":
    # Test different batch sizes
    batch_sizes = [200, 300, 500, 800, 1000]
    stock_limit = 2000  # Test with 2000 stocks for balance

    print(f"\n开始批次阈值测试: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试股票数: {stock_limit}")
    print(f"测试 batch sizes: {batch_sizes}")

    results = run_test_suite(batch_sizes, stock_limit)
    print_summary(results)
    save_results(results, f"batch_size_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    print(f"\n测试完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
