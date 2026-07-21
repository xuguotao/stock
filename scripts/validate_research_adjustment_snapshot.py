#!/usr/bin/env python3
"""Generate a repeatable acceptance report for one research adjustment snapshot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.clickhouse_source import ClickHouseStockDataSource
from src.data.research_adjustment_validation import PRICE_ERROR_TOLERANCE
from src.data.research_adjustment_store import ResearchAdjustmentStore


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate one published research adjustment snapshot.")
    parser.add_argument("--run-id", help="Published run to validate; defaults to the current v1 run.")
    parser.add_argument("--formula-version", default="v1")
    parser.add_argument("--output", type=Path, help="Markdown report path.")
    return parser.parse_args(argv)


def collect_report(client: Any, run_id: str, formula_version: str) -> dict[str, Any]:
    params = {"run": run_id, "formula_version": formula_version}
    run_rows = client.execute(
        """select run_id, formula_version, status, input_ingest_seq
        from research_adjustment_runs final
        where run_id = %(run)s and formula_version = %(formula_version)s
        order by published_at desc limit 1""",
        params,
    )
    if not run_rows:
        raise ValueError(f"research adjustment run not found: {run_id}")
    stored_run_id, stored_formula, status, input_ingest_seq = run_rows[0]
    if status != "published":
        raise ValueError(f"research adjustment run is not published: {run_id}")
    coverage_row = client.execute(
        """select
          (select count() from research_adjustment_raw_bars final where run_id=%(run)s and formula_version=%(formula_version)s),
          (select count() from research_daily_adjustment_factors final where run_id=%(run)s and formula_version=%(formula_version)s),
          (select count() from
             (select symbol, trade_date from research_adjustment_raw_bars final where run_id=%(run)s and formula_version=%(formula_version)s) as raw
             left anti join
             (select symbol, trade_date from research_daily_adjustment_factors final where run_id=%(run)s and formula_version=%(formula_version)s) as factor
             on raw.symbol=factor.symbol and raw.trade_date=factor.trade_date)""",
        params,
    )[0]
    events = _counts_by_status(client, "research_adjustment_events", "validation_status", params)
    factors = _counts_by_status(client, "research_daily_adjustment_factors", "quality_status", params)
    continuity_row = client.execute(
        """select count(), max(abs(validation_error)), quantileExact(0.95)(abs(validation_error))
        from research_adjustment_events final
        where run_id=%(run)s and formula_version=%(formula_version)s
          and validation_status='approved' and validation_error is not null""",
        params,
    )[0]
    nontrivial_row = client.execute(
        """select count(), uniqExact(symbol), min(forward_factor), max(forward_factor)
        from research_daily_adjustment_factors final
        where run_id=%(run)s and formula_version=%(formula_version)s and forward_factor != 1""",
        params,
    )[0]
    sample_rows = client.execute(
        """select symbol, event_date, ratio, abs(validation_error)
        from research_adjustment_events final
        where run_id=%(run)s and formula_version=%(formula_version)s
          and validation_status='approved' and validation_error is not null
        order by abs(validation_error) desc, symbol, event_date limit 20""",
        params,
    )
    return {
        "run": {"run_id": str(stored_run_id), "formula_version": str(stored_formula), "input_ingest_seq": input_ingest_seq},
        "coverage": {"raw_bar_count": int(coverage_row[0]), "factor_count": int(coverage_row[1]), "coverage_mismatch_count": int(coverage_row[2])},
        "events": events,
        "factors": factors,
        "continuity": {"approved_count": int(continuity_row[0]), "max_abs_error": continuity_row[1] or 0.0, "p95_abs_error": continuity_row[2] or 0.0},
        "nontrivial": {"bar_count": int(nontrivial_row[0]), "symbol_count": int(nontrivial_row[1]), "min_forward_factor": nontrivial_row[2] or 1.0, "max_forward_factor": nontrivial_row[3] or 1.0},
        "samples": [{"symbol": str(symbol), "event_date": str(event_date), "ratio": ratio, "abs_error": error} for symbol, event_date, ratio, error in sample_rows],
    }


def render_report(**data: Mapping[str, Any]) -> str:
    coverage = data["coverage"]
    continuity = data["continuity"]
    nontrivial = data["nontrivial"]
    automated_pass = coverage["raw_bar_count"] == coverage["factor_count"] and coverage["coverage_mismatch_count"] == 0
    continuity_attention = float(continuity["p95_abs_error"]) >= PRICE_ERROR_TOLERANCE * 2 / 3
    lines = [
        "# 研究复权准确性验收报告",
        "",
        f"- 快照：`{data['run']['run_id']}`（公式 `{data['run']['formula_version']}`，输入序号 `{data['run']['input_ingest_seq']}`）",
        f"- 自动完整性：{'通过（自动检查）' if automated_pass else '未通过（自动检查）'}",
        "- 外部权威公告核验：待完成",
        "",
        "## 自动检查结果",
        "",
        f"- 原始日线 / 因子行数：{coverage['raw_bar_count']} / {coverage['factor_count']}",
        f"- 原始日线缺少因子：{coverage['coverage_mismatch_count']}",
        f"- 已批准事件：{continuity['approved_count']}；批准事件绝对连续性误差 p95 / 最大值：{float(continuity['p95_abs_error']):.6f} / {float(continuity['max_abs_error']):.6f}",
        f"- 连续性阈值：{PRICE_ERROR_TOLERANCE:.6f}；连续性警戒：{'需要人工复核（p95 接近阈值）' if continuity_attention else '无'}",
        f"- 非 1 前复权因子：{nontrivial['bar_count']} 根、{nontrivial['symbol_count']} 只股票，范围 {float(nontrivial['min_forward_factor']):.6f}–{float(nontrivial['max_forward_factor']):.6f}",
        "",
        "## 事件与因子质量分布",
        "",
        _status_table("事件校验状态", data["events"]),
        "",
        _status_table("因子质量状态", data["factors"]),
        "",
        "## 待外部权威公告核验样本",
        "",
        "以下为连续性误差最大的已批准事件；应逐项对照交易所权益分派公告，确认除权日、分红、送转、配股与配股价。",
        "",
        "| 股票 | 事件日 | 调整率 | 绝对连续性误差 |",
        "| --- | --- | ---: | ---: |",
    ]
    lines.extend(
        f"| {sample['symbol']} | {sample['event_date']} | {float(sample['ratio']):.6f} | {float(sample['abs_error']):.6f} |"
        for sample in data["samples"]
    )
    lines.extend([
        "",
        "## 结论边界",
        "",
        "自动检查证明该快照的行级覆盖、公式结果和内部价格连续性符合当前规则；它不证明 Mootdx 事件字段与交易所公告完全一致，也不单独证明日线一定是未复权口径。外部公告抽样对账和原始日线口径交叉核验完成前，不应把本报告视为最终准确性认证。",
        "",
    ])
    return "\n".join(lines)


def _counts_by_status(client: Any, table: str, column: str, params: Mapping[str, Any]) -> dict[str, int]:
    rows = client.execute(
        f"select {column}, count() from {table} final where run_id=%(run)s and formula_version=%(formula_version)s group by {column}",
        params,
    )
    return {str(status): int(count) for status, count in rows}


def _status_table(title: str, counts: Mapping[str, int]) -> str:
    lines = [f"### {title}", "", "| 状态 | 数量 |", "| --- | ---: |"]
    lines.extend(f"| {status} | {count} |" for status, count in sorted(counts.items()))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    client = ClickHouseStockDataSource()._client_instance()
    if args.run_id:
        run_id = args.run_id
    else:
        current = ResearchAdjustmentStore(client=client).current_run(args.formula_version)
        if current is None:
            raise ValueError(f"no published research adjustment run for {args.formula_version}")
        run_id = str(current["run_id"])
    report = render_report(**collect_report(client, run_id, args.formula_version))
    output = args.output or Path("reports/research_adjustment") / f"validation-{run_id}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
