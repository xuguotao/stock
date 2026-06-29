"""尾盘因子诊断：度量 tail_session / overnight_momentum 是否有预测力。"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.factor_analysis.ic_analysis import ICAnalyzer
from src.research.factor_analysis.quantile import QuantileAnalyzer
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor
from src.strategy.factors.tail_session import TailSessionFactor


def compute_overnight_forward_return(bars: pd.DataFrame) -> pd.DataFrame:
    """S01 隔夜持仓 forward return: open(t+1)/close(t) - 1。

    禁止用 ICAnalyzer.compute_forward_returns（收盘-收盘）。
    """
    bars = bars.sort_index()
    close = bars["close"].unstack(level="symbol")          # date × symbol
    nxt_open = bars["open"].unstack(level="symbol").shift(-1)
    overnight = (nxt_open / close - 1.0)
    return (
        overnight.stack(future_stack=True)
        .to_frame(name="return")
        .rename_axis(["date", "symbol"])["return"]
        .to_frame()
    )


def diagnose_factor(bars, factor, forward_returns, n_quantiles=5):
    fv = factor.compute(bars)
    ic = ICAnalyzer(forward_period=1)
    ic_series = ic.compute_ic(fv, forward_returns)
    rank_ic = ic.compute_rank_ic(fv, forward_returns)
    summary = ic.ic_summary(ic_series, rank_ic)
    qa = QuantileAnalyzer(n_quantiles=n_quantiles)
    qresult = qa.analyze(fv, forward_returns)
    return {
        "factor": factor.name,
        "ic": summary.to_dict(),
        "quantile": qresult.summary,
    }


def run_diagnosis(bars, n_quantiles=5):
    fr = compute_overnight_forward_return(bars)
    factors = [
        TailSessionFactor(breakout_window=20, trend_window=5, volume_ratio_threshold=1.2),
        OvernightMomentumFactor(smoothing_window=1),
    ]
    return {"forward_return": "overnight_open/close-1", "factors": [diagnose_factor(bars, f, fr, n_quantiles) for f in factors]}


def _default_symbols() -> list[str]:
    """Sample stock pool reused from scripts/test_phase3.py (live-aggregator fallback)."""
    return [
        "600519.SH", "000001.SZ", "300750.SZ", "000858.SZ", "601318.SH",
        "600036.SH", "000333.SZ", "601888.SH", "002714.SZ", "600900.SH",
    ]


def _symbols_in_cache(bars_dir: str | Path) -> list[str]:
    """Discover all symbols present in the offline parquet bar cache.

    Cache filenames follow ``{SYM}_{YYYYMMDD}_{YYYYMMDD}.parquet`` where SYM
    uses ``_`` in place of ``.`` (e.g. 600519.SH -> 600519_SH). Returning every
    symbol lets the offline-cache path load the full cache rather than a fixed
    sample list.
    """
    import re

    pattern = re.compile(r"^(.+)_(\d{8})_(\d{8})$")
    symbols: set[str] = set()
    for path in Path(bars_dir).glob("*.parquet"):
        match = pattern.match(path.stem)
        if not match:
            continue
        symbols.add(match.group(1).replace("_", "."))
    return sorted(symbols)


def _load_bars(args):
    """Load bars from a research dataset, the offline cache, or the live aggregator."""
    from datetime import date

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if args.bars_dataset:
        from src.strategy.tail_session.backtest import load_bars_from_research_dataset

        bars, _ = load_bars_from_research_dataset(args.bars_dataset, None, start, end)
        return bars

    if args.offline_cache:
        from src.strategy.tail_session.backtest import load_bars_from_offline_cache

        symbols = _symbols_in_cache(args.bars_cache_dir)
        return load_bars_from_offline_cache(args.bars_cache_dir, symbols, start, end)

    from src.data.aggregator import DataAggregator

    agg = DataAggregator()
    return agg.get_bars_batch(_default_symbols(), start, end)


def main():
    parser = argparse.ArgumentParser(description="Diagnose tail-session factors (IC/quantile).")
    parser.add_argument("--bars-dataset", help="parquet research dataset path")
    parser.add_argument("--offline-cache", action="store_true",
                        help="read bars from the local parquet cache (data/cache/bars)")
    parser.add_argument("--bars-cache-dir", default="data/cache/bars",
                        help="directory for --offline-cache parquet files")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-06-01")
    parser.add_argument("--n-quantiles", type=int, default=5)
    parser.add_argument("--out", default="reports/tail_session/factor_diagnosis.json")
    args = parser.parse_args()

    bars = _load_bars(args)
    result = run_diagnosis(bars, n_quantiles=args.n_quantiles)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
