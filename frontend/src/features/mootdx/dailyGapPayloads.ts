import type { MootdxDailyQualityResponse } from '../../api/client'

export type DailyGapDisplayItem = MootdxDailyQualityResponse['missing_details'][number] & {
  block_missing_dates: string[]
}

export type DailyGapPayloadItem = Pick<DailyGapDisplayItem, 'symbol' | 'evidence'> & {
  start_date: string
  end_date: string
}

export function createDailyGapRepairPayload(
  items: DailyGapDisplayItem[],
  selectedTradeDate: string,
): DailyGapPayloadItem[] {
  return items.map((item) => ({
    symbol: item.symbol,
    start_date: selectedTradeDate,
    end_date: selectedTradeDate,
    evidence: item.evidence,
  }))
}

export function createDailyGapVerifyPayload(items: DailyGapDisplayItem[]): DailyGapPayloadItem[] {
  return items.map((item) => ({
    symbol: item.symbol,
    start_date: item.block_missing_dates[0],
    end_date: item.block_missing_dates.at(-1) ?? item.block_missing_dates[0],
    evidence: item.evidence,
  }))
}
