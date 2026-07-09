import type {
  StockReadinessDimension,
  StockReadinessResponse,
  StockReadinessSummary,
} from '../../api/client'

export type {
  StockReadinessDimension,
  StockReadinessResponse,
  StockReadinessSummary,
}

export interface StockReadinessItem {
  symbol: string
  name: string
  market: string
  board: string
  dimensions: Record<string, StockReadinessDimension>
}

export type ReadinessDimensionKey = 'daily' | 'minute5' | 'snapshot' | 'xdxr'

export interface StockReadinessFilters {
  range: [string, string]
  dimensions: ReadinessDimensionKey[]
  status: string
  market: string
  board: string
  q: string
}
