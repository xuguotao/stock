"""Fund tail-session opportunity discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class FundCandidate:
    """A fund that may be considered by the tail-session opportunity scanner."""

    fund_code: str
    fund_name: str
    fund_type: str
    candidate_tier: str
    proxy_provider: str
    proxy_code: str
    fee_tag: str
    min_holding_days: int
    enabled: bool
    tail_strategy_eligible: bool
    exclude_reason: str = ""


def load_candidates(source: str | Path | pd.DataFrame) -> list[FundCandidate]:
    """Load candidate funds from a CSV path or dataframe."""
    frame = pd.read_csv(source, dtype={"fund_code": str, "proxy_code": str}) if not isinstance(source, pd.DataFrame) else source
    candidates: list[FundCandidate] = []
    for raw in frame.fillna("").to_dict(orient="records"):
        candidates.append(
            FundCandidate(
                fund_code=str(raw["fund_code"]).strip().zfill(6),
                fund_name=str(raw["fund_name"]).strip(),
                fund_type=str(raw.get("fund_type", "other")).strip() or "other",
                candidate_tier=str(raw.get("candidate_tier", "cautious")).strip() or "cautious",
                proxy_provider=str(raw.get("proxy_provider", "nav")).strip() or "nav",
                proxy_code=str(raw.get("proxy_code", raw["fund_code"])).strip(),
                fee_tag=str(raw.get("fee_tag", "普通费率")).strip() or "普通费率",
                min_holding_days=_to_int(raw.get("min_holding_days"), default=7),
                enabled=_to_bool(raw.get("enabled", True)),
                tail_strategy_eligible=_to_bool(raw.get("tail_strategy_eligible", True)),
                exclude_reason=str(raw.get("exclude_reason", "")).strip(),
            )
        )
    return candidates


def filter_eligible_candidates(candidates: Iterable[FundCandidate]) -> list[FundCandidate]:
    """Keep candidates that are enabled and suitable for tail-session decisions."""
    excluded_types = {"money", "bond", "pure_bond", "cash"}
    eligible = []
    for candidate in candidates:
        if not candidate.enabled or not candidate.tail_strategy_eligible:
            continue
        if candidate.fund_type in excluded_types:
            continue
        if candidate.candidate_tier == "excluded":
            continue
        eligible.append(candidate)
    return eligible


def build_opportunity_rows(
    chinese_report: pd.DataFrame,
    candidates: Iterable[FundCandidate],
    *,
    watchlist_codes: set[str] | None = None,
) -> list[dict[str, object]]:
    """Decorate existing Chinese fund-tail rows with opportunity discovery fields."""
    candidate_by_code = {candidate.fund_code: candidate for candidate in candidates}
    watchlist_codes = {str(code).zfill(6) for code in (watchlist_codes or set())}
    rows = []
    for raw in chinese_report.fillna("").to_dict(orient="records"):
        code = str(raw.get("基金代码", "")).zfill(6)
        candidate = candidate_by_code.get(code)
        if candidate is None:
            continue
        row = dict(raw)
        row.update(classify_opportunity(row, candidate, watchlist_codes))
        rows.append(row)
    return sorted(rows, key=_sort_key)


def build_opportunity_markdown(rows: list[dict[str, object]], *, trade_date: str) -> str:
    """Build a concise Chinese opportunity discovery Markdown report."""
    actionable = [row for row in rows if row.get("机会类型") in {"新开仓候选", "已在观察池"}]
    if actionable:
        names = "、".join(str(row.get("基金名称", "")) for row in actionable[:8])
        summary = f"总判断：今日可重点观察 {names}；新开仓仍按小额试探处理。"
    else:
        summary = "总判断：今日没有明确的新开仓机会，优先等待回踩或数据确认。"

    lines = [
        f"# 基金尾盘机会发现 - {trade_date}",
        "",
        summary,
        "",
        "| 基金 | 代码 | 机会类型 | 机会等级 | 机会建议 | 评分 | 5日胜率 | 5日中位收益 | 跌超2% | 原因 |",
        "|---|---:|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {name} | {code} | {otype} | {grade} | {advice} | {score} | {win5} | {median5} | {risk5} | {reason} |".format(
                name=row.get("基金名称", ""),
                code=str(row.get("基金代码", "")).zfill(6),
                otype=row.get("机会类型", ""),
                grade=row.get("机会等级", ""),
                advice=row.get("机会建议", ""),
                score=row.get("预测加仓评分", ""),
                win5=_pct(row.get("5日预测上涨概率", "")),
                median5=_pct(row.get("5日预测中位数收益", "")),
                risk5=_pct(row.get("5日预测跌超2%概率", "")),
                reason=row.get("机会原因", ""),
            )
        )
    lines.extend(
        [
            "",
            "## 使用原则",
            "",
            "- 新开仓候选只代表进入观察和小额试探，不代表满仓买入。",
            "- 代理匹配低、数据滞后、费率不适合短线的基金不参与尾盘策略。",
            "- 这不是保证收益的投资建议，只作为基金尾盘筛选辅助。",
            "",
        ]
    )
    return "\n".join(lines)


def classify_opportunity(
    row: dict[str, object],
    candidate: FundCandidate,
    watchlist_codes: set[str],
) -> dict[str, object]:
    """Classify a decorated Chinese report row into opportunity buckets."""
    grade = str(row.get("操作等级", "D"))
    action = str(row.get("最终操作建议", ""))
    reason = str(row.get("建议原因", "")) or candidate.exclude_reason
    proxy_fit_level = str(row.get("代理匹配等级", ""))
    in_watchlist = candidate.fund_code in watchlist_codes

    if not candidate.tail_strategy_eligible or candidate.candidate_tier == "excluded":
        opportunity_type = "明确排除"
        opportunity_grade = "D"
        opportunity_advice = "不参与"
        opportunity_reason = candidate.exclude_reason or "候选池规则排除"
    elif proxy_fit_level in {"低", "low"}:
        opportunity_type = "明确排除"
        opportunity_grade = "D"
        opportunity_advice = "不参与"
        opportunity_reason = "代理匹配度低"
    elif grade in {"A", "B"} and action in {"尾盘加仓", "小额试探"}:
        opportunity_type = "已在观察池" if in_watchlist else "新开仓候选"
        opportunity_grade = grade
        opportunity_advice = "已有池内小额加仓观察" if in_watchlist else _new_entry_advice(grade)
        opportunity_reason = reason
    elif action in {"等待回踩", "持有观察"}:
        opportunity_type = "已在观察池" if in_watchlist else "观察候选"
        opportunity_grade = grade if grade in {"A", "B", "C"} else "C"
        opportunity_advice = action
        opportunity_reason = reason
    else:
        opportunity_type = "明确排除"
        opportunity_grade = "D"
        opportunity_advice = "不参与"
        opportunity_reason = reason or "预测优势不足"

    return {
        "机会类型": opportunity_type,
        "机会等级": opportunity_grade,
        "机会建议": opportunity_advice,
        "机会原因": opportunity_reason,
        "是否已在观察池": "是" if in_watchlist else "否",
        "费率标签": candidate.fee_tag,
        "最短观察周期": f"{candidate.min_holding_days}天",
        "候选层级": _tier_text(candidate.candidate_tier),
        "基金类型标签": _fund_type_text(candidate.fund_type),
    }


def _new_entry_advice(grade: str) -> str:
    return "可小额新开仓"


def _sort_key(row: dict[str, object]) -> tuple[int, float]:
    type_rank = {
        "新开仓候选": 0,
        "已在观察池": 1,
        "观察候选": 2,
        "明确排除": 3,
    }.get(str(row.get("机会类型")), 4)
    return (type_rank, -_to_float(row.get("预测加仓评分")))


def _tier_text(value: str) -> str:
    return {
        "preferred": "优先池",
        "cautious": "谨慎池",
        "excluded": "排除池",
    }.get(value, value or "-")


def _fund_type_text(value: str) -> str:
    return {
        "broad_index": "宽基",
        "sector": "行业",
        "consumer": "消费",
        "medical": "医药",
        "overseas": "海外",
        "active_mixed": "主动混合",
        "other": "其他",
    }.get(value, value or "其他")


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "启用"}


def _to_int(value: object, *, default: int) -> int:
    try:
        text = str(value).strip()
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def _to_float(value: object) -> float:
    try:
        text = str(value).strip()
        if text.endswith("%"):
            return float(text[:-1]) / 100
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _pct(value: object) -> str:
    try:
        text = str(value).strip()
        if text.endswith("%"):
            return text
        return f"{float(text) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"
