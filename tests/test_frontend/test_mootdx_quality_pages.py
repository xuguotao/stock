from pathlib import Path
import subprocess


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
    typescript = (Path.cwd().parents[1] / "frontend/node_modules/typescript/lib/typescript.js").resolve()
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
        '"verify":[{"symbol":"002005.SZ","start_date":"2026-06-03","end_date":"2026-07-13","evidence":"连续缺口"}]}'
    )


def test_mootdx_monitor_uses_chinese_status_labels() -> None:
    source = Path("frontend/src/pages/MootdxMonitor.vue").read_text(encoding="utf-8")
    formatter = Path("frontend/src/features/mootdx/formatters.ts").read_text(encoding="utf-8")

    assert "mootdxStatusText" in source
    assert "已知无数据" in source
    assert "mootdxAuditReasonText" in source
    assert "degraded: '待关注'" in formatter
    assert "healthy: '健康'" in formatter
    assert "coverage_below_target: '完整度低于 99.50% 健康目标'" in formatter
