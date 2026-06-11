#!/usr/bin/env python
"""Run a CSV-based backtest for fund tail-session advice rules."""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.fund_tail_backtest import (
    append_latest_row,
    classify_tail_signals,
    evaluate_latest_condition,
    evaluate_forward_returns,
    normalize_akshare_cni_index,
    normalize_akshare_index,
    normalize_akshare_nav,
    normalize_akshare_us_daily,
    select_proxy_series,
    summarize_latest_signal,
    to_chinese_report,
)


FUNDS = {
    "001632": "天弘中证食品饮料ETF联接C",
    "017437": "华宝纳斯达克精选股票(QDII)C",
    "007995": "华夏中证500指数增强C",
    "161604": "融通深证100指数A",
    "161005": "富国天惠成长混合(LOF)A",
    "162412": "华宝医疗ETF联接A",
    "161028": "富国中证新能源汽车指数(LOF)A",
    "000696": "汇添富环保行业股票",
    "260108": "景顺长城新兴成长混合A",
    "000977": "长城环保主题混合A",
    "012968": "广发行业严选三年持有期混合C",
    "320007": "诺安成长混合A",
    "110020": "易方达沪深300ETF联接A",
    "163406": "兴全合润混合A",
    "004851": "广发医疗保健股票A",
    "005827": "易方达蓝筹精选混合",
}

PROXY_INDEXES = {
    "001632": ("cni", "399396", "sz399396"),  # 国证食品
    "017437": ("us_sina", "QQQ"),  # Invesco QQQ ETF
    "007995": ("csindex", "000905", "sh000905"),  # 中证500
    "161604": ("cni", "399330", "sz399330"),  # 深证100
    "161005": ("csindex", "000300", "sh000300"),  # 主动成长混合，宽基代理
    "162412": ("csindex", "399989", "sz399989"),  # 中证医疗
    "161028": ("csindex", "399976", "sz399976"),  # 中证新能源汽车
    "000696": ("csindex", "000827", "sh000827"),  # 中证环保
    "260108": ("csindex", "000300", "sh000300"),  # 主动成长混合，宽基代理
    "000977": ("csindex", "000827", "sh000827"),  # 中证环保
    "012968": ("csindex", "000300", "sh000300"),  # 主动行业混合，宽基代理
    "320007": ("cni", "399006", "sz399006"),  # 成长/科技风格，创业板代理
    "110020": ("csindex", "000300", "sh000300"),  # 沪深300
    "163406": ("csindex", "000300", "sh000300"),  # 主动混合，宽基代理
    "004851": ("csindex", "399989", "sz399989"),  # 医疗主题
    "005827": ("csindex", "000300", "sh000300"),  # 沪深300
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest fund tail-session advice rules from CSV inputs."
    )
    parser.add_argument(
        "--data-dir",
        default="data/fund_tail",
        help="Directory containing <fund_code>_proxy.csv, optional <fund_code>_nav.csv, and optional benchmark.csv.",
    )
    parser.add_argument(
        "--report",
        default="reports/fund_tail_backtest.csv",
        help="Output Chinese CSV report path.",
    )
    parser.add_argument(
        "--raw-report",
        default="reports/fund_tail_backtest_raw.csv",
        help="Output raw English/internal CSV report path.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download fund NAV and mapped proxy index CSV files with AKShare before running.",
    )
    parser.add_argument(
        "--start-date",
        default="20200101",
        help="Start date for proxy index download when --download is used.",
    )
    parser.add_argument(
        "--end-date",
        default="20500101",
        help="End date for proxy index download when --download is used.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing input file: {path}")
    return pd.read_csv(path)


def download_proxy_index(provider: str, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    if provider == "cni":
        return normalize_akshare_cni_index(
            ak.index_hist_cni(symbol=symbol, start_date=start_date, end_date=end_date)
        )
    if provider == "csindex":
        return normalize_akshare_index(
            ak.stock_zh_index_hist_csindex(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
        )
    if provider == "us_sina":
        proxy = normalize_akshare_us_daily(ak.stock_us_daily(symbol=symbol, adjust=""))
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        return proxy[(proxy["date"] >= start) & (proxy["date"] <= end)].reset_index(drop=True)
    raise ValueError(f"unsupported proxy provider: {provider}")


def download_sina_realtime_index(sina_symbol: str) -> pd.DataFrame:
    url = f"https://hq.sinajs.cn/list={sina_symbol}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        text = resp.read().decode("gb18030")
    payload = text.split('"', 2)[1]
    parts = payload.split(",")
    if len(parts) < 32 or not parts[30]:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "date": [parts[30]],
            "close": [float(parts[3])],
            "volume": [float(parts[8])],
        }
    )


def download_inputs(data_dir: Path, start_date: str, end_date: str) -> None:
    import akshare as ak

    data_dir.mkdir(parents=True, exist_ok=True)
    for code in FUNDS:
        nav = ak.fund_open_fund_info_em(
            symbol=code,
            indicator="单位净值走势",
            period="成立来",
        )
        nav_series = normalize_akshare_nav(nav)
        nav_series.to_csv(data_dir / f"{code}_nav.csv", index=False)

        proxy_spec = PROXY_INDEXES.get(code)
        if proxy_spec is None:
            nav_series.to_csv(data_dir / f"{code}_proxy.csv", index=False)
            continue

        provider, proxy_code, *realtime = proxy_spec
        try:
            proxy_series = download_proxy_index(provider, proxy_code, start_date, end_date)
        except Exception as exc:
            print(
                f"Warning: proxy index {provider}:{proxy_code} failed for {code}, "
                f"using fund NAV as proxy: {exc}"
            )
            proxy_series = None
        selected_proxy = select_proxy_series(nav=nav_series, proxy=proxy_series)
        if realtime and selected_proxy is not nav_series:
            try:
                selected_proxy = append_latest_row(
                    selected_proxy,
                    download_sina_realtime_index(realtime[0]),
                )
            except Exception as exc:
                print(f"Warning: realtime index {realtime[0]} failed for {code}: {exc}")
        selected_proxy.to_csv(
            data_dir / f"{code}_proxy.csv",
            index=False,
        )

    try:
        benchmark = append_latest_row(
            download_proxy_index("csindex", "000300", start_date, end_date),
            download_sina_realtime_index("sh000300"),
        )
        benchmark.to_csv(
            data_dir / "benchmark.csv",
            index=False,
        )
    except Exception as exc:
        print(f"Warning: benchmark index 000300 failed, running without benchmark: {exc}")


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    if args.download:
        download_inputs(data_dir, args.start_date, args.end_date)

    benchmark_path = data_dir / "benchmark.csv"
    benchmark = read_csv(benchmark_path) if benchmark_path.exists() else None

    rows = []
    for code, name in FUNDS.items():
        proxy = read_csv(data_dir / f"{code}_proxy.csv")
        nav_path = data_dir / f"{code}_nav.csv"
        nav = read_csv(nav_path) if nav_path.exists() else proxy

        signals = classify_tail_signals(proxy, benchmark=benchmark)
        metrics = evaluate_forward_returns(signals, nav)
        condition = evaluate_latest_condition(signals, nav)
        rows.append(summarize_latest_signal(name, code, signals, metrics, condition))

    report = pd.DataFrame(rows)
    raw_report_path = Path(args.raw_report)
    raw_report_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(raw_report_path, index=False)

    chinese_report = to_chinese_report(report)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    chinese_report.to_csv(report_path, index=False)

    print(chinese_report.to_string(index=False))
    print(f"Report written to {report_path}")
    print(f"Raw report written to {raw_report_path}")


if __name__ == "__main__":
    main()
