# 2026-06-26 Tail ML Industry Context Smoke

## Scope

Smoke test after adding live daily feature alignment and industry context features.

Environment:

- ClickHouse: `STOCK_CLICKHOUSE_HOST=<PRIVATE_CLICKHOUSE_HOST>`, database `stock`
- Universe: first 300 symbols from shared strategy tradable universe
- Sample window: `2026-03-30` to `2026-06-17`
- Training: walk-forward, `train_days=30`, `validation_days=10`, `top_n=2`

## Sample

- Symbols: 300
- Feature rows: 97,200
- Label rows: 97,200
- Sample rows: 97,200
- Trade dates: 54
- Null label rows: 0

Industry context columns present:

- `industry`
- `industry_ret_5`
- `industry_ret_20`
- `industry_breadth_20`
- `industry_relative_ret_5`
- `industry_relative_ret_20`

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

## Model Top2

- Status: ready
- Fold count: 2
- Sample count: 97,200
- Selected days: 20
- Selected rows: 40
- Next-high 1% hit rate: 82.50%
- Avg expected high return: 5.57%
- Avg realized next-high return: 2.95%
- Avg next-low drawdown: -5.17%
- Drawdown breach 2% rate: 62.50%

## Interpretation

Industry and market context features are wired into both training samples and live inference. The small smoke run shows a material improvement in next-high hit rate versus the rule baseline, but drawdown remains too high for direct trading. The next optimization loop should focus on risk control: down-rank candidates with poor next-low/risk probability, add explicit stop-policy evaluation, and promote models only when drawdown breach improves against baseline.
