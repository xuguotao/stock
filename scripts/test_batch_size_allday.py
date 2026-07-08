"""Run batch size threshold tests throughout the trading day."""
import sys
import time
import json
from datetime import date, datetime, time as dt_time
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.test_batch_size_threshold import run_test_suite, save_results


def is_market_hours() -> bool:
    """Check if current time is within market hours."""
    now = datetime.now().time()
    morning = (dt_time(9, 30), dt_time(11, 30))
    afternoon = (dt_time(13, 0), dt_time(15, 0))
    return (morning[0] <= now <= morning[1]) or (afternoon[0] <= now <= afternoon[1])


def run_periodic_test(interval_minutes: int = 30, stock_limit: int = 2000):
    """Run tests periodically during market hours."""
    batch_sizes = [200, 300, 500, 800, 1000]
    all_results = []
    test_round = 0

    print(f"\n{'='*70}")
    print(f"开始全天批次阈值测试: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试间隔: {interval_minutes} 分钟")
    print(f"测试股票数: {stock_limit}")
    print(f"测试 batch sizes: {batch_sizes}")
    print(f"{'='*70}\n")

    while True:
        now = datetime.now()

        # Stop at 15:05 (after market close)
        if now.time() > dt_time(15, 5):
            print(f"\n15:05 已过，测试结束: {now.strftime('%H:%M:%S')}")
            break

        # Only run during market hours
        if not is_market_hours():
            print(f"[{now.strftime('%H:%M:%S')}] 非交易时段，等待...")
            time.sleep(60)  # Wait 1 minute
            continue

        # Run test round
        test_round += 1
        print(f"\n{'#'*70}")
        print(f"# 测试轮次 {test_round} - {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#'*70}")

        try:
            results = run_test_suite(batch_sizes, stock_limit)

            # Add timestamp to results
            for r in results:
                r["test_round"] = test_round
                r["test_time"] = now.isoformat()

            all_results.extend(results)

            # Save intermediate results
            output_file = f"batch_size_test_allday_{date.today().strftime('%Y%m%d')}.json"
            save_results(all_results, output_file)

            print(f"\n[完成] 轮次 {test_round} 已保存")

        except Exception as e:
            print(f"\n[错误] 轮次 {test_round} 失败: {e}")

        # Wait for next interval
        print(f"\n等待 {interval_minutes} 分钟后进行下一轮测试...")
        time.sleep(interval_minutes * 60)

    # Final summary
    generate_final_summary(all_results)


def generate_final_summary(all_results: list[dict]):
    """Generate a final summary of all test results."""
    print(f"\n{'='*70}")
    print("全天测试总结")
    print(f"{'='*70}")

    # Group by batch size
    by_batch = {}
    for r in all_results:
        if "error" in r:
            continue
        size = r["batch_size"]
        if size not in by_batch:
            by_batch[size] = []
        by_batch[size].append(r)

    # Calculate averages
    print(f"\n{'Batch Size':<12} {'测试次数':<10} {'平均耗时':<12} {'最快':<10} {'最慢':<10} {'平均每股':<12}")
    print("-"*70)

    summary_data = []
    for size in sorted(by_batch.keys()):
        results = by_batch[size]
        times = [r["elapsed_seconds"] for r in results]
        per_stock = [r["elapsed_per_stock"] for r in results]

        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        avg_per_stock = sum(per_stock) / len(per_stock)

        summary_data.append({
            "batch_size": size,
            "test_count": len(results),
            "avg_elapsed": round(avg_time, 2),
            "min_elapsed": round(min_time, 2),
            "max_elapsed": round(max_time, 2),
            "avg_per_stock": round(avg_per_stock, 4),
        })

        print(f"{size:<12} {len(results):<10} {avg_time:<12.2f} {min_time:<10.2f} {max_time:<10.2f} {avg_per_stock:<12.4f}")

    # Find best batch size
    if summary_data:
        best = min(summary_data, key=lambda x: x["avg_elapsed"])
        print(f"\n最优 batch_size: {best['batch_size']} (平均耗时 {best['avg_elapsed']}s)")

    # Save final summary
    output_file = f"batch_size_test_summary_{date.today().strftime('%Y%m%d')}.json"
    output_path = Path(__file__).parent.parent / "logs" / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = {
        "test_date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(),
        "total_tests": len(all_results),
        "summary_by_batch_size": summary_data,
        "all_results": all_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n总结已保存到: {output_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    # Default: run every 30 minutes with 2000 stocks
    interval = 30
    stock_limit = 2000

    # Parse command line args
    if len(sys.argv) > 1:
        interval = int(sys.argv[1])
    if len(sys.argv) > 2:
        stock_limit = int(sys.argv[2])

    run_periodic_test(interval, stock_limit)
