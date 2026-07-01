# Zijin Monitor Design

## Goal

Build a local monitoring report for Zijin Mining that tracks the three practical drivers discussed in the research workflow: gold trend, copper trend, and project/production delivery.

## Scope

The first version generates a Markdown report on demand. It does not send notifications, place trades, scrape company announcements automatically, or run as a daemon.

## Data Sources

- Zijin A-share price and daily bars use the existing `DataAggregator` and Sina/AKShare data adapters.
- Gold and copper inputs are accepted as daily bar data by the monitor core. The CLI can use manual CSV files for these commodity series in the first version.
- Production delivery is read from a local YAML config so quarterly report numbers can be updated after company disclosures.

## Monitor Rules

Trend status is based on 20-day and 60-day moving averages:

- `strong`: latest close is above both averages.
- `neutral`: latest close is above the 60-day average but below the 20-day average, or the averages are not enough to confirm weakness.
- `weak`: latest close is below the 60-day average.

Production status compares actual year-to-date output with expected elapsed progress:

- `on_track`: actual progress is within 90% of expected progress.
- `watch`: actual progress is between 75% and 90% of expected progress.
- `behind`: actual progress is below 75% of expected progress.

## Output

The report is saved to `reports/zijin_monitor/YYYY-MM-DD.md` by default. It contains:

- Snapshot date and Zijin latest quote if available.
- Gold, copper, and Zijin trend states.
- Production delivery table for gold, copper, and lithium.
- Trigger summary for the user to review.

## Testing

Unit tests cover trend classification, production progress classification, and Markdown rendering. CLI network behavior is intentionally thin and is not unit-tested in the first version.
