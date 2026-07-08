"""Monitor batch size test progress."""
import json
import sys
from datetime import datetime
from pathlib import Path

def show_progress():
    """Show current test progress."""
    # Find latest test file
    logs_dir = Path(__file__).parent.parent / "logs"
    today = datetime.now().strftime("%Y%m%d")
    test_file = logs_dir / f"batch_size_test_allday_{today}.json"

    if not test_file.exists():
        print(f"测试文件不存在: {test_file}")
        print("全天测试可能还未开始或尚未完成第一轮测试")
        return

    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])

    # Count completed rounds
    rounds = {}
    for r in results:
        round_num = r.get("test_round", 0)
        if round_num not in rounds:
            rounds[round_num] = []
        rounds[round_num].append(r)

    print(f"\n{'='*70}")
    print(f"全天批次阈值测试进度")
    print(f"{'='*70}")
    print(f"测试日期: {data.get('test_date', 'unknown')}")
    print(f"总测试次数: {len(results)}")
    print(f"完成轮次: {len(rounds)}")

    # Show latest round summary
    if rounds:
        latest_round = max(rounds.keys())
        latest_results = rounds[latest_round]

        print(f"\n最近一轮 (轮次 {latest_round}):")
        print(f"{'Batch Size':<12} {'耗时(s)':<10} {'成功数':<10} {'批次':<8} {'每批(s)':<10}")
        print("-"*50)

        for r in sorted(latest_results, key=lambda x: x.get("elapsed_seconds", 0)):
            if "error" in r:
                print(f"{r['batch_size']:<12} ERROR: {r['error']}")
            else:
                print(f"{r['batch_size']:<12} {r['elapsed_seconds']:<10} {r['success']:<10} "
                      f"{r['batches']:<8} {r['elapsed_per_batch']:<10}")

    # Show overall summary if we have enough data
    if len(results) >= 10:
        by_batch = {}
        for r in results:
            if "error" in r:
                continue
            size = r["batch_size"]
            if size not in by_batch:
                by_batch[size] = []
            by_batch[size].append(r["elapsed_seconds"])

        print(f"\n{'='*70}")
        print("当前最优（基于所有测试）:")
        print(f"{'='*70}")
        print(f"{'Batch Size':<12} {'测试次数':<10} {'平均耗时':<12} {'最快':<10}")
        print("-"*50)

        for size in sorted(by_batch.keys()):
            times = by_batch[size]
            avg_time = sum(times) / len(times)
            min_time = min(times)
            print(f"{size:<12} {len(times):<10} {avg_time:<12.2f} {min_time:<10.2f}")

        best_size = min(by_batch.keys(), key=lambda s: sum(by_batch[s])/len(by_batch[s]))
        print(f"\n当前最优 batch_size: {best_size}")

    print(f"{'='*70}\n")


if __name__ == "__main__":
    show_progress()
