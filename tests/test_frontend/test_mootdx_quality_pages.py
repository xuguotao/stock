import json
from pathlib import Path
import subprocess


def _workspace_path(relative_path: str) -> Path:
    for root in (Path.cwd(), *Path.cwd().parents):
        candidate = root / relative_path
        if candidate.exists():
            return candidate
    raise FileNotFoundError(relative_path)


def test_daily_quality_page_explains_degraded_coverage_in_chinese() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text(encoding="utf-8")
    formatter = Path("frontend/src/features/mootdx/formatters.ts").read_text(encoding="utf-8")

    assert "mootdxStatusText" in source
    assert "degraded: '待关注'" in formatter
    assert "完整度低于 99.50% 健康目标" in source
    assert "mootdxStatusText" in source


def test_daily_quality_page_filters_gap_queue_by_selected_trade_date() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text(encoding="utf-8")

    assert "selectedTradeDate" in source
    assert "missing_dates.includes(selectedTradeDate.value)" in source
    assert "查询交易日" in source
    assert "api.getMootdxDailyQuality(lookbackDays.value, 1000)" in source
    assert "coverage-strip" in source
    assert "coverage-day" in source
    assert '@click="selectTradeDate(coverage.trade_date)"' in source


def test_daily_quality_client_contract_includes_per_date_verification_verdicts() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "verification_by_date: Record<string, 'available' | 'no_data' | 'error' | ''>" in client


def test_daily_quality_page_places_selected_day_metrics_with_the_date_query() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text(encoding="utf-8")

    assert 'class="selected-day-summary"' in source
    assert '目录预期' in source
    assert '实际日线' in source
    assert '物理缺失' in source
    assert '待处理缺口' in source
    assert '有效覆盖' in source
    assert 'effectiveCoverageRate' in source
    assert '观察窗口概览' in source
    assert 'selectedCoverage?.actual_symbols' in source


def test_daily_gap_payloads_verify_the_full_gap_block_but_repair_selected_day_only() -> None:
    helper = Path("frontend/src/features/mootdx/dailyGapPayloads.ts").resolve()
    typescript = _workspace_path("frontend/node_modules/typescript/lib/typescript.js")
    script = """
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
const ts = await import(pathToFileURL(process.argv[2]).href)
const source = await readFile(process.argv[1], 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { createDailyGapRepairPayload, createDailyGapVerifyPayload } = await import(`data:text/javascript,${encodeURIComponent(compiled.outputText)}`)
const items = [{
  symbol: '002005.SZ',
  evidence: '连续缺口',
  missing_dates: ['2026-07-13'],
  block_missing_dates: ['2026-06-03', '2026-06-04', '2026-07-13'],
}]
console.log(JSON.stringify({
  repair: createDailyGapRepairPayload(items, '2026-07-13'),
  verify: createDailyGapVerifyPayload(items),
}))
"""

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(helper), str(typescript)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == (
        '{"repair":[{"symbol":"002005.SZ","start_date":"2026-07-13","end_date":"2026-07-13","evidence":"连续缺口"}],'
        '"verify":[{"symbol":"002005.SZ","start_date":"2026-06-03","end_date":"2026-07-13","evidence":"连续缺口","trade_dates":["2026-06-03","2026-06-04","2026-07-13"]}]}'
    )


def test_daily_gap_payloads_create_precise_repairs_only_for_available_verdicts() -> None:
    helper = Path("frontend/src/features/mootdx/dailyGapPayloads.ts").resolve()
    typescript = _workspace_path("frontend/node_modules/typescript/lib/typescript.js")
    script = """
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
const ts = await import(pathToFileURL(process.argv[2]).href)
const source = await readFile(process.argv[1], 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { createDailyGapPreciseRepairPayload } = await import(`data:text/javascript,${encodeURIComponent(compiled.outputText)}`)
const dates = [...Array.from({ length: 27 }, (_, index) => `2026-06-${String(index + 3).padStart(2, '0')}`), '2026-07-13']
const items = [{
  symbol: '002005.SZ',
  evidence: '连续缺口',
  missing_dates: ['2026-07-13'],
  block_missing_dates: dates,
  verification_by_date: Object.fromEntries(dates.map((date) => [date, date === '2026-07-13' ? 'no_data' : 'available'])),
}, {
  symbol: '000001.SZ',
  evidence: '无可回补日期',
  missing_dates: ['2026-07-12'],
  block_missing_dates: ['2026-07-11', '2026-07-12'],
  verification_by_date: { '2026-07-11': 'error', '2026-07-12': '' },
}]
console.log(JSON.stringify(createDailyGapPreciseRepairPayload(items)))
"""

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(helper), str(typescript)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert len(payload) == 27
    assert {item["start_date"] for item in payload} == {f"2026-06-{day:02d}" for day in range(3, 30)}
    assert all(item["start_date"] == item["end_date"] for item in payload)


def test_daily_gap_payloads_batch_precise_repairs_at_the_backend_limit() -> None:
    helper = Path("frontend/src/features/mootdx/dailyGapPayloads.ts").resolve()
    typescript = _workspace_path("frontend/node_modules/typescript/lib/typescript.js")
    script = """
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
const ts = await import(pathToFileURL(process.argv[2]).href)
const source = await readFile(process.argv[1], 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { createDailyGapPreciseRepairBatches } = await import(`data:text/javascript,${encodeURIComponent(compiled.outputText)}`)
const dates = Array.from({ length: 101 }, (_, index) => `2026-08-${String(index + 1).padStart(3, '0')}`)
const items = [{
  symbol: '002005.SZ',
  evidence: '连续缺口',
  missing_dates: ['2026-08-101'],
  block_missing_dates: dates,
  verification_by_date: Object.fromEntries(dates.map((date) => [date, 'available'])),
}]
console.log(JSON.stringify(createDailyGapPreciseRepairBatches(items).map((batch) => batch.length)))
"""

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(helper), str(typescript)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [100, 1]


def test_daily_gap_payloads_wait_for_each_batch_terminal_status_before_submitting_next() -> None:
    helper = Path("frontend/src/features/mootdx/dailyGapPayloads.ts").resolve()
    typescript = _workspace_path("frontend/node_modules/typescript/lib/typescript.js")
    script = """
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
const ts = await import(pathToFileURL(process.argv[2]).href)
const source = await readFile(process.argv[1], 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { runDailyGapRepairBatches, waitForDailyGapTerminalJob } = await import(`data:text/javascript,${encodeURIComponent(compiled.outputText)}`)
const batches = [[{ symbol: '002005.SZ' }], [{ symbol: '000001.SZ' }]]
const submitted = []
const statuses = ['pending', 'success', 'success']
const result = await runDailyGapRepairBatches(
  batches,
  async (batch) => { submitted.push(batch[0].symbol); return `job-${submitted.length}` },
  async () => waitForDailyGapTerminalJob(async () => ({ status: statuses.shift() }), async () => {}),
)
console.log(JSON.stringify({ submitted, result }))
"""

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(helper), str(typescript)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "submitted": ["002005.SZ", "000001.SZ"],
        "result": {"completed_batches": 2, "failed_batch_index": None, "failed_status": None},
    }


def test_daily_gap_payloads_stop_batch_submission_after_a_terminal_failure() -> None:
    helper = Path("frontend/src/features/mootdx/dailyGapPayloads.ts").resolve()
    typescript = _workspace_path("frontend/node_modules/typescript/lib/typescript.js")
    script = """
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
const ts = await import(pathToFileURL(process.argv[2]).href)
const source = await readFile(process.argv[1], 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { runDailyGapRepairBatches, waitForDailyGapTerminalJob } = await import(`data:text/javascript,${encodeURIComponent(compiled.outputText)}`)
const batches = [[{ symbol: '002005.SZ' }], [{ symbol: '000001.SZ' }]]
const submitted = []
const statuses = ['pending', 'failed']
const result = await runDailyGapRepairBatches(
  batches,
  async (batch) => { submitted.push(batch[0].symbol); return `job-${submitted.length}` },
  async () => waitForDailyGapTerminalJob(async () => ({ status: statuses.shift() }), async () => {}),
)
console.log(JSON.stringify({ submitted, result }))
"""

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(helper), str(typescript)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "submitted": ["002005.SZ"],
        "result": {"completed_batches": 0, "failed_batch_index": 0, "failed_status": "failed"},
    }


def test_daily_quality_page_offers_precise_repair_for_verified_available_dates() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text(encoding="utf-8")

    assert "创建精准回补（{{ preciseRepairItems.length }} 日）" in source
    assert "createDailyGapPreciseRepairPayload" in source
    assert "verifiedAvailableDateCount" in source
    assert "verifiedNoDataDateCount" in source
    assert "createDailyGapPreciseRepairBatches" in source
    assert "精准回补共" in source


def test_daily_gap_payloads_restore_verified_selection_after_refresh() -> None:
    helper = Path("frontend/src/features/mootdx/dailyGapPayloads.ts").resolve()
    typescript = _workspace_path("frontend/node_modules/typescript/lib/typescript.js")
    script = """
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
const ts = await import(pathToFileURL(process.argv[2]).href)
const source = await readFile(process.argv[1], 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { restoreDailyGapSelection } = await import(`data:text/javascript,${encodeURIComponent(compiled.outputText)}`)
const rows = [
  { symbol: '002005.SZ', block_missing_dates: ['2026-06-03'], verification_by_date: {} },
  { symbol: '000001.SZ', block_missing_dates: ['2026-06-03'], verification_by_date: {} },
]
console.log(JSON.stringify(restoreDailyGapSelection(rows, ['002005.SZ'])))
"""

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(helper), str(typescript)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [{"symbol": "002005.SZ", "block_missing_dates": ["2026-06-03"], "verification_by_date": {}}]


def test_daily_quality_page_reselects_verified_rows_after_the_job_refresh() -> None:
    source = Path("frontend/src/pages/DailyKlineQuality.vue").read_text(encoding="utf-8")

    assert "restoreDailyGapSelection" in source
    assert "trackJob(result.job_id, selectedVerifyItems.value.map(item => item.symbol), selectedTradeDate.value)" in source
    assert "async function load(selectedSymbols: string[] = [], selectionTradeDate = '')" in source


def test_mootdx_monitor_uses_chinese_status_labels() -> None:
    source = Path("frontend/src/pages/MootdxMonitor.vue").read_text(encoding="utf-8")
    formatter = Path("frontend/src/features/mootdx/formatters.ts").read_text(encoding="utf-8")

    assert "mootdxStatusText" in source
    assert "已知无数据" in source
    assert "mootdxAuditReasonText" in source
    assert "degraded: '待关注'" in formatter
    assert "healthy: '健康'" in formatter
    assert "coverage_below_target: '完整度低于 99.50% 健康目标'" in formatter
