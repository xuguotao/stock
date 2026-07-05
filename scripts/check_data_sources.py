#!/usr/bin/env python
"""Check external A-share data source availability."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_source_checks(
    *,
    symbol: str,
    tencent_source: Any | None = None,
    eastmoney_source: Any | None = None,
    cninfo_source: Any | None = None,
) -> list[dict[str, Any]]:
    """Run lightweight source checks and return structured rows."""
    if tencent_source is None:
        from src.data.tencent_source import TencentQuoteSource

        tencent_source = TencentQuoteSource(rate_limit=0.0)
    if eastmoney_source is None:
        from src.data.eastmoney_source import EastmoneyClient, EastmoneySignalSource

        eastmoney_source = EastmoneySignalSource(
            client=EastmoneyClient(min_interval=0.0, jitter=(0.0, 0.0))
        )
    if cninfo_source is None:
        from src.data.cninfo_source import CninfoAnnouncementSource

        cninfo_source = CninfoAnnouncementSource()

    rows = []
    rows.append(_check_tencent(tencent_source, symbol))
    rows.append(_check_eastmoney_concepts(eastmoney_source, symbol))
    rows.append(_check_eastmoney_fund_flow(eastmoney_source, symbol))
    rows.append(_check_cninfo(cninfo_source, symbol))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="000001.SZ", help="A-share symbol, e.g. 000001.SZ")
    args = parser.parse_args()

    rows = run_source_checks(symbol=args.symbol)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def _check_tencent(source: Any, symbol: str) -> dict[str, Any]:
    try:
        quotes = source.fetch_realtime_quotes([symbol])
        return {"source": "tencent", "ok": not quotes.empty, "detail": f"quotes={len(quotes)}"}
    except Exception as exc:
        return {"source": "tencent", "ok": False, "detail": str(exc)}


def _check_eastmoney_concepts(source: Any, symbol: str) -> dict[str, Any]:
    try:
        blocks = source.fetch_concept_blocks(symbol)
        total = int(blocks.get("total", 0))
        return {"source": "eastmoney_concepts", "ok": total > 0, "detail": f"blocks={total}"}
    except Exception as exc:
        return {"source": "eastmoney_concepts", "ok": False, "detail": str(exc)}


def _check_eastmoney_fund_flow(source: Any, symbol: str) -> dict[str, Any]:
    try:
        rows = source.fetch_minute_fund_flow(symbol)
        return {"source": "eastmoney_fund_flow", "ok": len(rows) > 0, "detail": f"rows={len(rows)}"}
    except Exception as exc:
        return {"source": "eastmoney_fund_flow", "ok": False, "detail": str(exc)}


def _check_cninfo(source: Any, symbol: str) -> dict[str, Any]:
    try:
        rows = source.fetch_announcements(symbol, page_size=3)
        return {"source": "cninfo", "ok": len(rows) > 0, "detail": f"announcements={len(rows)}"}
    except Exception as exc:
        return {"source": "cninfo", "ok": False, "detail": str(exc)}




if __name__ == "__main__":
    main()
