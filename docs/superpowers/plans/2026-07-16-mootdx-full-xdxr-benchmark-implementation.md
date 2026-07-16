# Mootdx 全量 XDXR 基准 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供可重复的只读全股票池 XDXR 基准、失败分布和可归档 JSON 报告，并运行一次真实全量测量。

**Architecture:** 保留默认 300 标的抽样，将全量选择作为显式 `--all` 模式。读诊断集中计算总体、市场桶、错误聚合和有限失败样本；CLI 负责参数互斥、JSON 输出及可选文件归档。

**Tech Stack:** Python 3.13、argparse、pandas、pytest、Mootdx（只读网络请求）。

---

### Task 1: 全量模式与可归档诊断

**Files:**

- Modify: `scripts/benchmark_mootdx_xdxr.py`
- Modify: `tests/test_scripts/test_benchmark_mootdx_xdxr.py`

- [ ] **Step 1: 写入失败的 CLI/诊断契约测试**

```python
def test_all_mode_selects_entire_catalog_and_writes_matching_json(tmp_path, capsys) -> None:
    source = FakeSource()
    output = tmp_path / "benchmark.json"
    assert benchmark_mootdx_xdxr.main(["--all", "--output", str(output)], source_factory=lambda **_: source) == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout == json.loads(output.read_text())
    assert stdout["sample_count"] == stdout["catalog_size"] == 7
    assert stdout["selection_mode"] == "all"

def test_read_only_diagnostics_groups_failures_by_bucket_and_error() -> None:
    diagnostics = benchmark_mootdx_xdxr._read_only_diagnostics(FakeSource(), ["300001.SZ"])
    assert diagnostics["bucket_results"]["chi_next"]["error_count"] == 1
    assert diagnostics["error_types"] == {"RuntimeError: source unavailable": 1}
```

- [ ] **Step 2: 运行新增测试并确认失败**

Run: `uv run --no-sync pytest -q tests/test_scripts/test_benchmark_mootdx_xdxr.py -k 'all_mode or groups_failures'`

Expected: FAIL，因为 CLI 尚无 `--all` / `--output`，诊断也尚无失败分布字段。

- [ ] **Step 3: 实现最小 CLI 与诊断增强**

新增 `--all` 与 `--output`。`--all` 选择完整目录、不能与显式 `--sample-size` 或 `--write` 同用；输出 JSON 只序列化一次，打印并可选择写入文件。只读诊断增加 `selection_mode`、`bucket_results`、`error_types`、`failed_symbols_sample`。

- [ ] **Step 4: 运行脚本测试**

Run: `uv run --no-sync pytest -q tests/test_scripts/test_benchmark_mootdx_xdxr.py`

Expected: PASS.

- [ ] **Step 5: 提交实现**

Run: `git add scripts/benchmark_mootdx_xdxr.py tests/test_scripts/test_benchmark_mootdx_xdxr.py && git commit -m "feat: report full Mootdx XDXR benchmark diagnostics"`

### Task 2: 真实全量只读运行与归档

**Files:**

- Create: `reports/mootdx_probe/xdxr_full_benchmark_2026-07-16.json`
- Modify: `docs/notes/mootdx-xdxr-interface-test-2026-07-13.md`

- [ ] **Step 1: 运行真实全量只读基准并写报告**

Run: `uv run --no-sync python scripts/benchmark_mootdx_xdxr.py --all --rate-limit 0.02 --timeout 10 --output reports/mootdx_probe/xdxr_full_benchmark_2026-07-16.json`

Expected: 命令退出码为 0，并记录目录规模、成功/空/错误、P50/P95/P99、市场桶和失败样本。即使出现源端错误，也不得换服务器、提高超时或重跑以掩盖该次观测。

- [ ] **Step 2: 验证归档报告结构**

Run: `uv run --no-sync python -c "import json; p=json.load(open('reports/mootdx_probe/xdxr_full_benchmark_2026-07-16.json')); assert p['mode']=='read_only' and p['selection_mode']=='all'; assert p['sample_count']==p['catalog_size']; assert set(p) >= {'p50_ms','p95_ms','p99_ms','bucket_results','error_types','failed_symbols_sample'}"`

Expected: PASS.

- [ ] **Step 3: 将实测数字和限制写入接口说明**

在 `docs/notes/mootdx-xdxr-interface-test-2026-07-13.md` 的 300 标的基准后新增“全量只读基准（2026-07-16）”，引用归档 JSON 的实际数值，明确它是单次观测，不证明长期可用性或复权公式。

- [ ] **Step 4: 提交实测报告与说明**

Run: `git add reports/mootdx_probe/xdxr_full_benchmark_2026-07-16.json docs/notes/mootdx-xdxr-interface-test-2026-07-13.md && git commit -m "docs: record full Mootdx XDXR benchmark"`

### Task 3: 最终验证

**Files:**

- No production changes expected

- [ ] **Step 1: 运行完整脚本测试**

Run: `uv run --no-sync pytest -q tests/test_scripts/test_benchmark_mootdx_xdxr.py`

Expected: PASS.

- [ ] **Step 2: 检查提交内容**

Run: `git diff main...HEAD --check && git status --short && git log --oneline main..HEAD`

Expected: 无空白错误、工作区干净，且包含设计、实现与实测报告的提交。
