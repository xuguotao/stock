#!/usr/bin/env python
"""Build a broad fund-tail candidate universe from AKShare fund metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_fund_tail_advice import FUNDS, PROXY_INDEXES


COLUMNS = [
    "fund_code",
    "fund_name",
    "fund_type",
    "candidate_tier",
    "proxy_provider",
    "proxy_code",
    "fee_tag",
    "min_holding_days",
    "enabled",
    "tail_strategy_eligible",
    "exclude_reason",
]

EXCLUDED_TYPE_KEYWORDS = ("债券", "货币", "商品", "REIT", "FOF")
UNMAPPED_ASSET_KEYWORDS = ("恒生", "港股", "黄金", "白银", "原油", "油气", "房地产")

PROXY_RULES = [
    ("半导体芯片", "sector", "cni", "980017"),
    ("国证半导体", "sector", "cni", "980017"),
    ("国证芯片", "sector", "cni", "980017"),
    ("芯片", "sector", "cni", "980017"),
    ("半导体", "sector", "cni", "980017"),
    ("新能源汽车", "sector", "csindex", "399976"),
    ("新能源车", "sector", "csindex", "399976"),
    ("医疗", "medical", "csindex", "399989"),
    ("医药", "medical", "csindex", "399989"),
    ("食品饮料", "consumer", "cni", "399396"),
    ("主要消费", "consumer", "cni", "399396"),
    ("消费", "consumer", "cni", "399396"),
    ("中证500", "broad_index", "csindex", "000905"),
    ("中证1000", "broad_index", "csindex", "000852"),
    ("沪深300", "broad_index", "csindex", "000300"),
    ("深证100", "broad_index", "cni", "399330"),
    ("创业板", "broad_index", "cni", "399006"),
    ("上证50", "broad_index", "csindex", "000016"),
    ("科创50", "broad_index", "csindex", "000688"),
    ("环保", "sector", "csindex", "000827"),
    ("纳斯达克", "overseas", "us_sina", "QQQ"),
    ("纳指", "overseas", "us_sina", "QQQ"),
]


def build_candidate_rows(source: pd.DataFrame, *, limit: int = 240) -> list[dict[str, object]]:
    """Create tail-strategy candidate rows from AKShare fund-name metadata."""
    rows_by_code: dict[str, dict[str, object]] = {}
    for raw in source.fillna("").to_dict(orient="records"):
        code = str(raw.get("基金代码", "")).strip().zfill(6)
        name = str(raw.get("基金简称", "")).strip()
        fund_kind = str(raw.get("基金类型", "")).strip()
        if not code or not name:
            continue
        if code in rows_by_code:
            continue
        row = candidate_row_for(code, name, fund_kind)
        if row is None:
            continue
        rows_by_code[code] = row

    return sorted(rows_by_code.values(), key=_sort_key)[:limit]


def candidate_row_for(code: str, name: str, fund_kind: str) -> dict[str, object] | None:
    if any(keyword in fund_kind or keyword in name for keyword in EXCLUDED_TYPE_KEYWORDS):
        return None

    builtin_proxy = PROXY_INDEXES.get(code)
    if builtin_proxy is not None:
        fund_type = _fund_type_from_name(name)
        provider, proxy_code, *_ = builtin_proxy
    else:
        matched = _match_proxy(name)
        if matched is not None:
            fund_type, provider, proxy_code = matched
        elif "QDII" in fund_kind or "QDII" in name or any(keyword in name for keyword in UNMAPPED_ASSET_KEYWORDS):
            return None
        elif _is_equity_or_mixed(fund_kind):
            fund_type, provider, proxy_code = "active_mixed", "csindex", "000300"
        else:
            return None

    return {
        "fund_code": code,
        "fund_name": FUNDS.get(code, name),
        "fund_type": fund_type,
        "candidate_tier": _candidate_tier(code, name, fund_type),
        "proxy_provider": provider,
        "proxy_code": proxy_code,
        "fee_tag": _fee_tag(name),
        "min_holding_days": 7,
        "enabled": "true",
        "tail_strategy_eligible": "true",
        "exclude_reason": "",
    }


def _match_proxy(name: str) -> tuple[str, str, str] | None:
    for keyword, fund_type, provider, proxy_code in PROXY_RULES:
        if keyword in name:
            return fund_type, provider, proxy_code
    return None


def _fund_type_from_name(name: str) -> str:
    matched = _match_proxy(name)
    if matched is not None:
        return matched[0]
    return "active_mixed"


def _is_equity_or_mixed(fund_kind: str) -> bool:
    return any(keyword in fund_kind for keyword in ("股票", "混合", "指数", "QDII"))


def _candidate_tier(code: str, name: str, fund_type: str) -> str:
    if code in FUNDS or fund_type in {"broad_index", "consumer", "medical", "overseas"}:
        return "preferred"
    if any(keyword in name for keyword in ("指数", "ETF联接", "增强")):
        return "preferred"
    return "cautious"


def _fee_tag(name: str) -> str:
    if any(keyword in name for keyword in ("ETF联接", "指数", "增强")):
        return "低费率"
    return "普通费率"


def _sort_key(row: dict[str, object]) -> tuple[int, int, str]:
    code = str(row["fund_code"])
    watchlist_order = {fund_code: index for index, fund_code in enumerate(FUNDS)}
    tier_rank = {"preferred": 0, "cautious": 1}.get(str(row["candidate_tier"]), 2)
    if code in watchlist_order:
        return (0, watchlist_order[code], code)
    return (1, tier_rank, code)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build fund-tail candidate CSV from AKShare.")
    parser.add_argument("--output", default="config/fund_tail_candidates.csv")
    parser.add_argument("--limit", type=int, default=240)
    return parser.parse_args()


def main() -> None:
    import akshare as ak

    args = parse_args()
    rows = build_candidate_rows(ak.fund_name_em(), limit=args.limit)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(output, index=False)
    print(f"Wrote {len(rows)} fund-tail candidates to {output}")


if __name__ == "__main__":
    main()
