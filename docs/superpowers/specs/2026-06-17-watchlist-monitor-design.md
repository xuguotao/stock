# Watchlist Monitor Design

## Goal

Build a dashboard-visible watchlist monitor that helps decide when followed stocks are close to a reasonable entry area. The first version focuses on analysis and status display inside the local web console. It does not send active notifications, place trades, or automatically modify broker/client watchlists.

## Scope

The monitor covers a configurable list of stocks and produces a structured daily analysis for each symbol. The initial watchlist is:

| Symbol | Name | Theme |
|---|---|---|
| `000636` | 风华高科 | MLCC / 被动元件 |
| `002859` | 洁美科技 | MLCC 耗材 / 载带 |
| `300285` | 国瓷材料 | MLCC 上游材料 |
| `300408` | 三环集团 | MLCC / 陶瓷元件 |
| `300014` | 亿纬锂能 | 电池 / 储能 |
| `688017` | 绿的谐波 | 机器人 / 减速器 |
| `601899` | 紫金矿业 | 金铜资源 |

The first version supports manual page refresh and backend API refresh. Scheduled jobs and push notifications are out of scope, but the analysis model will expose trigger statuses that later notification channels can reuse.

## User Workflow

1. User opens the web dashboard and navigates to a new watchlist monitor page.
2. The page shows a compact table for the followed stocks.
3. Each row shows latest price, daily change, 5-day return, 20-day return, volume condition, monitor status, and distance to the configured entry zone.
4. User can open a stock detail panel or section to read the short analysis text, key levels, and rule triggers.
5. User uses the status as a decision aid, not as automatic trading advice.

## Configuration

Add `config/watchlist_monitor.yaml` as the source of truth for the first version. Each stock entry contains:

- `symbol`: A-share code.
- `name`: Display name.
- `theme`: Business or market theme.
- `notes`: Short investment logic.
- `levels`: Manual levels for observation, entry, add, invalidation, and optional breakout confirmation.

Example shape:

```yaml
stocks:
  - symbol: "601899"
    name: "紫金矿业"
    theme: "金铜资源"
    notes: "关注金铜价格、Q2利润和现金流延续性。"
    levels:
      observe: [30.0, 30.5]
      entry: [29.5, 29.8]
      add: [28.5, 29.0]
      invalid: 27.0
      breakout: 32.0
```

Manual levels are intentional. The module should not pretend to infer perfect buy prices from price history. It combines user-defined levels with objective trend and volume context.

## Backend Design

Add `src/monitoring/watchlist.py` with pure analysis helpers and dataclasses:

- `WatchlistConfig`
- `WatchlistStockConfig`
- `WatchlistLevels`
- `WatchlistStockSnapshot`
- `WatchlistReport`

Core helper responsibilities:

- Normalize symbols through existing core constants.
- Fetch latest quote and daily bars through existing data sources where possible.
- Calculate 5-day and 20-day returns.
- Calculate 5-day and 20-day moving averages.
- Detect short-term volume expansion by comparing latest volume with recent average volume.
- Classify each stock into one monitor status.

Status values:

| Status | Meaning |
|---|---|
| `hot_wait` | Price has run too fast or is above the preferred entry area; wait for pullback. |
| `watch_pullback` | Price is approaching observation levels but has not entered the entry zone. |
| `entry_zone` | Price is inside the configured first-entry area. |
| `add_zone` | Price is inside the configured add area while invalidation has not triggered. |
| `breakout_confirm` | Price has broken above the configured breakout level with acceptable volume. |
| `risk_off` | Price has broken the invalidation level or trend has materially weakened. |
| `neutral` | No actionable condition is active. |

Add `src/web/backend/watchlist_monitor.py` with API-facing functions:

- `get_watchlist_report(trade_date: date | None = None) -> dict`
- optional `render_watchlist_markdown(report) -> str`

Add FastAPI routes in `src/web/backend/app.py`:

- `GET /api/watchlist-monitor/report`
- `GET /api/watchlist-monitor/config`

The report endpoint returns structured JSON suitable for the Vue page. Markdown rendering is useful for local saved reports but is not required for the page to function.

## Frontend Design

Add `frontend/src/pages/WatchlistMonitor.vue` and link it from the existing navigation in `frontend/src/App.vue`.

The page contains:

- Summary cards: number of stocks in `entry_zone`, `watch_pullback`, `hot_wait`, and `risk_off`.
- Main table with symbol, name, theme, latest price, daily change, 5-day return, 20-day return, volume status, monitor status, and distance to entry.
- Detail area for the selected stock with levels, triggered rules, and analysis text.
- Refresh button that refetches the backend report.

The visual style should follow the existing dashboard pages. Avoid trading-terminal clutter in the first version; the important state should be scannable.

## Analysis Rules

The rule order is deterministic:

1. If latest price is below or equal to `invalid`, classify `risk_off`.
2. If latest price is inside `add`, classify `add_zone`.
3. If latest price is inside `entry`, classify `entry_zone`.
4. If latest price is inside `observe` or within 2% above the observe upper bound, classify `watch_pullback`.
5. If latest price is above `breakout` and latest volume is at least 1.2 times recent average volume, classify `breakout_confirm`.
6. If 5-day return is above 15% or 20-day return is above 35%, classify `hot_wait` unless a stronger status above already applied.
7. Otherwise classify `neutral`.

Each result includes a human-readable reason list so the user can see why the status was assigned.

## Error Handling

- If latest quote is unavailable, return the stock row with `data_status: "quote_unavailable"` and keep configured levels visible.
- If daily bars are unavailable, return quote-driven fields and omit return/moving-average metrics.
- If the config file is missing or malformed, the API returns a clear 500 response with the config path and validation problem.
- Data-source failures do not break the whole report; they are recorded per symbol.

## Testing

Unit tests should cover:

- Config parsing.
- Status classification for each status.
- Return and volume metric calculation from small in-memory daily bar frames.
- API response shape for a fixture report.

Frontend tests should verify:

- The watchlist page renders summary cards and table rows from mocked API data.
- Status labels and detail reasons are visible.
- Refresh action calls the report endpoint.

## Non-Goals

- No automatic buy/sell orders.
- No active notifications in the first version.
- No scraping of private forums or unofficial rumors.
- No AI-generated price targets.
- No dependency on a single unstable market-data endpoint when existing data adapters can provide fallback behavior.

## Acceptance Criteria

- Running the backend exposes `/api/watchlist-monitor/report`.
- The frontend has a watchlist monitor page accessible from navigation.
- The page displays all seven initial stocks.
- Each stock has a monitor status and actionable reason text.
- The status logic is deterministic and covered by tests.
- The implementation can later add notifications without changing the report schema materially.
