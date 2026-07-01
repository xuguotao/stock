# 2026-06-26 Tail ML Risk-Adjusted Smoke

## Scope

Smoke test after making model scoring and promotion risk-aware:

- Promotion gate rejects models whose `drawdown_breach_2pct_rate` is worse than baseline.
- Walk-forward model score now penalizes drawdown probability more heavily.
- Live model ranking reuses the same risk-adjusted score helper.

Environment and sample match the previous industry-context smoke:

- ClickHouse: `STOCK_CLICKHOUSE_HOST=<PRIVATE_CLICKHOUSE_HOST>`, database `stock`
- Universe: first 300 symbols from shared strategy tradable universe
- Sample window: `2026-03-30` to `2026-06-17`
- Training: walk-forward, `train_days=30`, `validation_days=10`, `top_n=2`

## Baseline Top2

- Selected days: 54
- Selected rows: 108
- Next-open win rate: 24.07%
- Next-high 1% hit rate: 55.56%
- Avg next-open return: -2.33%
- Avg next-high return: 1.88%
- Avg next-low drawdown: -5.35%
- Drawdown breach 2% rate: 80.56%
- Max consecutive losing selections: 17

## Risk-Adjusted Model Top2

- Status: ready
- Fold count: 2
- Sample count: 97,200
- Selected days: 20
- Selected rows: 40
- Next-high 1% hit rate: 85.00%
- Avg expected high return: 5.03%
- Avg realized next-high return: 5.04%
- Avg next-low drawdown: -2.98%
- Drawdown breach 2% rate: 52.50%

## Delta Versus Previous Industry Smoke

Previous industry-context model smoke:

- Next-high 1% hit rate: 82.50%
- Avg realized next-high return: 2.95%
- Avg next-low drawdown: -5.17%
- Drawdown breach 2% rate: 62.50%

Risk-adjusted smoke improvement:

- Hit rate: +2.50pp
- Avg next-high return: +2.09pp
- Avg next-low drawdown: improved by 2.19pp
- Drawdown breach 2% rate: -10.00pp

## Interpretation

Risk-aware scoring improved both upside and downside on the same 300-symbol smoke setup. Drawdown is still high in absolute terms, so this is not enough to declare the strategy production-ready. The next loop should evaluate stop-policy outcomes and require promotion gates to compare policy return, not just next-high opportunity.
