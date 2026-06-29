"""盘后七步法复盘数据查询（基于 ClickHouse stock_quote_snapshots 当日末次快照）。

取当日每只 symbol 的最后一条快照(argMax by snapshot_at)，输出七步法复盘需要的核心统计：
  第1步 涨停/跌停/涨跌家数 + 炸板(触板未封，需1m，暂标注待补)
  第4步 成交额前排
  第5步 跌停票共性
  第6步 标记重点(逆势走强/底部异动等候选)

用法:
  python scripts/daily_review_snapshot.py            # 默认今天
  python scripts/daily_review_snapshot.py 2026-06-29  # 指定日期
"""
from __future__ import annotations

import sys
from datetime import date

sys.path.insert(0, ".")

from config.settings import get_settings
from clickhouse_driver import Client


def get_client() -> Client:
    s = get_settings().clickhouse
    return Client(
        host=s.host,
        port=getattr(s, "port", 9000),
        user=s.user,
        password=s.password,
        database=s.database,
    )


def latest_snapshot_subquery(d: date) -> str:
    """当日每只 symbol 末次快照的子查询。"""
    return f"""
SELECT
    symbol,
    argMax(name, snapshot_at) AS name,
    argMax(price, snapshot_at) AS price,
    argMax(change_pct, snapshot_at) AS change_pct,
    argMax(volume, snapshot_at) AS volume,
    argMax(amount, snapshot_at) AS amount,
    argMax(turnover_pct, snapshot_at) AS turnover_pct,
    argMax(pe_ttm, snapshot_at) AS pe_ttm,
    argMax(mcap, snapshot_at) AS mcap,
    argMax(float_mcap, snapshot_at) AS float_mcap,
    argMax(limit_up, snapshot_at) AS limit_up,
    argMax(limit_down, snapshot_at) AS limit_down,
    argMax(volume, snapshot_at) AS volume
FROM stock_quote_snapshots
WHERE toDate(snapshot_at) = '{d.isoformat()}'
GROUP BY symbol
"""


def fmt_amt(x: float) -> str:
    return f"{x/1e8:.1f}亿"


def main(d: date) -> None:
    client = get_client()
    q = latest_snapshot_subquery(d)

    print(f"# {d.isoformat()} 盘后复盘数据（ClickHouse 末次快照）\n")

    # ---- 第1步：情绪 = 涨停/跌停/涨跌家数 ----
    r = client.execute(
        f"""
    SELECT
        count() AS total,
        countIf(price > 0) AS valid,
        countIf(limit_up > 0 AND price >= limit_up * 0.999) AS limit_up_cnt,
        countIf(limit_down > 0 AND price <= limit_down * 1.001) AS limit_down_cnt,
        countIf(change_pct > 0) AS up_cnt,
        countIf(change_pct < 0) AS down_cnt,
        countIf(change_pct = 0) AS flat_cnt,
        round(sum(amount)/1e8, 0) AS total_amount_yi
    FROM ({q})
    """
    )[0]
    print("## 1. 看情绪")
    print(f"- 总数 {r[0]} | 涨停 {r[2]} | 跌停 {r[3]} | 上涨 {r[4]} | 下跌 {r[5]} | 平 {r[6]}")
    print(f"- 全市场成交额 {r[7]:.0f} 亿")
    print("- 炸板数：需 1m 快照聚合检测「触板未封」，待补脚本")
    print(f"- 涨跌家数比：{r[4]}:{r[5]}，{'赚钱效应偏强' if r[4] > r[5] else '亏钱效应偏强'}\n")

    # ---- 涨停股清单（按成交额前 20） ----
    print("## 涨停股清单（按成交额前 20）")
    rows = client.execute(
        f"""
    SELECT symbol, name, change_pct, amount, turnover_pct, float_mcap, limit_up
    FROM ({q})
    WHERE limit_up > 0 AND price >= limit_up * 0.999 AND price > 0
    ORDER BY amount DESC LIMIT 20
    """
    )
    print(f"共 {r[2]} 只涨停，前 20：")
    print(f"{'#':>3} {'symbol':<10} {'name':<10} {'涨幅%':>6} {'成交额':>8} {'换手%':>6} {'流通市值':>8}")
    for i, row in enumerate(rows, 1):
        print(f"{i:>3} {row[0]:<10} {row[1]:<10} {row[2]:>6.2f} {fmt_amt(row[3]):>8} {row[4]:>6.1f} {row[5]/1e8:>7.0f}亿")
    print()

    # ---- 第4步：资金 = 成交额前 20 ----
    print("## 4. 看资金（成交额前 20）")
    rows = client.execute(
        f"""
    SELECT symbol, name, change_pct, amount, turnover_pct
    FROM ({q})
    WHERE price > 0
    ORDER BY amount DESC LIMIT 20
    """
    )
    print(f"{'#':>3} {'symbol':<10} {'name':<10} {'涨幅%':>6} {'成交额':>8} {'换手%':>6}")
    for i, row in enumerate(rows, 1):
        print(f"{i:>3} {row[0]:<10} {row[1]:<10} {row[2]:>6.2f} {fmt_amt(row[3]):>8} {row[4]:>6.1f}")
    print()

    # ---- 第5步：亏钱效应 = 跌停票共性 ----
    print("## 5. 看亏钱效应（跌停票）")
    rows = client.execute(
        f"""
    SELECT symbol, name, change_pct, amount, float_mcap
    FROM ({q})
    WHERE limit_down > 0 AND price <= limit_down * 1.001 AND price > 0
    ORDER BY float_mcap DESC LIMIT 20
    """
    )
    print(f"共 {r[3]} 只跌停，按流通市值前 20：")
    print(f"{'#':>3} {'symbol':<10} {'name':<10} {'涨幅%':>7} {'成交额':>8} {'流通市值':>8}")
    for i, row in enumerate(rows, 1):
        print(f"{i:>3} {row[0]:<10} {row[1]:<10} {row[2]:>7.2f} {fmt_amt(row[3]):>8} {row[4]/1e8:>7.0f}亿")
    print("- 跌停票是高位补跌还是集体退潮：需结合连板数据判断（待补）\n")

    # ---- 第6步候选：逆势走强（涨幅≥5% + 换手≥5% + 成交额≥2亿） ----
    print("## 6. 标记重点候选（逆势走强：涨幅≥5% 且 换手≥5% 且 成交≥2亿，前 15）")
    rows = client.execute(
        f"""
    SELECT symbol, name, change_pct, amount, turnover_pct
    FROM ({q})
    WHERE price > 0 AND change_pct >= 5 AND turnover_pct >= 5 AND amount >= 2e8
    ORDER BY change_pct DESC, amount DESC LIMIT 15
    """
    )
    print(f"{'#':>3} {'symbol':<10} {'name':<10} {'涨幅%':>6} {'成交额':>8} {'换手%':>6}")
    for i, row in enumerate(rows, 1):
        print(f"{i:>3} {row[0]:<10} {row[1]:<10} {row[2]:>6.2f} {fmt_amt(row[3]):>8} {row[4]:>6.1f}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    main(date.fromisoformat(arg))
