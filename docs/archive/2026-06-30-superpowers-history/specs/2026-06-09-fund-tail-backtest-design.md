# Fund Tail Backtest Design

## Goal

Build a repeatable research script that tests whether the daily 14:50 fund advice rules have historical value before using them as a decision aid.

## Scope

The first version covers the four funds in the current workflow:

- 天弘中证食品饮料ETF联接C `001632`
- 华宝纳斯达克精选股票(QDII)C `017437`
- 华夏中证500指数增强C `007995`
- 易方达蓝筹精选混合 `005827`

The script will use index or ETF proxy data to generate tail-session signals, then evaluate the following-day and multi-day returns on the target fund net value series where available. It is a research tool, not an automated trading system.

## Approach

Use two layers:

1. Signal layer: classify each trading day as `add`, `watch`, or `avoid` using proxy market data. Rules include same-day return, short moving-average position, recent momentum, and relative strength versus a broad benchmark.
2. Evaluation layer: apply those signal dates to the fund return series and measure forward 1-day, 3-day, 5-day, and 10-day returns, win rate, average return, and maximum adverse return.

This separates the question "was the market setup favorable at 14:50?" from "did the actual fund benefit after the signal?"

## Data

The implementation should support CSV input first so tests and real runs are deterministic. Network download can be added later or handled by existing scripts. Expected CSV columns are:

- `date`
- `close`
- optional `volume`

Each fund can have:

- a proxy series used for signal generation
- a fund NAV series used for forward-return evaluation

If NAV data is missing for a fund, the script may fall back to evaluating the proxy and clearly label that result.

## Output

The script should print a readable table per fund with:

- signal counts
- average forward returns for 1, 3, 5, and 10 trading days
- win rates for the same horizons
- worst forward return
- latest signal classification

It should also write a CSV report under `reports/`.

## Guardrails

The script must not claim that a rule guarantees future returns. It should show whether the rule had historical edge under the supplied data and make missing data explicit.
