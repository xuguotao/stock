import type { MootdxDailyQualityResponse } from '../../api/client'

export type DailyGapDisplayItem = MootdxDailyQualityResponse['missing_details'][number] & {
  block_missing_dates: string[]
}

export type DailyGapPayloadItem = Pick<DailyGapDisplayItem, 'symbol' | 'evidence'> & {
  start_date: string
  end_date: string
  trade_dates?: string[]
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
    trade_dates: item.block_missing_dates,
  }))
}

export function createDailyGapPreciseRepairPayload(items: DailyGapDisplayItem[]): DailyGapPayloadItem[] {
  return items.flatMap((item) => item.block_missing_dates
    .filter((tradeDate) => item.verification_by_date[tradeDate] === 'available')
    .map((tradeDate) => ({
      symbol: item.symbol,
      start_date: tradeDate,
      end_date: tradeDate,
      evidence: item.evidence,
    })))
}

export function createDailyGapPreciseRepairBatches(
  items: DailyGapDisplayItem[],
  batchSize = 100,
): DailyGapPayloadItem[][] {
  const payload = createDailyGapPreciseRepairPayload(items)
  return Array.from(
    { length: Math.ceil(payload.length / batchSize) },
    (_, index) => payload.slice(index * batchSize, (index + 1) * batchSize),
  )
}

type DailyGapJobStatus = { status: string }

export async function waitForDailyGapTerminalJob<T extends DailyGapJobStatus>(
  loadJob: () => Promise<T>,
  wait: () => Promise<void>,
): Promise<T> {
  let job = await loadJob()
  while (job.status === 'pending' || job.status === 'running') {
    await wait()
    job = await loadJob()
  }
  return job
}

export async function runDailyGapRepairBatches<T extends DailyGapJobStatus>(
  batches: DailyGapPayloadItem[][],
  createJob: (batch: DailyGapPayloadItem[]) => Promise<string>,
  waitForTerminalJob: (jobId: string) => Promise<T>,
): Promise<{ completed_batches: number; failed_batch_index: number | null; failed_status: string | null }> {
  let completedBatches = 0
  for (const [index, batch] of batches.entries()) {
    const job = await waitForTerminalJob(await createJob(batch))
    if (job.status !== 'success') {
      return { completed_batches: completedBatches, failed_batch_index: index, failed_status: job.status }
    }
    completedBatches += 1
  }
  return { completed_batches: completedBatches, failed_batch_index: null, failed_status: null }
}

export function restoreDailyGapSelection(
  items: DailyGapDisplayItem[],
  selectedSymbols: string[],
): DailyGapDisplayItem[] {
  const selected = new Set(selectedSymbols)
  return items.filter((item) => selected.has(item.symbol))
}
