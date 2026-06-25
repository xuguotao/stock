# 2026-06-26 Tail ML Smoke Experiment

## Scope

This smoke run validated the new market-context feature pipeline against ClickHouse data without promoting a model for live use.

- Data source: ClickHouse `stock`
- Window: `2026-01-08` to `2026-06-24`
- Universe: first 500 symbols from the strategy-tradable universe ranked by liquidity
- Samples: 326,322 rows
- Symbols: 500
- Trade dates: 109
- Null labels: 0
- Model: `HistGradientBoostingClassifier/Regressor`
- Walk-forward: train 60 days, validate 10 days, Top2
- Artifact: local ignored path `models/tail_session/tail-market-context-20260626-smoke`

## Added Feature Evidence

The sample builder produced the new market-context columns:

- `market_ret_5`
- `market_breadth_20`
- `relative_ret_5`
- `tail_volume_ratio`

These fields now flow into `DEFAULT_FEATURE_COLUMNS`, and live inference maps UI/live fields such as `tail_return` and `volume_ratio` to the training feature names before scoring.

## Same-Sample Rule Baseline

| Top N | Selected days | Next-high >1% hit | Avg next-open | Avg next-high | Avg next-low | Drawdown breach |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 109 | 58.72% | -2.49% | 2.43% | -5.97% | 79.82% |
| 2 | 109 | 58.26% | -2.84% | 2.09% | -6.41% | 81.19% |
| 3 | 109 | 55.35% | -3.32% | 1.64% | -6.88% | 83.18% |

## Model Smoke Result

| Metric | Value |
|---|---:|
| Validation selected days | 40 |
| Selected rows | 80 |
| Next-high >1% hit | 86.25% |
| Avg expected high return | 6.27% |
| Avg realized next-high return | 6.78% |
| Avg next-low drawdown | -1.48% |
| Drawdown breach 2% | 55.00% |

## Interpretation

The model strongly outperformed the rule baseline on this 500-symbol smoke universe. This is promising but not enough for production promotion because the run was intentionally constrained to a liquidity-ranked subset. A promotion-quality run should use the full strategy-tradable universe or an explicitly documented production universe, persist baseline and promotion metadata through the training API, and then be promoted from the model lab.

## Next Work

- Run a production-size training job from the model lab or API.
- Add feature-importance or feature-delta explanations to model manifests and live results.
- Persist model/baseline runs into ClickHouse for longer-term comparison.
