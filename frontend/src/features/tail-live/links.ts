export function stockTrendUrl(symbol: string, options: { tradeDate?: string } = {}) {
  const params = new URLSearchParams({ granularity: '5m' })
  if (options.tradeDate) params.set('trade_date', options.tradeDate)
  return `/stock-trend/${encodeURIComponent(symbol)}?${params.toString()}`
}
